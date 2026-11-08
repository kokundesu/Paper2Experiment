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


# A run that ran to the end but whose metric_regex matched nothing is re-read, not run again: a demo run once spent six
# more minutes of training because the value printed as tensor(-21.86) and the regex expected a bare number.
WRONG_REGEX = {**RUN, "metric_regex": r"AUC=([0-9.]+)"}  # main.py prints "AUC 0.957"


def test_a_run_whose_regex_missed_is_reparsed_not_rerun(tmp_path, monkeypatch):
    cid = make_spec_case(tmp_path, monkeypatch)
    fake = FakeClient({KEY: [
        [patch(add_tasks=[SETUP])],
        [("submit", SETUP_REPORT)],
        [patch(add_tasks=[WRONG_REGEX])],
        [patch(reparse=[{"task_id": "main", "metric_regex": r"AUC ([0-9.]+)"}])],
        [patch(finish={"answers": ans(q3=False), "not_measured": {"q3": "no run prints it"}})],
    ]})
    use_fake(monkeypatch, fake)
    ctx = corebench.new_run(cid, "planner")
    run_c(ctx)
    ev = events(ctx)
    failed = next(e for e in ev if e["event"] == "task/failed")
    assert failed["problems"] == ["no parsable metric value"]
    wake = [e for e in ev if e["agent"] == "planner" and e["event"] == "start"][3]["task"]
    assert "AUC 0.957" in wake  # the tail the Planner fixes the regex from
    done = next(e for e in ev if e["event"] == "task/done" and e.get("task_id") == "main")
    assert done["value"] == 0.957 and done["reparsed_from"]["metric_regex"] == "AUC=([0-9.]+)"
    assert len(list(ctx.sandbox.log_dir.glob("cmd_*_exp_main.log"))) == 1  # the experiment ran once


def _runtime_after_a_run(tmp_path, monkeypatch, task):
    from p2e.runtime import ExperimentPatch, Runtime
    cid = make_spec_case(tmp_path, monkeypatch)
    use_fake(monkeypatch, FakeClient({}))
    ctx = corebench.new_run(cid, "planner")
    rt = Runtime(ctx)
    assert rt.apply(ExperimentPatch(reasoning="r", add_tasks=[{**task, "depends_on": []}])) == []
    rt.step(lambda t, r: (True, {}, ""))
    return rt, ExperimentPatch


def test_reparse_refuses_a_run_that_did_not_exit_cleanly(tmp_path, monkeypatch):
    rt, Patch = _runtime_after_a_run(tmp_path, monkeypatch, {**WRONG_REGEX, "command": "python3 code/main.py; exit 3"})
    assert rt.tasks["main"]["problems"] == ["exit code 3", "no parsable metric value"]
    problems = rt.apply(Patch(reasoning="r", reparse=[{"task_id": "main", "metric_regex": r"AUC ([0-9.]+)"}]))
    assert problems and "replace it instead" in problems[0] and rt.tasks["main"]["status"] == "failed"


def test_reparse_refuses_a_log_changed_after_the_run_and_a_regex_that_still_misses(tmp_path, monkeypatch):
    rt, Patch = _runtime_after_a_run(tmp_path, monkeypatch, WRONG_REGEX)
    still_wrong = rt.apply(Patch(reasoning="r", reparse=[{"task_id": "main", "metric_regex": r"ROC ([0-9.]+)"}]))
    assert "also finds no value" in still_wrong[0]
    log = rt.ctx.run_dir / rt.tasks["main"]["log"]
    log.write_text(log.read_text() + "AUC 0.999\n")  # an agent appending the number it wants
    tampered = rt.apply(Patch(reasoning="r", reparse=[{"task_id": "main", "metric_regex": r"AUC ([0-9.]+)"}]))
    assert "not the one the sandbox wrote" in tampered[0] and rt.tasks["main"]["status"] == "failed"


def test_tasks_blocked_on_the_failed_run_go_again_after_its_reparse(tmp_path, monkeypatch):
    rt, Patch = _runtime_after_a_run(tmp_path, monkeypatch, WRONG_REGEX)
    after = {**RUN, "task_id": "after", "depends_on": ["main"]}
    assert rt.apply(Patch(reasoning="r", add_tasks=[after])) == []
    rt.ready()  # its dependency failed: blocked
    assert rt.tasks["after"]["status"] == "blocked"
    assert rt.apply(Patch(reasoning="r", reparse=[{"task_id": "main", "metric_regex": r"AUC ([0-9.]+)"}])) == []
    assert rt.tasks["main"]["status"] == "done" and rt.ready() == ["after"]
