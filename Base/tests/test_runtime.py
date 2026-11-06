"""The Planner + Runtime substrate (p2e.runtime), without any LLM: patches, the three verification stages, wakes and
stalls, the finish gate, agent-task dispatch and state round trips."""
import threading
import time

import pytest

from p2e import runner
from p2e.runtime import (MAX_PARALLEL_DIAGNOSE, MAX_REPLACEMENTS, STALL_LIMIT, AgentTask, ExperimentPatch,
                         FinishProposal, Replacement, RunTask, Runtime, filtering_problems)

# prints per-epoch losses unless --quiet, then the metric; --fail exits with an error
TRAIN = """import sys
seed = int(sys.argv[sys.argv.index('--seed') + 1])
if '--fail' in sys.argv:
    raise SystemExit('RuntimeError: CUDA not available')
if '--quiet' not in sys.argv:
    for e in range(3):
        print(f'epoch {e} loss {1 / (e + 1):.3f}')
print(f'Test accuracy: {0.80 + 0.01 * seed:.4f}')
"""


@pytest.fixture
def rt(toy_case):
    ctx = runner.new_run("toy", "planner")
    ctx.sandbox.run(f"git clone -q {toy_case} repo")
    (ctx.sandbox.workspace / "repo" / "train.py").write_text(TRAIN)
    return Runtime(ctx)


def run(seed, tid=None, extra="", smoke_extra="", **kw):
    return RunTask(task_id=tid or f"acc_s{seed}", claim_id="acc", seed=seed, workdir="repo",
                   command=f"python3 train.py --seed {seed} {extra}".strip(),
                   smoke_command=f"python3 train.py --seed {seed} {smoke_extra}".strip(),
                   metric_regex=r"Test accuracy: ([0-9.]+)", scale=100, **kw)


def no_agent(task, runtime):
    raise AssertionError("no agent task expected")


def drain(rt, run_agent=no_agent):
    while rt.step(run_agent):
        pass


def test_plan_check_rejects_the_whole_patch(rt):
    bad = ExperimentPatch(reasoning="r", add_tasks=[
        run(0, extra="| grep accuracy"),
        run(1, tid="nosmoke").model_copy(update={"smoke_command": None}),
        run(2, tid="badre").model_copy(update={"metric_regex": "Test accuracy"}),
        run(3, tid="other_claim").model_copy(update={"claim_id": "nope"}),
        run(4, tid="needs_x", depends_on=["x"]),
        run(5, tid="elsewhere").model_copy(update={"workdir": "missing"}),
    ])
    problems = rt.apply(bad)
    text = "\n".join(problems)
    for expected in ("pipes its output into a filter", "smoke_command is required", "exactly one capture group",
                     "unknown claim 'nope'", "unknown task 'x'", "workdir 'missing' does not exist"):
        assert expected in text, expected
    assert rt.tasks == {}  # atomic: nothing was added


def test_one_counted_variant_per_claim(rt):
    p = ExperimentPatch(reasoning="r", add_tasks=[run(0), run(1, tid="paper_s1", variant="paper_text")])
    assert any("only one variant may count" in x for x in rt.apply(p))
    p = ExperimentPatch(reasoning="r", add_tasks=[run(0), run(1, tid="paper_s1", variant="paper_text", counts=False)])
    assert rt.apply(p) == []


def test_smoke_then_full_run_then_finish(rt):
    assert rt.apply(ExperimentPatch(reasoning="r", add_tasks=[run(0, smoke_extra="--epochs 1"), run(1)])) == []
    drain(rt)
    assert [rt.tasks[t]["status"] for t in ("acc_s0", "acc_s1")] == ["done", "done"]
    assert rt.tasks["acc_s0"]["value"] == pytest.approx(80.0) and rt.tasks["acc_s1"]["value"] == pytest.approx(81.0)
    logs = sorted(p.name for p in (rt.ctx.run_dir / "logs").glob("*.log"))
    assert sum("smoke_" in n for n in logs) == 2 and sum("exp_" in n for n in logs) == 2  # one smoke per command
    assert rt.check_finish(FinishProposal()) == [] and rt.state["finished"] is not None
    m = rt.metrics()
    assert m.claims[0].values == pytest.approx([80.0, 81.0]) and all(e.startswith("logs/") for e in m.claims[0].evidence)


def test_smoke_gate_catches_a_quiet_command_before_the_full_run(rt):
    # the planner forgot the progress output (the HNN --verbose failure): caught by the smoke run, full run never starts
    assert rt.apply(ExperimentPatch(reasoning="r", add_tasks=[run(0, extra="--quiet", smoke_extra="--quiet")])) == []
    drain(rt)
    t = rt.tasks["acc_s0"]
    assert t["status"] == "failed" and t["stage"] == "smoke"
    assert any("no training progress" in p for p in t["problems"])
    assert not list((rt.ctx.run_dir / "logs").glob("*exp_*"))


def test_evidence_gate_rejects_a_value_without_training_trace(rt):
    assert rt.apply(ExperimentPatch(reasoning="r", add_tasks=[run(0, extra="--quiet")])) == []
    drain(rt)
    t = rt.tasks["acc_s0"]
    assert t["status"] == "failed" and t["stage"] == "evidence" and "value" not in t
    assert rt.counted_values()["acc"] == []


def test_without_gates_any_parsed_value_counts(toy_case):
    ctx = runner.new_run("toy", "planner_nogates")
    ctx.sandbox.run(f"git clone -q {toy_case} repo")
    (ctx.sandbox.workspace / "repo" / "train.py").write_text(TRAIN)
    rt = Runtime(ctx, gates=False)
    quiet = run(0, extra="--quiet | tail -n 1").model_copy(update={"smoke_command": None})
    assert rt.apply(ExperimentPatch(reasoning="r", add_tasks=[quiet])) == []  # no plan check either
    drain(rt)
    assert rt.tasks["acc_s0"]["status"] == "done" and not list((ctx.run_dir / "logs").glob("*smoke_*"))


def test_replacing_a_failed_task_rewires_its_dependants_and_caps_attempts(rt):
    p = ExperimentPatch(reasoning="r", add_tasks=[run(0, extra="--fail"), run(1, depends_on=["acc_s0"])])
    assert rt.apply(p) == []
    drain(rt)
    assert rt.tasks["acc_s0"]["status"] == "failed" and rt.tasks["acc_s1"]["status"] == "blocked"
    assert "RuntimeError" in rt.tasks["acc_s0"]["signature"]
    fix = ExperimentPatch(reasoning="drop --fail", add_tasks=[run(0, tid="acc_s0_b")],
                          replace=[Replacement(old_task_id="acc_s0", new_task_id="acc_s0_b")])
    assert rt.apply(fix) == []
    assert rt.tasks["acc_s0_b"]["attempt"] == 2 and rt.tasks["acc_s0_b"]["lineage"] == "acc_s0"
    assert rt.tasks["acc_s1"]["spec"]["depends_on"] == ["acc_s0_b"] and rt.tasks["acc_s1"]["status"] == "pending"
    drain(rt)
    assert rt.claim_status()["acc"]["satisfied"]
    rt.tasks["acc_s0_b"].update(status="failed", attempt=MAX_REPLACEMENTS)  # pretend the lineage kept failing
    again = ExperimentPatch(reasoning="r", add_tasks=[run(0, tid="acc_s0_c", counts=False)],
                            replace=[Replacement(old_task_id="acc_s0_b", new_task_id="acc_s0_c")])
    assert any(f"reached {MAX_REPLACEMENTS} attempts" in x for x in rt.apply(again))


def test_replacing_or_cancelling_a_task_that_was_never_added_is_rejected_not_raised(rt):
    # cb-3418007 (test split, D): the Planner replaced and cancelled a setup task it had only described
    p = ExperimentPatch(reasoning="r", add_tasks=[run(0, tid="acc_s0_b")], cancel_task_ids=["setup_env"],
                        replace=[Replacement(old_task_id="setup_env", new_task_id="acc_s0_b")])
    text = "\n".join(rt.apply(p))
    assert "replace: unknown task 'setup_env'" in text and "cancel: unknown task 'setup_env'" in text
    assert rt.tasks == {}


def test_wake_tracks_progress_loops_and_replans(rt):
    assert rt.apply(ExperimentPatch(reasoning="r", add_tasks=[run(0)])) == []
    drain(rt)
    w = rt.wake()
    assert w["is_progress_being_made"] and not w["replan"] and [c["task_id"] for c in w["changed"]] == ["acc_s0"]
    w = rt.wake()
    assert w["changed"] == [] and rt.state["stalls"] == 1  # only deltas; a wake with nothing new is a stall
    wakes = []
    for i in range(STALL_LIMIT):  # the same failure again and again
        assert rt.apply(ExperimentPatch(reasoning="r", add_tasks=[run(1, tid=f"f{i}", extra="--fail")])) == []
        drain(rt)
        wakes.append(rt.wake())
    assert [w["replan"] for w in wakes] == [False, True, False]  # stalls 2, 3 -> re-plan and reset, then 1
    assert wakes[-1]["is_in_loop"] and rt.state["replans"] == 1 and rt.state["stalls"] == 1


def test_finish_gate(rt):
    assert any("0/2 counted values" in p for p in rt.check_finish(FinishProposal()))
    assert any("no run of it was attempted" in p
               for p in rt.check_finish(FinishProposal(not_measured={"acc": "code does not run on CPU"})))
    assert rt.apply(ExperimentPatch(reasoning="r", add_tasks=[run(0, extra="--fail")])) == []
    assert any("tasks still pending" in p for p in rt.check_finish(FinishProposal(not_measured={"acc": "x"})))
    drain(rt)
    assert rt.check_finish(FinishProposal(not_measured={"acc": "fails on CPU: CUDA required"})) == []


def test_agent_tasks_and_parallel_diagnosis(rt):
    seen, active, peak = [], [0], [0]
    lock = threading.Lock()

    def run_agent(task, runtime):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        seen.append(task.task_id)
        if task.task_id == "boom":
            raise ValueError("worker crashed")
        return True, {"note": task.objective}, f"{task.role} done"

    tasks = [AgentTask(task_id="setup", role="setup", objective="clone and install")]
    tasks += [AgentTask(task_id=f"diag{i}", role="diagnose", objective=f"d{i}", claim_id="acc", depends_on=["setup"])
              for i in range(MAX_PARALLEL_DIAGNOSE + 1)]
    tasks.append(AgentTask(task_id="boom", role="debug", objective="x", depends_on=["setup"]))
    assert rt.apply(ExperimentPatch(reasoning="r", add_tasks=tasks)) == []
    assert rt.step(run_agent) == ["setup"] and rt.should_wake(["setup"])  # a finished agent task wakes the planner
    assert len(rt.step(run_agent)) == MAX_PARALLEL_DIAGNOSE and peak[0] == MAX_PARALLEL_DIAGNOSE
    drain(rt, run_agent)
    assert rt.tasks["setup"]["artifact"] == {"note": "clone and install"}
    assert rt.tasks["boom"]["status"] == "failed" and "worker crashed" in rt.tasks["boom"]["summary"]


def test_state_round_trip(rt):
    assert rt.apply(ExperimentPatch(reasoning="r", add_tasks=[run(0), run(1)])) == []
    rt.step(no_agent)
    again = Runtime(rt.ctx, state=rt.state)  # e.g. rebuilt from a LangGraph checkpoint
    drain(again)
    assert again.claim_status()["acc"]["satisfied"]


def test_filter_detection():
    assert filtering_problems("python t.py --seed 0 2>&1") == []
    assert filtering_problems("cd repo && python main.py --verbose") == []
    assert filtering_problems("python t.py | tail -n 5") and filtering_problems("python t.py > out.txt")
    assert filtering_problems("python t.py 2>/dev/null") and filtering_problems("python t.py &> log")
