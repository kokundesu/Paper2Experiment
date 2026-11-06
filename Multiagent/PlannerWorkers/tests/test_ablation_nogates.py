"""Ablation switch gates=False (the round-1 C- setting), offline: same Planner script, but a quiet, filtered command counts."""
import json

import pytest

from p2e import runner
from p2e.testing import FakeClient, use_fake
from p2e.versions import load

c = load("PlannerWorkers")

TRAIN = """import sys
seed = int(sys.argv[sys.argv.index('--seed') + 1])
print(f'Test accuracy: {0.80 + 0.01 * seed:.4f}')
"""


def run_task(seed):
    return {"kind": "run", "task_id": f"acc_s{seed}", "claim_id": "acc", "seed": seed, "workdir": "repo",
            "command": f"python3 train.py --seed {seed} | tail -n 1", "metric_regex": r"Test accuracy: ([0-9.]+)",
            "scale": 100, "depends_on": ["setup"]}  # no smoke command, filtered output, no progress lines


def test_without_gates_a_quiet_filtered_run_counts(toy_case, monkeypatch):
    fake = FakeClient({c.PLANNER[:30]: [
        [("submit", {"reasoning": "r", "add_tasks": [{"kind": "agent", "task_id": "setup", "role": "setup",
                                                      "objective": "clone"}]})],
        [("run_shell", {"command": f"git clone -q {toy_case} repo"}), ("write_file", {"path": "repo/train.py", "content": TRAIN})],
        [("submit", {"repo_dir": "repo", "python": "python3", "entrypoint": "repo/train.py", "smoke_test": "ok", "ok": True})],
        [("submit", {"reasoning": "r", "add_tasks": [run_task(0), run_task(1)]})],
        [("submit", {"reasoning": "r", "finish": {}})],
        [("submit", {"claims": [{"claim_id": "acc", "status": "reproduced", "confidence": "low"}]})],
    ]})
    use_fake(monkeypatch, fake)
    ctx = runner.new_run("toy", "planner_nogates")
    result = c.PlannerRuntimeWorkflow(ctx, gates=False, workers=False).run()

    assert result.verdict == "full"  # the toy case has no evidence pattern: only the gates could have objected
    summary = json.loads((ctx.run_dir / "summary.json").read_text())
    assert summary["gates"] is False and summary["claims"]["acc"]["value"] == pytest.approx(80.5)
    assert not list((ctx.run_dir / "logs").glob("*smoke_*"))
    system = next(json.loads(l) for l in (ctx.run_dir / "trace.jsonl").read_text().splitlines()
                  if '"agent": "planner"' in l and '"event": "start"' in l)["system"]
    assert "enforced by the runtime" not in system and "never filtered or redirected" in system
