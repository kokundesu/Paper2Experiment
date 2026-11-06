"""Read-only views of runs/ for the web UI.

Everything here is derived from files a run writes anyway: `trace.jsonl` (appended live, one JSON event per
line) gives the stage a running run is in and the event feed; `summary.json` marks a finished run. Finished
runs are re-scored with the current evaluator and case.yaml so that the comparison uses one set of rules,
like `p2e eval` and the reports (`p2e eval` prints, this caches).
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from ..evaluator import evaluate
from ..runner import BENCHMARK, RUNS
from ..schemas import Case, DiscrepancyReport, EvalResult, Metrics

# A run with no summary.json whose trace has not grown for this long is treated as aborted, not running.
RUNNING_GRACE_S = 30 * 60
# Version labels of the runs made before the web UI existed (see docs/03-single-vs-multi-report.html).
VERSIONS_FILE = RUNS / "all_versions_rescored.json"
CURRENT_VERSION = "V2.1+"

# Stage keys per workflow, in pipeline order. LLM roles use their trace `agent` name; the others are
# derived (executor_* from executor runs, evaluator from summary.json).
_PIPELINE = ["paper_analyst", "env_agent", "planner", "executor_pilot", "result_reviewer", "executor_rest",
             "discrepancy_analyst", "evaluator"]
# Workflows without an entry (the Planner + Runtime versions) show the roles their trace actually started.
STAGES = {
    "fixed": _PIPELINE,
    "multi": _PIPELINE,  # runs made before the version folders, when the fixed pipeline was called "multi"
    "single": ["single_agent", "evaluator"],
    "deterministic": ["deterministic", "evaluator"],
}
LLM_ROLES = {"paper_analyst", "env_agent", "planner", "result_reviewer", "discrepancy_analyst", "single_agent"}


# ---------------------------------------------------------------- trace


_trace_cache: dict[Path, tuple[tuple[float, int], list[dict]]] = {}


def read_trace(run_dir: Path) -> list[dict]:
    """All events of a run; cached by (mtime, size). A half-written last line is skipped."""
    path = run_dir / "trace.jsonl"
    if not path.is_file():
        return []
    st = path.stat()
    key = (st.st_mtime, st.st_size)
    hit = _trace_cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    events = []
    with path.open() as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    _trace_cache[path] = (key, events)
    return events


def compact(i: int, e: dict) -> dict:
    """One trace event trimmed for the live feed."""
    ev = e.get("event")
    out = {"i": i, "t": e.get("t"), "agent": e.get("agent"), "event": ev}
    if ev == "response":
        out["turn"] = e.get("turn")
        out["text"] = (e.get("text") or "")[:600]
        out["tool_calls"] = [{"name": c.get("name"), "input": str(c.get("input", ""))[:300]}
                             for c in e.get("tool_calls") or []]
    elif ev == "tool_result":
        out["tool"] = e.get("tool")
        out["is_error"] = bool(e.get("is_error"))
        out["output"] = (e.get("output") or "")[:500]
    elif ev == "run":
        for k in ("run_id", "claim_id", "seed", "value", "exit_code", "duration_s", "log_path", "attempts"):
            out[k] = e.get(k)
        out["command"] = (e.get("command") or "")[:300]
    elif ev == "start":
        for k in ("model", "effort", "case", "workflow", "budget_usd"):
            if k in e:
                out[k] = e[k]
    elif ev == "end":
        u = e.get("usage") or {}
        out["cost_usd"] = e.get("cost_usd")
        out["run_spent_usd"] = e.get("run_spent_usd")
        out["requests"] = u.get("requests")
        out["tool_calls"] = u.get("tool_calls")
        out["wall_s"] = u.get("wall_s")
        if "verdict" in e:
            out["verdict"] = e["verdict"]
    elif ev == "submit":
        out["output"] = json.dumps(e.get("output"), ensure_ascii=False, default=str)[:600]
    elif ev == "entrypoint":
        out["detail"] = json.dumps({k: v for k, v in e.items() if k not in ("t", "agent", "event")},
                                   ensure_ascii=False, default=str)[:400]
    return out


# ---------------------------------------------------------------- one run


def _summary(run_dir: Path) -> dict | None:
    """summary.json, with verdict, claims and diagnosis replaced by the current rules (see `rescore`), so the
    run list, the detail view and the comparison agree with `p2e eval`. The file itself is left as written."""
    p = run_dir / "summary.json"
    if not p.is_file():
        return None
    summary = json.loads(p.read_text())
    result = rescore(run_dir, summary)
    if result is None:
        return summary
    dg = result.diagnosis
    summary["verdict"] = result.verdict
    summary["claims"] = {v.claim_id: {"target": v.target, "aggregate": v.aggregate, "value": v.measured_agg,
                                      "mean": v.measured_mean, "std": v.measured_std, "n": v.n_values,
                                      "pass": v.within_tolerance and v.evidence_ok, "reason": v.reason,
                                      "diagnostic_only": v.diagnostic_only} for v in result.claims}
    if dg is not None:
        summary["diagnosis"] = {"present": dg.present, "n_failing": len(dg.failing), "n_detected": len(dg.detected),
                                "false_success": dg.false_success, "false_alarm": dg.false_alarm,
                                "n_attributed": sum(a.scored for a in dg.attributions),
                                "n_attribution_correct": sum(a.scored and a.correct for a in dg.attributions),
                                "n_strict_correct": sum(a.scored and a.strict_correct for a in dg.attributions)}
    return summary


def run_status(run_dir: Path, summary: dict | None, alive: bool | None = None) -> str:
    """done / error / running / aborted. `alive` is what the server knows about a process it launched."""
    if summary is not None:
        return "error" if summary.get("error") else "done"
    if alive is True:
        return "running"
    if alive is False:
        return "aborted"
    trace = run_dir / "trace.jsonl"
    if trace.is_file() and time.time() - trace.stat().st_mtime < RUNNING_GRACE_S:
        return "running"
    return "aborted"


def stages(workflow: str, events: list[dict], finished: bool) -> list[dict]:
    """State of each pipeline stage: pending / running / done / skipped, with time and cost where known."""
    roles: dict[str, dict] = {}
    for e in events:
        a, ev = e.get("agent"), e.get("event")
        if ev == "start" and a != "runner":
            roles.setdefault(a, {"started": e["t"], "ended": None, "cost_usd": None, "usage": None})
        elif ev == "end" and a in roles:
            roles[a].update(ended=e["t"], cost_usd=e.get("cost_usd"), usage=e.get("usage"))
    runs = [e for e in events if e.get("event") == "run"]
    reviewer = roles.get("result_reviewer")
    analyst = roles.get("discrepancy_analyst")
    planner = roles.get("planner")
    split = reviewer["started"] if reviewer else None
    pilots = [r for r in runs if split is None or r["t"] <= split]
    rest = [r for r in runs if split is not None and r["t"] > split]
    debuggers = sorted(k for k in roles if k.startswith("debugger"))

    out = []
    # A workflow without a fixed stage list shows every role its trace started, in order, then the evaluator.
    keys = STAGES.get(workflow) or [*roles, "evaluator"]
    for key in keys:
        st = {"key": key, "state": "pending", "started": None, "ended": None, "cost_usd": None, "requests": None,
              "tool_calls": None, "runs": None, "debuggers": None}
        if key in LLM_ROLES or (key in roles and workflow not in STAGES):
            r = roles.get(key)
            if r:
                st.update(started=r["started"], ended=r["ended"], cost_usd=r["cost_usd"],
                          state="done" if r["ended"] else "running")
                if r["usage"]:
                    st.update(requests=r["usage"].get("requests"), tool_calls=r["usage"].get("tool_calls"))
        elif key == "executor_pilot":
            st["runs"] = len(pilots)
            if planner and planner["ended"]:
                st["started"] = planner["ended"]
                if reviewer:
                    st.update(state="done", ended=reviewer["started"])
                else:
                    st["state"] = "running"
        elif key == "executor_rest":
            st["runs"] = len(rest)
            st["debuggers"] = [{"key": d, "state": "done" if roles[d]["ended"] else "running",
                                "cost_usd": roles[d]["cost_usd"]} for d in debuggers]
            if reviewer and reviewer["ended"]:
                st["started"] = reviewer["ended"]
                if analyst:
                    st.update(state="done", ended=analyst["started"])
                else:
                    st["state"] = "running"
        elif key == "deterministic":
            if events:
                st.update(started=events[0]["t"], state="done" if finished else "running")
        elif key == "evaluator":
            if finished:
                st["state"] = "done"
        if finished and st["state"] == "pending":
            st["state"] = "skipped"
        if finished and st["state"] == "running":  # the run ended without this role's end event (error / budget)
            st["state"] = "done"
        out.append(st)
    return out


def _case_tolerances(case_id: str) -> dict[str, dict]:
    try:
        case = Case.load(BENCHMARK / case_id)
    except Exception:
        return {}
    return {c.id: {"target": c.value, "unit": c.unit, "setting": c.setting, "diagnostic_only": c.diagnostic_only,
                   "tolerance": c.tolerance.model_dump(exclude_none=True), "describe": c.tolerance.describe(c.unit or "")}
            for c in case.claims}


def run_detail(run_dir: Path, since: int = 0, alive: bool | None = None, limit: int = 400) -> dict:
    events = read_trace(run_dir)
    summary = _summary(run_dir)
    status = run_status(run_dir, summary, alive)
    finished = summary is not None
    runner_start = next((e for e in events if e.get("agent") == "runner" and e.get("event") == "start"), None)
    case_id = (summary or runner_start or {}).get("case") or run_dir.name.split("_", 2)[1]
    workflow = (summary or runner_start or {}).get("workflow") or run_dir.name.rsplit("_", 1)[-1]
    spent = next((e.get("run_spent_usd") for e in reversed(events) if e.get("event") == "end" and "run_spent_usd" in e),
                 None)
    if summary:
        spent = summary["llm"].get("cost_usd", spent)
    started_t = runner_start["t"] if runner_start else (events[0]["t"] if events else None)
    elapsed = summary["wall_s"] if summary else (time.time() - started_t if started_t else None)
    feed_from = since if since > 0 else max(0, len(events) - limit)
    files = sorted(p.name for p in run_dir.glob("*.json") if p.name not in ("task.json", "log_manifest.json"))
    # Live measurements before the evaluator runs: executor runs grouped by claim.
    measured: dict[str, list] = {}
    for e in events:
        if e.get("event") == "run" and e.get("claim_id"):
            measured.setdefault(e["claim_id"], []).append(e.get("value"))
    return {
        "name": run_dir.name, "case": case_id, "workflow": workflow, "status": status,
        "model": (summary or runner_start or {}).get("model"),
        "budget_usd": (runner_start or {}).get("budget_usd") or (summary or {}).get("llm", {}).get("budget_usd"),
        "spent_usd": spent, "started": started_t, "elapsed_s": elapsed,
        "stages": stages(workflow, events, finished),
        "executor_runs": [compact(i, e) for i, e in enumerate(events) if e.get("event") == "run"],
        "measured": measured,
        "claims_gt": _case_tolerances(case_id),
        "summary": summary,
        "files": files,
        "events": [compact(i, events[i]) for i in range(feed_from, len(events))],
        "total_events": len(events),
    }


def list_runs(alive: dict[str, bool] | None = None) -> list[dict]:
    """One row per run directory, newest first. Finished runs come from summary.json alone (cheap); running
    ones from their trace."""
    alive = alive or {}
    versions = version_labels()
    rows = []
    for d in sorted((p for p in RUNS.iterdir() if p.is_dir() and (p / "trace.jsonl").is_file()),
                    key=lambda p: p.name, reverse=True):
        summary = _summary(d)
        status = run_status(d, summary, alive.get(d.name))
        row = {"name": d.name, "status": status, "version": versions.get(d.name, CURRENT_VERSION), "stage": None,
               "verdict": None, "wall_s": None, "usd": None, "claims": None, "error": None, "started": None}
        if summary:
            scored = [c for c in summary["claims"].values() if not c.get("diagnostic_only")]
            row.update(case=summary["case"], workflow=summary["workflow"], verdict=summary["verdict"],
                       wall_s=summary["wall_s"], usd=summary["llm"].get("cost_usd"), error=summary.get("error"),
                       claims=f"{sum(c['pass'] for c in scored)}/{len(scored)}")
            row["started"] = d.stat().st_mtime - summary["wall_s"]
        else:
            events = read_trace(d)
            start = next((e for e in events if e.get("agent") == "runner" and e.get("event") == "start"), None)
            parts = d.name.split("_")
            row.update(case=(start or {}).get("case") or (parts[1] if len(parts) > 2 else "?"),
                       workflow=(start or {}).get("workflow") or (parts[2] if len(parts) > 2 else "?"),
                       started=start["t"] if start else None)
            running = [s["key"] for s in stages(row["workflow"], events, False) if s["state"] == "running"]
            row["stage"] = running[-1] if running else None
            row["usd"] = next((e.get("run_spent_usd") for e in reversed(events) if e.get("event") == "end"), None)
        rows.append(row)
    return rows


# ---------------------------------------------------------------- comparison


_score_cache: dict[Path, tuple[float, EvalResult]] = {}


def rescore(run_dir: Path, summary: dict | None = None) -> EvalResult | None:
    """The run scored with the current evaluator and case.yaml (what `p2e eval` prints), cached by mtime."""
    metrics_path = run_dir / "metrics.json"
    if summary is None:
        p = run_dir / "summary.json"
        summary = json.loads(p.read_text()) if p.is_file() else None
    if summary is None or not metrics_path.is_file():
        return None
    case_yaml = BENCHMARK / summary["case"] / "case.yaml"
    if not case_yaml.is_file():
        return None
    mtime = max(metrics_path.stat().st_mtime, case_yaml.stat().st_mtime)
    hit = _score_cache.get(run_dir)
    if hit and hit[0] == mtime:
        return hit[1]
    manifest_path = run_dir / "log_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    try:
        result = evaluate(Case.load(BENCHMARK / summary["case"]), Metrics.model_validate_json(metrics_path.read_text()),
                          run_dir, summary["workflow"], DiscrepancyReport.load(run_dir), manifest)
    except Exception:
        return None
    _score_cache[run_dir] = (mtime, result)
    return result


def version_labels() -> dict[str, str]:
    if not VERSIONS_FILE.is_file():
        return {}
    try:
        return {r["run"]: r["ver"] for r in json.loads(VERSIONS_FILE.read_text())}
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


def _agg(rows: list[dict]) -> dict:
    n = len(rows)
    mean = lambda k: round(statistics.fmean(r[k] for r in rows if r.get(k) is not None), 4) if any(r.get(k) is not None for r in rows) else None  # noqa: E731
    return {
        "n": n,
        "full": sum(r["verdict"] == "full" for r in rows),
        "partial": sum(r["verdict"] == "partial" for r in rows),
        "fail": sum(r["verdict"] == "fail" for r in rows),
        "wall_min": mean("wall_min"), "usd": mean("usd"), "requests": mean("requests"), "tool_calls": mean("tool_calls"),
        "failing": sum(r["failing"] for r in rows), "detected": sum(r["detected"] for r in rows),
        "false_success": sum(r["false_success"] for r in rows), "false_alarm": sum(r["false_alarm"] for r in rows),
        "attributed": sum(r["attributed"] for r in rows), "attribution_correct": sum(r["attribution_correct"] for r in rows),
        "strict_correct": sum(r["strict_correct"] for r in rows),
    }


def compare(version: str | None = None, case: str | None = None) -> dict:
    """Single vs multi (vs deterministic) over all finished runs, re-scored with the current rules."""
    versions = version_labels()
    rows = []
    for d in sorted(p for p in RUNS.iterdir() if p.is_dir()):
        summary = _summary(d)
        if summary is None or summary.get("error"):
            continue
        result = rescore(d, summary)
        if result is None:
            continue
        dg = result.diagnosis
        rows.append({
            "run": d.name, "version": versions.get(d.name, CURRENT_VERSION), "case": summary["case"],
            "workflow": summary["workflow"], "verdict": result.verdict,
            "wall_min": summary["wall_s"] / 60, "usd": summary["llm"].get("cost_usd"),
            "requests": summary["llm"].get("requests"), "tool_calls": summary["llm"].get("tool_calls"),
            "failing": len(dg.failing) if dg else 0, "detected": len(dg.detected) if dg else 0,
            "false_success": len(dg.false_success) if dg else 0, "false_alarm": len(dg.false_alarm) if dg else 0,
            "attributed": sum(a.scored for a in dg.attributions) if dg else 0,
            "attribution_correct": sum(a.scored and a.correct for a in dg.attributions) if dg else 0,
            "strict_correct": sum(a.scored and a.strict_correct for a in dg.attributions) if dg else 0,
            "claims": [{"id": c.claim_id, "target": c.target, "value": c.measured_agg, "pass": c.within_tolerance and c.evidence_ok,
                        "agg_within": c.agg_within, "diagnostic_only": c.diagnostic_only} for c in result.claims],
        })
    all_versions = sorted({r["version"] for r in rows}, key=_version_key)
    all_cases = sorted({r["case"] for r in rows})
    selected = [r for r in rows if (not version or r["version"] == version) and (not case or r["case"] == case)]
    workflows = ["single", "multi", "deterministic"]
    by_workflow = {wf: _agg([r for r in selected if r["workflow"] == wf]) for wf in workflows
                   if any(r["workflow"] == wf for r in selected)}
    by_version = [{"version": v, **{wf: _agg([r for r in rows if r["version"] == v and r["workflow"] == wf
                                              and (not case or r["case"] == case)])
                                    for wf in ("single", "multi")}} for v in all_versions]
    by_case = {}
    for c in sorted({r["case"] for r in selected}):
        by_case[c] = {wf: {"full": sum(r["verdict"] == "full" for r in selected if r["case"] == c and r["workflow"] == wf),
                           "n": sum(1 for r in selected if r["case"] == c and r["workflow"] == wf)}
                      for wf in workflows}
    # Per claim: paper value, tolerance, and every measured aggregate per workflow, for the dot plot.
    claims = []
    for c in sorted({r["case"] for r in selected}):
        gt = _case_tolerances(c)
        for cid, g in gt.items():
            entry = {"case": c, "claim": cid, **g, "values": {}}
            for wf in ("single", "multi"):
                # claim ids repeat across cases (DLinear and FITS both have etth1_96_mse), so match the case too
                entry["values"][wf] = [{"run": r["run"], "value": cl["value"], "pass": cl["pass"]}
                                       for r in selected if r["workflow"] == wf and r["case"] == c
                                       for cl in r["claims"] if cl["id"] == cid and cl["value"] is not None]
            claims.append(entry)
    return {"versions": all_versions, "cases": all_cases, "version": version, "case": case,
            "n_runs": len(selected), "by_workflow": by_workflow, "by_version": by_version, "by_case": by_case,
            "claims": claims, "runs": selected}


def _version_key(v: str) -> tuple:
    body = v.lstrip("V").rstrip("+")
    try:
        return tuple(int(x) for x in body.split(".")) + ((1,) if v.endswith("+") else (0,))
    except ValueError:
        return (999,)
