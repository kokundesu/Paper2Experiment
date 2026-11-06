"""The web UI's data layer, on a synthetic run directory (runs/ is git-ignored, so no real run is assumed)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from p2e.web import data


def _event(agent, event, t, **kw):
    return json.dumps({"t": t, "agent": agent, "event": event, **kw}) + "\n"


def _multi_run(tmp_path: Path, finished: bool) -> Path:
    d = tmp_path / "20261007-120000_gcn_multi"
    d.mkdir()
    t0 = time.time() - 300
    lines = [
        _event("runner", "start", t0, case="gcn", workflow="multi", model="gpt-6-luna", budget_usd=5.0),
        _event("paper_analyst", "start", t0 + 1, model="gpt-6-luna", effort="medium", task="..."),
        _event("paper_analyst", "response", t0 + 2, turn=1, status="completed", text="", tool_calls=[{"name": "read_file", "input": "{}"}]),
        _event("paper_analyst", "tool_result", t0 + 2.1, tool="read_file", is_error=False, output="x" * 5000),
        _event("paper_analyst", "end", t0 + 10, usage={"requests": 2, "tool_calls": 1, "wall_s": 9}, cost_usd=0.001, run_spent_usd=0.001),
        _event("env_agent", "start", t0 + 11, model="gpt-6-luna", effort="medium"),
        _event("env_agent", "end", t0 + 60, usage={"requests": 5, "tool_calls": 9, "wall_s": 49}, cost_usd=0.004, run_spent_usd=0.005),
        _event("planner", "start", t0 + 61),
        _event("planner", "end", t0 + 70, usage={"requests": 2, "tool_calls": 2, "wall_s": 9}, cost_usd=0.001, run_spent_usd=0.006),
        _event("executor", "run", t0 + 80, run_id="a", claim_id="cora_acc", seed=0, command="python train.py", workdir="repo",
               exit_code=0, duration_s=9.5, value=81.6, log_path="logs/cmd_010_exp.log", attempts=1, debug_notes=[]),
        _event("result_reviewer", "start", t0 + 81),
    ]
    if finished:
        lines += [
            _event("result_reviewer", "end", t0 + 100, usage={"requests": 3, "tool_calls": 4, "wall_s": 19}, cost_usd=0.003, run_spent_usd=0.009),
            _event("executor", "run", t0 + 110, run_id="b", claim_id="cora_acc", seed=1, command="python train.py", workdir="repo",
                   exit_code=0, duration_s=9.5, value=81.9, log_path="logs/cmd_011_exp.log", attempts=1, debug_notes=[]),
            _event("discrepancy_analyst", "start", t0 + 111),
            _event("discrepancy_analyst", "end", t0 + 150, usage={"requests": 4, "tool_calls": 6, "wall_s": 39}, cost_usd=0.005, run_spent_usd=0.014),
            _event("runner", "end", t0 + 151, verdict="full"),
        ]
        (d / "summary.json").write_text(json.dumps({
            "case": "gcn", "workflow": "multi", "model": "gpt-6-luna", "verdict": "full", "error": None, "wall_s": 151.0,
            "llm": {"requests": 16, "tool_calls": 22, "cost_usd": 0.014, "budget_usd": 5.0},
            "claims": {"cora_acc": {"target": 81.5, "aggregate": "mean", "value": 81.75, "mean": 81.75, "std": 0.2, "n": 2,
                                    "pass": True, "reason": "", "diagnostic_only": False}},
            "diagnosis": {"present": True, "n_failing": 0, "n_detected": 0, "false_success": [], "n_attributed": 0,
                          "n_attribution_correct": 0, "n_strict_correct": 0}}))
    (d / "trace.jsonl").write_text("".join(lines))
    (d / "paper_spec.json").write_text("{}")
    return d


def test_stages_of_a_running_multi_run(tmp_path: Path):
    d = _multi_run(tmp_path, finished=False)
    detail = data.run_detail(d)
    assert detail["status"] == "running" and detail["case"] == "gcn" and detail["workflow"] == "multi"
    states = {s["key"]: s["state"] for s in detail["stages"]}
    assert states["paper_analyst"] == states["env_agent"] == states["planner"] == "done"
    assert states["executor_pilot"] == "done" and states["result_reviewer"] == "running"
    assert states["executor_rest"] == states["discrepancy_analyst"] == states["evaluator"] == "pending"
    pilot = next(s for s in detail["stages"] if s["key"] == "executor_pilot")
    assert pilot["runs"] == 1
    assert detail["spent_usd"] == 0.006 and detail["measured"] == {"cora_acc": [81.6]}
    # The feed is compact: tool output is cut, the task prompt is not echoed.
    tr = next(e for e in detail["events"] if e["event"] == "tool_result")
    assert len(tr["output"]) == 500
    assert "task" not in next(e for e in detail["events"] if e["event"] == "start" and e["agent"] == "paper_analyst")


def test_finished_run_marks_all_stages_and_lists_cheaply(tmp_path: Path, monkeypatch):
    d = _multi_run(tmp_path, finished=True)
    detail = data.run_detail(d, since=12)
    assert detail["status"] == "done"
    assert all(s["state"] == "done" for s in detail["stages"])
    assert detail["events"][0]["i"] == 12 and detail["total_events"] == 16
    rest = next(s for s in detail["stages"] if s["key"] == "executor_rest")
    assert rest["runs"] == 1 and rest["debuggers"] == []
    monkeypatch.setattr(data, "RUNS", tmp_path)
    monkeypatch.setattr(data, "VERSIONS_FILE", tmp_path / "none.json")
    rows = data.list_runs()
    assert len(rows) == 1 and rows[0]["verdict"] == "full" and rows[0]["claims"] == "1/1"
    assert rows[0]["version"] == data.CURRENT_VERSION and rows[0]["status"] == "done"


def test_stale_trace_without_summary_is_aborted(tmp_path: Path):
    d = _multi_run(tmp_path, finished=False)
    import os
    old = time.time() - data.RUNNING_GRACE_S - 60
    os.utime(d / "trace.jsonl", (old, old))
    assert data.run_status(d, None) == "aborted"
    assert data.run_status(d, None, alive=True) == "running"


def test_compare_aggregates_by_workflow(monkeypatch):
    rows_in = [
        {"verdict": "full", "wall_min": 10.0, "usd": 0.02, "requests": 20, "tool_calls": 30, "failing": 1, "detected": 1,
         "false_success": 0, "false_alarm": 0, "attributed": 1, "attribution_correct": 1, "strict_correct": 0},
        {"verdict": "fail", "wall_min": 20.0, "usd": 0.04, "requests": 40, "tool_calls": 50, "failing": 2, "detected": 2,
         "false_success": 0, "false_alarm": 1, "attributed": 2, "attribution_correct": 1, "strict_correct": 0},
    ]
    agg = data._agg(rows_in)
    assert agg["n"] == 2 and agg["full"] == 1 and agg["fail"] == 1
    assert agg["wall_min"] == 15.0 and agg["usd"] == 0.03 and agg["requests"] == 30
    assert agg["failing"] == 3 and agg["detected"] == 3 and agg["false_alarm"] == 1 and agg["attribution_correct"] == 2
    assert data._agg([])["n"] == 0 and data._agg([])["wall_min"] is None
    assert [data._version_key(v) for v in ("V0.1", "V2", "V2.1+")] == [(0, 1, 0), (2, 0), (2, 1, 1)]
