"""Agent evaluation of a batch of spec runs (CORE-Bench): pass rates with intervals, paired comparisons between
workflow versions, cost and time, a failure taxonomy and skill usage. Everything is read from the run directories
(summary.json, eval.json, trace.jsonl); nothing is re-graded here and no LLM is involved.

Rates:
    full            every scored question within tolerance AND produced by this run (our verdict)
    tolerance-only  every scored question within tolerance, provenance ignored (what the answers alone earn)
    hal             the original HAL harness rule (comparable with published CORE-Bench numbers)
    question acc.   scored questions answered correctly and produced by the run / scored questions

Failure taxonomy (one category per run that is not full, first match wins):
    setup_failed    the environment could not be made to work
    budget_or_turns the run hit its budget, an agent cap or the turn limit
    error           another error ended the run
    no_answers      no valid report, or no question answered
    provenance      a correct answer did not come from this run (shipped file, typed, not found)
    partial         some scored questions right
    wrong_answers   answers given, none right
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .skills import skills_read

ORDER = ["single", "fixed", "planner_workers", "planner", "planner_nogates"]
LABEL = {"single": "A", "fixed": "B", "planner_workers": "D", "planner": "C", "planner_nogates": "C-"}


@dataclass
class Run:
    dir: Path
    case: str
    workflow: str
    split: str | None
    verdict: str
    full: bool
    tol_full: bool
    hal: bool
    scored: int
    correct: int
    answered: int
    cost: float
    wall: float
    category: str | None
    error: str | None
    skills: list[str] = field(default_factory=list)
    skills_version: int | None = None
    profile: str | None = None
    skills_on: bool = True


def categorize(summary: dict, ev: dict, answered: int) -> str | None:
    if summary.get("verdict") in ("full", "unscored"):
        return None
    err = (summary.get("error") or "").lower()
    if "environment not ready" in err or "setup" in err and "fail" in err:
        return "setup_failed"
    if any(k in err for k in ("budget", "turns", "cap reached")):
        return "budget_or_turns"
    if err and not answered:
        return "error"
    if not summary.get("valid_report") or not answered:
        return "no_answers"
    if summary.get("shortcut") or summary.get("typed") or summary.get("unsupported"):
        return "provenance"
    if summary.get("verdict") == "partial":
        return "partial"
    return "wrong_answers"


def load_run(d: Path) -> Run | None:
    try:
        s = json.loads((d / "summary.json").read_text())
        ev = json.loads((d / "eval.json").read_text())
    except (OSError, ValueError):
        return None
    if "questions" not in ev:  # a paper run, not a spec run
        return None
    qs = [q for q in ev["questions"] if q.get("scored")]
    produced = lambda q: (q.get("provenance") or {}).get("status") == "produced"
    report = {}
    if (d / "report.json").is_file():
        try:
            report = json.loads((d / "report.json").read_text())
        except ValueError:
            pass
    events = [json.loads(l) for l in (d / "trace.jsonl").read_text().splitlines() if l.strip()] \
        if (d / "trace.jsonl").is_file() else []
    answered = len(report) if isinstance(report, dict) else 0
    return Run(dir=d, case=s["case"], workflow=s["workflow"], split=s.get("split"), verdict=s["verdict"],
               full=s["verdict"] == "full", tol_full=bool(s.get("full_tolerance_only")), hal=bool(s.get("hal_full")),
               scored=len(qs), correct=sum(1 for q in qs if q.get("correct") and produced(q)), answered=answered,
               cost=float(s.get("llm", {}).get("cost_usd") or 0), wall=float(s.get("wall_s") or 0),
               category=categorize(s, ev, answered), error=s.get("error"), skills=skills_read(events),
               skills_version=(s.get("skills") or {}).get("version"), profile=s.get("profile"),
               skills_on=(s.get("skills") or {}).get("enabled", True) is not False)


def collect(runs_root: Path, split: str | None = None, since: str = "", until: str = "",
            workflows: list[str] | None = None, profiles: list[str] | None = None,
            skills: bool | None = None) -> list[Run]:
    """Runs of one comparison group: a batch mixing models or skills on/off is reported one group at a time,
    since the report keeps one run per (task, workflow)."""
    out = []
    for d in sorted(runs_root.glob("*_cb-*")):
        stamp = d.name.split("_", 1)[0]
        if stamp < since or (until and stamp > until):
            continue
        r = load_run(d)
        if r and (split is None or r.split == split) and (not workflows or r.workflow in workflows) \
                and (not profiles or r.profile in profiles) and (skills is None or r.skills_on == skills):
            out.append(r)
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pairs (b: only X full, c: only Y full)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def _latest(runs: list[Run]) -> dict[tuple[str, str], Run]:
    """One run per (task, workflow): the latest, so a re-run replaces a crashed or repeated one."""
    best: dict[tuple[str, str], Run] = {}
    for r in sorted(runs, key=lambda r: r.dir.name):
        best[(r.case, r.workflow)] = r
    return best


def report(runs: list[Run], title: str = "Agent evaluation") -> str:
    by = _latest(runs)
    wfs = [w for w in ORDER if any(k[1] == w for k in by)] + sorted({k[1] for k in by} - set(ORDER))
    tasks = sorted({k[0] for k in by})
    lines = [f"# {title}", "", f"{len(tasks)} tasks, workflows: {', '.join(f'{LABEL.get(w, w)} ({w})' for w in wfs)}; "
             f"one run per task and workflow (latest).", ""]
    unscored = sorted({t for (t, w), r in by.items() if r.verdict == "unscored"})
    if unscored:
        lines += ["Unscored tasks (every question too noisy to score; left out of the rates below). Under the HAL rule "
                  "they still count, so their HAL result is listed here:", "",
                  "| Task | " + " | ".join(LABEL.get(w, w) for w in wfs) + " |", "|---" * (len(wfs) + 1) + "|"]
        lines += [f"| {t} | " + " | ".join(("HAL pass" if by[(t, w)].hal else "HAL fail") if (t, w) in by else "-"
                                          for w in wfs) + " |" for t in unscored]
        lines.append("")
    lines += ["## Pass rates", "", "| Version | Runs | Full | 95% CI | Tolerance-only | HAL rule | Question acc. | "
              "Mean cost | Total cost | Median wall | Total wall |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for w in wfs:
        rs = [by[(t, w)] for t in tasks if (t, w) in by and by[(t, w)].verdict != "unscored"]
        n, k = len(rs), sum(r.full for r in rs)
        lo, hi = wilson(k, n)
        sc, co = sum(r.scored for r in rs), sum(r.correct for r in rs)
        lines.append(f"| {LABEL.get(w, w)} | {n} | {k}/{n} ({k / n:.0%}) | {lo:.0%}–{hi:.0%} | "
                     f"{sum(r.tol_full for r in rs)}/{n} | {sum(r.hal for r in rs)}/{n} | "
                     f"{co}/{sc} ({co / sc if sc else 0:.0%}) | ${statistics.fmean(r.cost for r in rs):.3f} | "
                     f"${sum(r.cost for r in rs):.2f} | {statistics.median(r.wall for r in rs) / 60:.1f} min | "
                     f"{sum(r.wall for r in rs) / 3600:.1f} h |")
    if len(wfs) > 1:
        lines += ["", "## Paired comparisons (tasks both versions ran)", "",
                  "| Pair | Tasks | Both full | Only first | Only second | Neither | McNemar exact p |",
                  "|---|---|---|---|---|---|---|"]
        for i, x in enumerate(wfs):
            for y in wfs[i + 1:]:
                common = [t for t in tasks if (t, x) in by and (t, y) in by and t not in unscored]
                fx = {t: by[(t, x)].full for t in common}
                fy = {t: by[(t, y)].full for t in common}
                both = sum(fx[t] and fy[t] for t in common)
                b = sum(fx[t] and not fy[t] for t in common)
                c = sum(fy[t] and not fx[t] for t in common)
                lines.append(f"| {LABEL.get(x, x)} vs {LABEL.get(y, y)} | {len(common)} | {both} | {b} | {c} | "
                             f"{len(common) - both - b - c} | {mcnemar_exact(b, c):.3f} |")
    cats = ["setup_failed", "budget_or_turns", "error", "no_answers", "provenance", "partial", "wrong_answers"]
    lines += ["", "## Failure taxonomy (runs that are not full)", "",
              "| Version | " + " | ".join(cats) + " |", "|---" * (len(cats) + 1) + "|"]
    for w in wfs:
        cnt = Counter(by[(t, w)].category for t in tasks if (t, w) in by)
        lines.append(f"| {LABEL.get(w, w)} | " + " | ".join(str(cnt.get(c, 0)) for c in cats) + " |")
    lines += ["", "## Skill usage", "", "| Version | Library versions | Runs reading any skill | Reads per skill |",
              "|---|---|---|---|"]
    for w in wfs:
        rs = [by[(t, w)] for t in tasks if (t, w) in by]
        reads = Counter(s for r in rs for s in r.skills)
        vers = sorted({str(r.skills_version) for r in rs})
        lines.append(f"| {LABEL.get(w, w)} | {', '.join(vers)} | {sum(bool(r.skills) for r in rs)}/{len(rs)} | "
                     + (", ".join(f"{s} {n}" for s, n in reads.most_common()) or "-") + " |")
    lines += ["", "## Per task", "", "| Task | " + " | ".join(LABEL.get(w, w) for w in wfs) + " |",
              "|---" * (len(wfs) + 1) + "|"]
    mark = {"full": "full", "partial": "partial", "fail": "fail", "unscored": "unscored"}
    for t in tasks:
        cells = []
        for w in wfs:
            r = by.get((t, w))
            cells.append("-" if r is None else mark.get(r.verdict, r.verdict)
                         + (f" ({r.category})" if r.category and r.category not in ("partial",) else ""))
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    errors = defaultdict(list)
    for (t, w), r in by.items():
        if r.error:
            errors[w].append(f"{t}: {r.error[:160]}")
    if errors:
        lines += ["", "## Errors", ""]
        for w in wfs:
            for e in errors.get(w, []):
                lines.append(f"- {LABEL.get(w, w)} {e}")
    lines += ["", "Small samples: with about 20 tasks, a difference of a few tasks is within noise; read the "
              "intervals and the exact p-values before ranking versions."]
    return "\n".join(lines) + "\n"
