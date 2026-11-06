"""Version A (single ReAct agent), offline: the fake model replays the agent's tool calls; sandbox, logs and
evaluator are real."""
import json
import os
import time
from pathlib import Path

import pytest

from p2e import llm, runner
from p2e.llm import Agent, Budget, BudgetExceeded, Trace, sandbox_tools
from p2e.models import Entry, get_profile
from p2e.sandbox import Sandbox
from p2e.schemas import DiscrepancyReport, Metrics, PaperSpec
from p2e.testing import ENV, GT_SEED, SPEC, FakeClient, _diag, _run_spec, _set_target, use_fake
from p2e.versions import load

single_agent = load("SingleAgent")


def test_single_agent_submits_metrics_and_diagnosis(toy_case, monkeypatch):
    _set_target(85.0, [GT_SEED])
    fake = FakeClient({single_agent.SYSTEM[:30]: [
        [("run_shell", {"command": f"git clone -q {toy_case} repo"})],                 # cmd_001
        [("run_shell", {"command": "python3 repo/train.py --seed 0"})],                # cmd_002
        [("run_shell", {"command": "python3 repo/train.py --seed 1"})],                # cmd_003
        # a diagnosis without its category is rejected and resubmitted
        [("submit", {"metrics": {"claims": []}, "diagnosis": {"claims": [{**_diag("discrepancy"), "category": None}]}})],
        [("submit", {"metrics": {"claims": [{"claim_id": "acc", "values": [80.0, 81.0],
                                             "evidence": ["logs/cmd_002_shell.log", "logs/cmd_003_shell.log"]}]},
                     "diagnosis": {"claims": [_diag("discrepancy", "reproducer_error", "we probably broke it")]}})],
    ]})
    use_fake(monkeypatch, fake)
    ctx = runner.new_run("toy", "single")
    result = single_agent.run(ctx)

    assert result.verdict == "fail" and result.claims[0].evidence_ok  # numbers still checked against the logs
    assert DiscrepancyReport.load(ctx.run_dir).claims[0].status == "discrepancy"
    dg = result.diagnosis
    assert dg.present and dg.detection == 1.0 and dg.false_success == [] and dg.attribution == 0.0


def test_brief_preregisters_the_criterion_without_the_target(toy_case):
    _set_target(85.0, [GT_SEED])
    brief = runner.new_run("toy", "single").task_brief()
    assert "Reproduced if: the mean over at least 2 seed runs is within ±1 percentage points (absolute) of the paper value" in brief
    # no target value, nothing from the hidden root-cause entry
    assert "85" not in brief and "seed variance" not in brief and "randomness" not in brief


def test_single_agent_mean_submission_is_sent_back(toy_case, monkeypatch):
    fake = FakeClient({single_agent.SYSTEM[:30]: [
        [("run_shell", {"command": f"git clone -q {toy_case} repo"})],                 # cmd_001
        [("run_shell", {"command": "python3 repo/train.py --seed 0"})],                # cmd_002
        [("run_shell", {"command": "python3 repo/train.py --seed 1"})],                # cmd_003
        # the mean of the two runs as one value: rejected at submission
        [("submit", {"metrics": {"claims": [{"claim_id": "acc", "values": [80.5],
                                             "evidence": ["logs/cmd_002_shell.log", "logs/cmd_003_shell.log"]}]},
                     "diagnosis": {"claims": [_diag("reproduced", conclusion="matches")]}})],
        [("submit", {"metrics": {"claims": [{"claim_id": "acc", "values": [80.0, 81.0],
                                             "evidence": ["logs/cmd_002_shell.log", "logs/cmd_003_shell.log"]}]},
                     "diagnosis": {"claims": [_diag("reproduced", conclusion="matches")]}})],
    ]})
    use_fake(monkeypatch, fake)
    ctx = runner.new_run("toy", "single")
    result = single_agent.run(ctx)
    assert result.verdict == "full" and fake.n == 5
    events = [json.loads(l) for l in (ctx.run_dir / "trace.jsonl").read_text().splitlines()]
    assert any(e["event"] == "tool_result" and e["is_error"] and "one value per seed run" in e["output"] for e in events)


