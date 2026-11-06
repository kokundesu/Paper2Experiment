"""Version D (version C + worker sub-agents), offline: setup and diagnosis run in workers with their own context."""
import json

import pytest

from p2e import runner
from p2e.testing import FakeClient, use_fake
from p2e.versions import load

c = load("PlannerWorkers")
workers = load("PlannerWorkers")
TRAIN = """import sys
seed = int(sys.argv[sys.argv.index('--seed') + 1])
for e in range(3):
    print(f'epoch {e} loss {1 / (e + 1):.3f}')
print(f'Test accuracy: {0.80 + 0.01 * seed:.4f}')
"""


def run_task(seed):
    return {"kind": "run", "task_id": f"acc_s{seed}", "claim_id": "acc", "seed": seed, "workdir": "repo",
            "command": f"python3 train.py --seed {seed}", "smoke_command": f"python3 train.py --seed {seed}",
            "metric_regex": r"Test accuracy: ([0-9.]+)", "scale": 100, "depends_on": ["setup"]}


def test_agent_tasks_go_to_workers_with_their_own_context(toy_case, monkeypatch):
    setup_key = c.WORKER.format(role="setup")[:30]
    diag_key = c.WORKER.format(role="diagnose")[:30]
    fake = FakeClient({
        c.PLANNER[:30]: [
            [("submit", {"reasoning": "r", "add_tasks": [{"kind": "agent", "task_id": "setup", "role": "setup",
                                                          "objective": "clone", "boundaries": "only repo/"}]})],
            [("submit", {"reasoning": "r", "add_tasks": [run_task(0), run_task(1)]})],
            [("submit", {"reasoning": "r", "finish": {}})],
        ],
        setup_key: [
            [("run_shell", {"command": f"git clone -q {toy_case} repo"}),
             ("write_file", {"path": "repo/train.py", "content": TRAIN})],
            [("submit", {"repo_dir": "repo", "python": "python3", "entrypoint": "repo/train.py", "smoke_test": "ok",
                         "ok": True})],
        ],
        diag_key: [[("submit", {"claim_id": "acc", "status": "reproduced", "confidence": "high"})]],
    })
    use_fake(monkeypatch, fake)
    ctx = runner.new_run("toy", "planner_workers")
    result = workers.run(ctx)

    assert result.verdict == "full" and result.diagnosis.present
    ev = [json.loads(l) for l in (ctx.run_dir / "trace.jsonl").read_text().splitlines()]
    agents = {e["agent"] for e in ev if e["event"] == "start"}
    assert {"planner", "setup_setup", "diagnose_final_diag_acc"} <= agents
    setup_start = next(e for e in ev if e["agent"] == "setup_setup" and e["event"] == "start")
    assert setup_start["history_len"] == 0 and "Boundaries: only repo/" in setup_start["task"]
    # the Planner's conversation holds the setup worker's report, not its tool calls
    planner_calls = [e for e in ev if e["agent"] == "planner" and e["event"] == "tool_result"]
    assert all(e["tool"] == "submit" for e in planner_calls)
    wake = [e for e in ev if e["agent"] == "planner" and e["event"] == "start"][1]["task"]
    assert '"report"' in wake and '"smoke_test": "ok"' in wake  # the worker's report is delivered in the wake
    assert json.loads((ctx.run_dir / "summary.json").read_text())["workers"] is True
