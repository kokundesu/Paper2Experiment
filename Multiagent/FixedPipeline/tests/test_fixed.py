"""Version B (fixed pipeline), offline: role scripts replayed by a fake model; sandbox, executor, checkpoint and
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

multi_agent = load("FixedPipeline")


def test_multi_agent_end_to_end_with_debug(toy_case, monkeypatch):
    env, run_spec = ENV, _run_spec

    scripts = {
        multi_agent.ANALYST[:30]: [[("submit", {**SPEC, "claims": [{"claim_id": "acc", "protocol": "p"}]})]],
        multi_agent.ENV[:30]: [[("run_shell", {"command": f"git clone -q {toy_case} repo"})], [("submit", env)]],
        # Planner gets the regex wrong; the executor finds no metric and the Debugger fixes it.
        multi_agent.PLANNER[:30]: [[("submit", {"rationale": "r", "runs": [run_spec(0, r"acc= ([0-9.]+)"),
                                                                           run_spec(1, r"acc= ([0-9.]+)")]})]],
        multi_agent.DEBUGGER[:30]: [[("submit", {"diagnosis": "regex did not match", "changes": [],
                                                 "revised_runs": [run_spec(0, r"Test accuracy: ([0-9.]+)"),
                                                                  run_spec(1, r"Test accuracy: ([0-9.]+)")]})]],
        multi_agent.REVIEWER[:30]: [[("submit", {"assessment": "pilot matches the paper's protocol; setup faithful"})]],
        # The analyst runs a cheap diagnostic (it must not change the metrics) and judges the claim reproduced.
        multi_agent.ANALYST_DISCREPANCY[:30]: [[("run_shell", {"command": "tail -n 3 ../logs/*exp_acc_s0.log"})],
                                               [("submit", {"claims": [_diag("reproduced", conclusion="matches")]})]],
    }
    fake = FakeClient(scripts)
    use_fake(monkeypatch, fake)

    ctx = runner.new_run("toy", "multi")
    result = multi_agent.run(ctx)

    assert result.verdict == "full", (ctx.run_dir / "summary.json").read_text()
    metrics = Metrics.model_validate_json((ctx.run_dir / "metrics.json").read_text())
    assert sorted(metrics.claims[0].values) == pytest.approx([80.0, 81.0])
    for name in ("paper_spec.json", "env_report.json", "plan.json", "debug_1.json", "review.json",
                 "discrepancy_report.json", "eval.json", "summary.json"):
        assert (ctx.run_dir / name).exists(), name
    summary = json.loads((ctx.run_dir / "summary.json").read_text())
    assert summary["model"] == "gpt-6-luna" and summary["llm"]["requests"] == 8
    assert summary["diagnosis"]["present"] and summary["diagnosis"]["n_failing"] == 0
    assert result.diagnosis.false_success == [] and result.diagnosis.detection is None
    starts = [json.loads(l) for l in (ctx.run_dir / "trace.jsonl").read_text().splitlines()]
    analyst = next(r for r in starts if r["agent"] == "discrepancy_analyst" and r["event"] == "start")
    assert "acc_s0" in analyst["task"] and "logs/cmd_" in analyst["task"]  # measured values and their logs
    effort = {r["agent"]: r["effort"] for r in starts if r["event"] == "start" and "effort" in r}
    assert effort["result_reviewer"] == effort["discrepancy_analyst"] == llm.REVIEW_EFFORT == "high"
    assert effort["planner"] == effort["env_agent"] == llm.DEFAULT_EFFORT


def _multi_scripts(toy_case, analyst_turns):
    return {
        multi_agent.ANALYST[:30]: [[("submit", {**SPEC, "claims": [{"claim_id": "acc", "paper_value": 85.0, "protocol": "p"}]})]],
        multi_agent.ENV[:30]: [[("run_shell", {"command": f"git clone -q {toy_case} repo"})], [("submit", ENV)]],
        multi_agent.PLANNER[:30]: [[("submit", {"rationale": "r", "runs": [_run_spec(0), _run_spec(1)]})]],
        multi_agent.REVIEWER[:30]: [[("submit", {"assessment": "pilot matches the paper's protocol; setup faithful"})]],
        multi_agent.ANALYST_DISCREPANCY[:30]: analyst_turns,
    }


def test_multi_agent_analyst_diagnoses_a_miss(toy_case, monkeypatch):
    _set_target(85.0, [GT_SEED])
    fake = FakeClient(_multi_scripts(toy_case, [
        [("run_shell", {"command": "cd repo && for s in 2 3; do python3 train.py --seed $s; done"})],
        [("submit", {"claims": [_diag("discrepancy", "environment", "seed variance explains the gap",
                                      "logs/cmd_004_shell.log")]})]]))
    use_fake(monkeypatch, fake)
    ctx = runner.new_run("toy", "multi")
    result = multi_agent.run(ctx)

    assert result.verdict == "fail"
    metrics = Metrics.model_validate_json((ctx.run_dir / "metrics.json").read_text())
    assert sorted(metrics.claims[0].values) == pytest.approx([80.0, 81.0])  # diagnostic runs (seeds 2, 3) not counted
    report = DiscrepancyReport.load(ctx.run_dir)
    assert report.claims[0].category == "environment"
    dg = result.diagnosis
    assert dg.detection == 1.0 and dg.attribution == 1.0 and dg.evidence_recall == 1.0  # also_acceptable counts
    summary = json.loads((ctx.run_dir / "summary.json").read_text())["diagnosis"]
    assert summary["n_detected"] == 1 and summary["n_attribution_correct"] == 1


def test_multi_agent_skips_analyst_when_budget_is_spent(toy_case, monkeypatch):
    _set_target(85.0, [GT_SEED])
    fake = FakeClient(_multi_scripts(toy_case, [[("submit", {"claims": []})]]))
    use_fake(monkeypatch, fake)
    ctx = runner.new_run("toy", "multi")
    # 4 requests of $0.0002 reach the planner; the reviewer's and the analyst's checks see the budget spent
    ctx.budget.limit_usd = ctx.budget.reserve_usd + 0.0007
    result = multi_agent.run(ctx)

    assert fake.n == 4 and not (ctx.run_dir / "discrepancy_report.json").exists()
    assert result.verdict == "fail" and result.claims[0].n_values == 2  # still scored
    assert not result.diagnosis.present and result.diagnosis.note == "no diagnosis"
    assert result.diagnosis.detection == 0.0 and result.diagnosis.attribution == 0.0
    events = [json.loads(l) for l in (ctx.run_dir / "trace.jsonl").read_text().splitlines()]
    assert any(e["agent"] == "discrepancy_analyst" and e["event"] == "skipped" for e in events)
    assert any(e["agent"] == "result_reviewer" and e["event"] == "skipped" for e in events)


def test_multi_agent_reviewer_fixes_setup_error_after_pilot(toy_case, monkeypatch):
    # The plan appends a stray print, so the pilot reports 10%. The reviewer finds the setup error, the pilot
    # is discarded and every seed runs with the corrected command.
    def bad(seed):
        return {**_run_spec(seed), "command": f"python3 train.py --seed {seed} && echo 'Test accuracy: 0.10'"}
    scripts = _multi_scripts(toy_case, [[("submit", {"claims": [_diag("reproduced", conclusion="matches")]})]])
    scripts[multi_agent.PLANNER[:30]] = [[("submit", {"rationale": "r", "runs": [bad(0), bad(1)]})]]
    scripts[multi_agent.REVIEWER[:30]] = [
        [("run_shell", {"command": "tail -n 2 ../logs/*exp_acc_s0.log"})],
        [("submit", {"assessment": "pilot 10% vs paper 85%: the command prints a stray metric line",
                     "setup_errors": ["stray echo after train.py (train.py prints the metric itself)"],
                     "rerun_claims": ["acc"], "revised_runs": [_run_spec(0), _run_spec(1)]})]]
    fake = FakeClient(scripts)
    use_fake(monkeypatch, fake)
    ctx = runner.new_run("toy", "multi")
    result = multi_agent.run(ctx)

    assert result.verdict == "full", (ctx.run_dir / "summary.json").read_text()
    metrics = Metrics.model_validate_json((ctx.run_dir / "metrics.json").read_text())
    assert sorted(metrics.claims[0].values) == pytest.approx([80.0, 81.0])  # the 10% pilot was discarded
    review = json.loads((ctx.run_dir / "review.json").read_text())
    assert review["rerun_claims"] == ["acc"] and review["setup_errors"]
    executed = [json.loads(l) for l in (ctx.run_dir / "trace.jsonl").read_text().splitlines()
                if '"agent": "executor"' in l and '"event": "run"' in l]
    assert [e["run_id"] for e in executed] == ["acc_s0", "acc_s0", "acc_s1"]  # pilot, repeated pilot, seed 1





def _scripts(toy_case, **overrides):
    s = {
        multi_agent.ANALYST[:30]: [[("submit", {**SPEC, "claims": [{"claim_id": "acc", "protocol": "p"}]})]],
        multi_agent.ENV[:30]: [[("run_shell", {"command": f"git clone -q {toy_case} repo"})], [("submit", ENV)]],
        multi_agent.PLANNER[:30]: [[("submit", {"rationale": "r", "runs": [_run_spec(0), _run_spec(1)]})]],
        multi_agent.REVIEWER[:30]: [[("submit", {"assessment": "setup faithful"})]],
        multi_agent.ANALYST_DISCREPANCY[:30]: [[("submit", {"claims": [_diag("reproduced", conclusion="matches")]})]],
    }
    s.update({getattr(multi_agent, k)[:30]: v for k, v in overrides.items()})
    return s


def _events(ctx) -> list[dict]:
    return [json.loads(l) for l in (ctx.run_dir / "trace.jsonl").read_text().splitlines()]


def test_missing_workdir_goes_to_the_debugger(toy_case, monkeypatch):
    # The planner points at a directory that does not exist (the measured failure: env report said repo/, the
    # repo was elsewhere). The run fails with a log; the debugger fixes the workdir.
    wrong = [{**_run_spec(s), "workdir": "nope"} for s in (0, 1)]
    fake = FakeClient(_scripts(
        toy_case,
        PLANNER=[[("submit", {"rationale": "r", "runs": wrong})]],
        DEBUGGER=[[("submit", {"diagnosis": "workdir nope does not exist; the clone is in repo/", "changes": [],
                               "revised_runs": [_run_spec(0), _run_spec(1)]})]]))
    use_fake(monkeypatch, fake)
    ctx = runner.new_run("toy", "multi")
    result = multi_agent.run(ctx)

    assert result.verdict == "full", (ctx.run_dir / "summary.json").read_text()
    first = next(e for e in _events(ctx) if e["agent"] == "executor" and e["event"] == "run")
    assert first["workdir"] == "nope" and first["exit_code"] == 2
    assert "workdir does not exist" in (ctx.run_dir / first["log_path"]).read_text()
    assert json.loads((ctx.run_dir / "summary.json").read_text())["error"] is None


def test_analyst_rerun_replaces_invalid_measurements_once(toy_case, monkeypatch):
    # The plan appends a stray metric line and the reviewer misses it, so both seeds report 10%. The analyst finds
    # the setup error and hands corrected runs back; they replace the claim's values. Its second report may not
    # ask again: a repeated request is ignored.
    def bad(seed):
        return {**_run_spec(seed), "command": f"python3 train.py --seed {seed} && echo 'Test accuracy: 0.10'"}
    rerun = {"claims": [_diag("discrepancy", "reproducer_error", "stray echo")],
             "setup_errors": ["the command echoes a fixed 'Test accuracy: 0.10' after train.py (plan.json)"],
             "rerun_claims": ["acc"], "revised_runs": [_run_spec(0), _run_spec(1)]}
    fake = FakeClient(_scripts(
        toy_case,
        PLANNER=[[("submit", {"rationale": "r", "runs": [bad(0), bad(1)]})]],
        ANALYST_DISCREPANCY=[[("submit", rerun)],
                             [("submit", {**rerun, "claims": [_diag("reproduced", conclusion="matches")]})]]))
    use_fake(monkeypatch, fake)
    ctx = runner.new_run("toy", "multi")
    result = multi_agent.run(ctx)

    assert result.verdict == "full", (ctx.run_dir / "summary.json").read_text()
    metrics = Metrics.model_validate_json((ctx.run_dir / "metrics.json").read_text())
    assert sorted(metrics.claims[0].values) == pytest.approx([80.0, 81.0])  # the 10% runs were replaced
    summary = json.loads((ctx.run_dir / "summary.json").read_text())
    assert summary["analyst_reruns"] == 1
    assert json.loads((ctx.run_dir / "analyst_rerun_1.json").read_text())["rerun_claims"] == ["acc"]
    assert not (ctx.run_dir / "analyst_rerun_2.json").exists()
    runs = [e["run_id"] for e in _events(ctx) if e["agent"] == "executor" and e["event"] == "run"]
    assert runs == ["acc_s0", "acc_s1", "acc_s0", "acc_s1"]
    starts = [e for e in _events(ctx) if e["agent"] == "discrepancy_analyst" and e["event"] == "start"]
    assert "still available" in starts[0]["task"] and "No rerun is available" in starts[1]["task"]
    report = json.loads((ctx.run_dir / "discrepancy_report.json").read_text())
    assert "revised_runs" not in report and report["claims"][0]["status"] == "reproduced"


class Interrupt(BaseException):
    """Stands in for a crash or Ctrl-C: not an Exception, so the graph's error handling does not catch it."""


def test_interrupted_run_resumes_from_its_checkpoint(toy_case, monkeypatch):
    fake = FakeClient(_scripts(toy_case))
    use_fake(monkeypatch, fake)
    ctx = runner.new_run("toy", "multi")
    real_reviewer = multi_agent.MultiAgentWorkflow.result_reviewer

    def crash(self, state):
        raise Interrupt()
    monkeypatch.setattr(multi_agent.MultiAgentWorkflow, "result_reviewer", crash)
    with pytest.raises(Interrupt):
        multi_agent.run(ctx)
    assert not (ctx.run_dir / "summary.json").exists()
    spent_before = ctx.budget.spent_usd

    monkeypatch.setattr(multi_agent.MultiAgentWorkflow, "result_reviewer", real_reviewer)
    ctx2 = runner.resume_run(ctx.run_dir)  # a fresh context, as after a restart
    assert ctx2.budget.spent_usd == 0 and not ctx2.sandbox.manifest
    result = multi_agent.run(ctx2, resume=True)

    assert result.verdict == "full", (ctx.run_dir / "summary.json").read_text()
    assert result.claims[0].evidence_ok  # the pilot's log, written before the crash, is still trusted
    runs = [e["run_id"] for e in _events(ctx) if e["agent"] == "executor" and e["event"] == "run"]
    assert runs == ["acc_s0", "acc_s1"]  # the pilot did not run again
    agents = [e["agent"] for e in _events(ctx) if e["event"] == "start" and e["agent"] != "runner"]
    assert agents.count("paper_analyst") == agents.count("env_agent") == agents.count("planner") == 1
    assert ctx2.budget.spent_usd > spent_before  # usage before the crash carried over, then grew
    assert any(e["event"] == "resume" for e in _events(ctx))


def test_resume_refuses_a_finished_run(toy_case, monkeypatch):
    use_fake(monkeypatch, FakeClient(_scripts(toy_case)))
    ctx = runner.new_run("toy", "multi")
    multi_agent.run(ctx)
    with pytest.raises(ValueError, match="already finished"):
        runner.resume_run(ctx.run_dir)
