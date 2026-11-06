"""The shared agent loop (p2e.llm.Agent) and the CLI, without the API: a scripted fake model stands in."""
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


def _agent(tmp_path, client, budget=None, **kw):
    sb = Sandbox(tmp_path / "run")
    return Agent("t", "TEST", sandbox_tools(sb), PaperSpec, Trace(tmp_path / "trace.jsonl"),
                 budget or Budget(profile=get_profile("luna")), chat=client, **kw)


def test_agent_uses_tools_retries_bad_submit_and_tracks_usage(tmp_path):
    client = FakeClient({"TEST": [
        [("run_shell", {"command": "echo hi > f.txt"})],
        [("read_file", {"path": "f.txt"}), ("submit", {"summary": "missing fields"})],
        [("submit", SPEC)],
    ]})
    agent = _agent(tmp_path, client)
    out = agent.run("go")
    assert out.summary == "s"
    assert agent.usage.requests == 3 and agent.budget.usage.requests == 3
    assert agent.budget.spent_usd == pytest.approx(3 * (1000 * 0.10 + 200 * 0.50) / 1e6)
    events = [json.loads(l)["event"] for l in (tmp_path / "trace.jsonl").read_text().splitlines()]
    assert events.count("tool_result") == 4 and events[-2:] == ["submit", "end"]


def test_shared_budget_stops_agent(tmp_path):
    # each request: 200k input (below the 272k long-context line) -> 200k*0.10/1e6 = $0.02;
    # budget $0.07 minus the Luna reserve ((150k+8k)*0.10 + 16k*0.50)/1e6 = $0.024 allows three requests
    client = FakeClient({"TEST": [[("list_dir", {})]] * 10}, tokens=(200_000, 0, 0))
    agent = _agent(tmp_path, client, budget=Budget(profile=get_profile("luna"), limit_usd=0.07))
    with pytest.raises(BudgetExceeded, match="run budget"):
        agent.run("go")
    assert client.n == 3


def test_cost_counts_cache_and_long_context():
    luna = get_profile("luna")
    e = Entry(kind="message", prompt=300_000, cached=100_000, written=50_000, output=1000, reasoning=800)
    # above 272k input: 2x input/cache rates, 1.5x output
    expected = (2 * (150_000 * 0.10 + 100_000 * 0.01 + 50_000 * 0.125) + 1.5 * 1000 * 0.50) / 1e6
    assert luna.cost(e) == pytest.approx(expected)
    haiku = get_profile("haiku55")
    small = Entry(kind="message", prompt=100_000, cached=0, written=0, output=1000)
    big = Entry(kind="message", prompt=100_001, cached=0, written=0, output=1000)
    assert haiku.cost(small) == pytest.approx((100_000 * 0.10 + 1000 * 0.50) / 1e6)
    assert haiku.cost(big) == pytest.approx(5 * (100_001 * 0.10 + 1000 * 0.50) / 1e6)


def test_bad_json_arguments_go_back_to_the_model(tmp_path):
    client = FakeClient({"TEST": [[("submit", "{not json")], [("submit", SPEC)]]})
    out = _agent(tmp_path, client).run("go")
    assert out.summary == "s" and client.n == 2
    results = [json.loads(l) for l in (tmp_path / "trace.jsonl").read_text().splitlines()]
    assert any(r["event"] == "tool_result" and r["is_error"] and "not valid JSON" in r["output"] for r in results)


@pytest.mark.parametrize("keep", [False, True])
def test_run_deletes_workspace_after_scoring_unless_kept(toy_case, monkeypatch, keep):
    monkeypatch.setenv("OPENAI_API_KEY", "test")  # importing cli reads .env; this keeps the real key out
    from p2e import cli

    def workflow(ctx):
        (ctx.sandbox.workspace / "repo" / ".venv").mkdir(parents=True)
        (ctx.sandbox.workspace / "repo" / ".venv" / "big.so").write_text("x")
        ctx.sandbox.run("echo 'Test accuracy: 0.8050'")
        return runner.finish(ctx, Metrics(claims=[]), time.monotonic())

    monkeypatch.setattr(cli, "BENCHMARK", runner.BENCHMARK)
    monkeypatch.setattr(cli, "RUNS", runner.RUNS)
    monkeypatch.setitem(cli.WORKFLOWS, "deterministic", workflow)
    assert cli.main(["run", "--case", "toy", "--workflow", "deterministic"] + (["--keep-workspace"] * keep)) == 0
    (run_dir,) = runner.RUNS.iterdir()
    assert (run_dir / "workspace").exists() == keep
    assert any(Path(os.environ["P2E_WORKSPACE_ROOT"]).glob("*/workspace")) == keep  # the real tree, outside the project
    assert (run_dir / "summary.json").exists() and list((run_dir / "logs").glob("cmd_*.log"))


# ---- model-visible is recorded, conversations, tool pipeline hooks

def _spy(monkeypatch):
    """Capture every request the fake model receives, as (role, content, tool calls)."""
    sent = []
    orig = FakeClient._generate

    def spy(self, messages, *a, **kw):
        sent.append([(m.type, m.content, [c["name"] for c in getattr(m, "tool_calls", []) or []]) for m in messages])
        return orig(self, messages, *a, **kw)
    monkeypatch.setattr(FakeClient, "_generate", spy)
    return sent


def _replayed(tmp_path, agent="t"):
    events = [json.loads(l) for l in (tmp_path / "trace.jsonl").read_text().splitlines()]
    return [(m["role"], m["content"], [c["name"] for c in m.get("tool_calls", [])])
            for m in llm.replay_messages(events, agent)]


def test_every_request_is_rebuilt_from_the_trace(tmp_path, monkeypatch):
    sent = _spy(monkeypatch)
    client = FakeClient({"TEST": [[], [("submit", "{bad json")], [("list_dir", {}), ("read_file", {"path": "nope"})],
                                  [("submit", SPEC)]]})
    _agent(tmp_path, client).run("go")
    # the last request carried the nudge, the invalid-JSON reply, both tool results and every model turn before it
    assert _replayed(tmp_path)[:-1] == sent[-1] and len(sent) == 4


def test_converse_continues_the_same_conversation_and_the_trace_follows(tmp_path, monkeypatch):
    sent = _spy(monkeypatch)
    client = FakeClient({"TEST": [[("submit", SPEC)], [("list_dir", {})], [("submit", SPEC)]]})
    agent = _agent(tmp_path, client)
    _, history = agent.converse([], "first")
    out, history2 = agent.converse(history, "second")
    assert out.summary == "s" and len(history2) > len(history)
    assert sent[-1][1][1] == "first" and _replayed(tmp_path)[:-1] == sent[-1]  # one context, rebuilt from the trace
    with pytest.raises(ValueError, match="history must be"):
        agent.converse(history, "stale history")  # not the conversation the previous call returned


def test_tool_hooks_deny_and_rewrite(tmp_path):
    client = FakeClient({"TEST": [[("run_shell", {"command": "echo hi"}), ("list_dir", {})], [("submit", SPEC)]]})
    agent = _agent(tmp_path, client,
                   pre_tool=[lambda name, args: "read-only role" if name == "run_shell" else None],
                   post_tool=[lambda name, args, out, err: (out + "\n[checked]", err)])
    agent.run("go")
    events = [json.loads(l) for l in (tmp_path / "trace.jsonl").read_text().splitlines()]
    results = {e["tool"]: e for e in events if e["event"] == "tool_result"}
    assert results["run_shell"]["is_error"] and "read-only role" in results["run_shell"]["output"]
    assert results["list_dir"]["output"].endswith("[checked]") and not results["list_dir"]["is_error"]
    assert results["submit"]["output"] == "accepted"  # hooks never touch the submission
    assert any(e["event"] == "tool_denied" for e in events)
