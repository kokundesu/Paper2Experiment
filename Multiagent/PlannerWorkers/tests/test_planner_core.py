"""Shared Planner + runtime (the round-1 C setting: gates on, agent tasks in the Planner's own context), offline.

A fake model replays the Planner's turns. Everything else is real: the runtime and its gates, the sandbox, the
checkpoint and the evaluator. The toy repository's train.py prints per-epoch losses unless --quiet."""
import json

import pytest

from p2e import runner
from p2e.schemas import Metrics
from p2e.testing import FakeClient, use_fake
from p2e.versions import load

planner = load("PlannerWorkers")


def run_c(ctx, resume=False):
    """The shared Planner + runtime with agent tasks in the Planner's own context (the round-1 C setting)."""
    return planner.PlannerRuntimeWorkflow(ctx, gates=True, workers=False).run(resume=resume)

TRAIN = """import sys
seed = int(sys.argv[sys.argv.index('--seed') + 1])
if '--quiet' not in sys.argv:
    for e in range(3):
        print(f'epoch {e} loss {1 / (e + 1):.3f}')
print(f'Test accuracy: {0.80 + 0.01 * seed:.4f}')
"""
KEY = planner.PLANNER[:30]


def run_task(seed, tid=None, extra="", **kw):
    return {"kind": "run", "task_id": tid or f"acc_s{seed}", "claim_id": "acc", "seed": seed, "workdir": "repo",
            "command": f"python3 train.py --seed {seed} {extra}".strip(),
            "smoke_command": f"python3 train.py --seed {seed} --epochs 1 {extra}".strip(),
            "metric_regex": r"Test accuracy: ([0-9.]+)", "scale": 100, "depends_on": ["setup"], **kw}


SETUP_TASK = {"kind": "agent", "task_id": "setup", "role": "setup", "objective": "clone and make it runnable",
              "done_criteria": "train.py runs and prints progress", "effort_turns": 10}
SETUP_REPORT = {"repo_dir": "repo", "python": "python3", "entrypoint": "repo/train.py", "smoke_test": "ran 1 epoch",
                "ok": True}
LEDGER = {"given_or_verified": ["claim acc: test accuracy"], "assumptions": [
    {"setting": "epochs", "value": "3", "basis": "train.py default; paper does not say"}], "plan": "setup, then 2 seeds"}


def patch(reasoning="r", **kw):
    return ("submit", {"reasoning": reasoning, **kw})


def setup_turns(toy_case):
    """The Planner's own turns while it executes the setup task in its context (version C)."""
    return [[("run_shell", {"command": f"git clone -q {toy_case} repo"}),
             ("write_file", {"path": "repo/train.py", "content": TRAIN})],
            [("submit", SETUP_REPORT)]]


def report(status="reproduced", conclusion="matches"):
    return ("submit", {"claims": [{"claim_id": "acc", "status": status, "conclusion": conclusion,
                                   "confidence": "medium"}]})


def events(ctx) -> list[dict]:
    return [json.loads(l) for l in (ctx.run_dir / "trace.jsonl").read_text().splitlines()]


def test_planner_runs_setup_then_runs_then_finishes(toy_case, monkeypatch):
    fake = FakeClient({KEY: [
        [patch(ledger=LEDGER, add_tasks=[SETUP_TASK])],
        *setup_turns(toy_case),
        [patch(add_tasks=[run_task(0), run_task(1)])],
        [patch(finish={"summary": "both seeds measured"})],
        [report()],
    ]})
    use_fake(monkeypatch, fake)
    ctx = runner.new_run("toy", "planner")
    result = run_c(ctx)

    assert result.verdict == "full", (ctx.run_dir / "summary.json").read_text()
    metrics = Metrics.model_validate_json((ctx.run_dir / "metrics.json").read_text())
    assert sorted(metrics.claims[0].values) == pytest.approx([80.0, 81.0])
    assert "epochs" in metrics.notes  # the ledger's assumptions travel with the result
    summary = json.loads((ctx.run_dir / "summary.json").read_text())
    assert summary["finish_accepted"] and summary["gates"] and not summary["workers"]
    assert summary["tasks"] == {"done": 3}
    logs = sorted(p.name for p in (ctx.run_dir / "logs").glob("*.log"))
    assert sum("smoke_" in n for n in logs) == 2 and sum("exp_" in n for n in logs) == 2
    # one context: the setup work happened inside the Planner's conversation
    starts = [e for e in events(ctx) if e["event"] == "start" and e["agent"] == "planner"]
    assert [s["output_schema"] for s in starts] == ["ExperimentPatch", "SetupReport", "ExperimentPatch",
                                                    "ExperimentPatch", "DiscrepancyReport"]
    assert [s["history_len"] > 0 for s in starts] == [False, True, True, True, True]


def test_gates_send_a_quiet_command_back_before_the_full_run(toy_case, monkeypatch):
    quiet = [run_task(0, extra="--quiet"), run_task(1, extra="--quiet")]
    fixed = [run_task(0, tid="acc_s0_v"), run_task(1, tid="acc_s1_v")]
    fake = FakeClient({KEY: [
        [patch(add_tasks=[SETUP_TASK])],
        *setup_turns(toy_case),
        [patch(add_tasks=quiet)],
        # the smoke run of acc_s0 fails (no progress), acc_s1 is still waiting: the Planner replaces both
        [patch("progress is printed only without --quiet", add_tasks=fixed, replace=[
            {"old_task_id": "acc_s0", "new_task_id": "acc_s0_v"}, {"old_task_id": "acc_s1", "new_task_id": "acc_s1_v"}])],
        [patch(finish={})],
        [report()],
    ]})
    use_fake(monkeypatch, fake)
    ctx = runner.new_run("toy", "planner")
    result = run_c(ctx)

    assert result.verdict == "full"
    ev = events(ctx)
    failed = next(e for e in ev if e["agent"] == "runtime" and e["event"] == "task/failed")
    assert failed["task_id"] == "acc_s0" and failed["stage"] == "smoke"
    assert not any("exp_acc_s0." in p.name for p in (ctx.run_dir / "logs").glob("*.log"))  # never ran in full
    wake = [e for e in ev if e["agent"] == "planner" and e["event"] == "start"][3]["task"]
    assert "no training progress" in wake and "acc_s0" in wake  # the Planner was told why


def test_runtime_refuses_bad_patches_and_early_finish(toy_case, monkeypatch):
    fake = FakeClient({KEY: [
        [patch(add_tasks=[SETUP_TASK])],
        *setup_turns(toy_case),
        [patch(finish={"summary": "done already?"})],  # refused: no counted values
        [patch(add_tasks=[run_task(0, extra="| tail -n 3")])],  # refused: filters its output
        [patch(add_tasks=[run_task(0), run_task(1)])],
        [patch(finish={})],
        [report()],
    ]})
    use_fake(monkeypatch, fake)
    ctx = runner.new_run("toy", "planner")
    assert run_c(ctx).verdict == "full"
    ev = events(ctx)
    assert any(e["event"] == "finish/rejected" and "0/2 counted values" in str(e["problems"]) for e in ev)
    assert any(e["event"] == "patch/rejected" and "filter" in str(e["problems"]) for e in ev)
    msgs = [e["task"] for e in ev if e["agent"] == "planner" and e["event"] == "start"]
    assert any("refused to finish" in m for m in msgs) and any("refused the patch" in m for m in msgs)


def test_stalls_reset_the_conversation_and_the_run_can_end_not_measured(toy_case, monkeypatch):
    def failing(i):
        return run_task(0, tid=f"try{i}", extra="--seed-typo").copy() | {
            "command": "python3 train.py", "smoke_command": "python3 train.py"}  # no --seed: crashes every time
    fake = FakeClient({KEY: [
        [patch(add_tasks=[SETUP_TASK])],
        *setup_turns(toy_case),
        [patch(add_tasks=[failing(0)])],
        [patch(add_tasks=[failing(1)])],
        [patch(add_tasks=[failing(2)])],
        # third failure with the same signature -> re-plan: a fresh conversation seeded with ledger and tasks
        [patch("root cause: the script needs --seed; give up after three identical crashes",
               finish={"not_measured": {"acc": "every attempt crashed the same way"}})],
        [report("not_measured", "")],
    ]})
    use_fake(monkeypatch, fake)
    ctx = runner.new_run("toy", "planner")
    result = run_c(ctx)

    assert result.verdict == "fail" and json.loads((ctx.run_dir / "summary.json").read_text())["replans"] == 1
    starts = [e for e in events(ctx) if e["agent"] == "planner" and e["event"] == "start"]
    replan = next(s for s in starts if "stalled" in s["task"])
    assert replan["history_len"] == 0 and "Task ledger" in replan["task"] and "try2" in replan["task"]


class Interrupt(BaseException):
    pass


def test_resume_after_an_interrupt(toy_case, monkeypatch):
    fake = FakeClient({KEY: [
        [patch(add_tasks=[SETUP_TASK])],
        *setup_turns(toy_case),
        [patch(add_tasks=[run_task(0), run_task(1)])],
        [patch(finish={})],
        [report()],
    ]})
    use_fake(monkeypatch, fake)
    ctx = runner.new_run("toy", "planner")
    real = planner.PlannerRuntimeWorkflow.diagnose

    def crash(self, state):
        raise Interrupt()
    monkeypatch.setattr(planner.PlannerRuntimeWorkflow, "diagnose", crash)
    with pytest.raises(Interrupt):
        run_c(ctx)
    monkeypatch.setattr(planner.PlannerRuntimeWorkflow, "diagnose", real)
    ctx2 = runner.resume_run(ctx.run_dir)
    result = run_c(ctx2, resume=True)

    assert result.verdict == "full" and result.claims[0].evidence_ok  # logs from before the crash still trusted
    runs = [e["task_id"] for e in events(ctx) if e["event"] == "task/done" and e["task_id"].startswith("acc")]
    assert runs == ["acc_s0", "acc_s1"]  # nothing ran twice
