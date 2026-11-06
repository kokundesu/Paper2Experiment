"""The shared Planner + runtime on a spec run: the finish proposal carries the answers and, with gates on, the runtime refuses
answers that did not come from this run's output. Offline with a scripted model."""
import json

from p2e import corebench
from p2e.testing import FakeClient, make_spec_case, use_fake
from p2e.versions import load

planner = load("PlannerWorkers")


def run_c(ctx, resume=False):
    """The shared Planner + runtime with agent tasks in the Planner's own context (the round-1 C setting)."""
    return planner.PlannerRuntimeWorkflow(ctx, gates=True, workers=False).run(resume=resume)
KEY = planner.PLANNER_SPEC[:30]
SETUP = {"kind": "agent", "task_id": "setup", "role": "setup", "objective": "make main.py runnable",
         "done_criteria": "main.py starts", "effort_turns": 5}
SETUP_REPORT = {"repo_dir": ".", "python": "python3", "entrypoint": "code/main.py", "smoke_test": "ok", "ok": True}
RUN = {"kind": "run", "task_id": "main", "command": "python3 code/main.py", "workdir": ".", "depends_on": ["setup"]}


def patch(**kw):
    return ("submit", {"reasoning": "r", **kw})


def ans(q3=True):
    out = [{"question_id": "q1", "value": "CatBoost", "evidence": ["logs/cmd_001_exp_main.log"]},
           {"question_id": "q2", "value": 0.957, "evidence": ["logs/cmd_001_exp_main.log"]}]
    return out + ([{"question_id": "q3", "value": 0.9506, "evidence": ["data/old_results.txt"]}] if q3 else [])


def events(ctx):
    return [json.loads(l) for l in (ctx.run_dir / "trace.jsonl").read_text().splitlines()]


def test_finish_gate_refuses_a_shortcut_answer(tmp_path, monkeypatch):
    cid = make_spec_case(tmp_path, monkeypatch)
    fake = FakeClient({KEY: [
        [patch(add_tasks=[SETUP])],
        [("submit", SETUP_REPORT)],
        [patch(add_tasks=[RUN])],
        [patch(finish={"answers": ans()})],  # refused: q3 only appears in a shipped file
        [patch(finish={"answers": ans(q3=False), "not_measured": {"q3": "no run prints it"}})],
    ]})
    use_fake(monkeypatch, fake)
    ctx = corebench.new_run(cid, "planner")
    result = run_c(ctx)
    ev = events(ctx)
    rejected = next(e for e in ev if e["event"] == "finish/rejected")
    assert any("q3" in p and "before the run started" in p for p in rejected["problems"])
    wake = [e for e in ev if e["agent"] == "planner" and e["event"] == "start"][3]["task"]
    assert "output_tail" in wake and "AUC 0.957" in wake  # the Planner sees what the run printed
    summary = json.loads((ctx.run_dir / "summary.json").read_text())
    assert summary["finish_accepted"] and result.verdict == "partial" and not result.shortcut
    assert not any(e["agent"] == "planner" and "DiscrepancyReport" in str(e.get("output_schema")) for e in ev)


def test_without_gates_the_shortcut_goes_through_and_is_caught_by_the_evaluator(tmp_path, monkeypatch):
    cid = make_spec_case(tmp_path, monkeypatch)
    fake = FakeClient({KEY: [
        [patch(add_tasks=[SETUP])],
        [("submit", SETUP_REPORT)],
        [patch(add_tasks=[RUN])],
        [patch(finish={"answers": ans()})],
    ]})
    use_fake(monkeypatch, fake)
    ctx = corebench.new_run(cid, "planner_nogates")
    result = planner.PlannerRuntimeWorkflow(ctx, gates=False, workers=False).run()
    assert result.verdict == "partial" and result.full_tolerance_only and result.shortcut == ["Old accuracy?"]


def test_read_log_tool_reads_only_logs(tmp_path, monkeypatch):
    cid = make_spec_case(tmp_path, monkeypatch)
    use_fake(monkeypatch, FakeClient({}))
    ctx = corebench.new_run(cid, "planner")
    wf = planner.PlannerRuntimeWorkflow(ctx)
    ctx.sandbox.run("python3 code/main.py", tag="exp_main")
    tool = next(t for t in wf._read_tools() if t.name == "read_log")
    assert "AUC 0.957" in tool.fn({"name": "logs/cmd_001_exp_main.log"})
    assert tool.fn({"name": "../trace.jsonl"}).startswith("no such log")
