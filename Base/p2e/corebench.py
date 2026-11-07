"""CORE-Bench v1.1 (arXiv 2606.26158) as an external dataset, graded with our tolerance rule.

Ground truth is `benchmark/corebench_v1.1/core_test.json` from the Hugging Face dataset
agent-evals/core-bench-v1.1-mainline: one entry per capsule, `results` = the answers of n=3 manual re-runs. The
agent answers every question of a task once (m=1) in a dict keyed by the question text.

Numeric answers pass when |answer - mean| <= h, where (the project's tolerance rule, TOLERANCE_RULE; agreed
2026-10-16, also used for the v4 reference re-runs in p2e.reference)

    h = max(t(0.975, n-1) * s * sqrt(1/m + 1/n),   # noise of the re-runs (CORE-Bench's prediction interval)
            half a unit of the ground truth's last printed digit,   # precision
            1e-5 * |mean|, or 1e-8 when the mean is 0)   # floating point

The question h answers: if the agent did exactly what the official code does and only the seed changed, how far
from the reference mean could its result land? Each term covers one legitimate source of difference:

- noise: randomness. s (ddof=1) estimates one run's spread; sqrt(1/m + 1/n) turns it into the spread of "mean of
  the agent's m runs minus mean of the n reference runs" (independent, so variances add); t instead of 1.96 because
  s itself comes from only n runs. With m=1 this is CORE-Bench's own 95% prediction interval (Fig. 4, HAL harness
  `__eval_result_json`; arXiv 2606.26158 appendix A.5.3; Spence & Stanley 2016). An agent that changes epochs,
  splits or other settings lands outside it systematically, which is what the rule should catch.
- precision: resolution. No agreement finer than the reported precision is required, and unrounded answers are
  accepted (the role of v1.1's fix 2, appendix A.1; ReplicationBench appendix D). Mostly the floor for
  deterministic code (s = 0).
- floor: floating point (thread counts, BLAS). Only the relative part of numpy.isclose's defaults is kept: an
  absolute 1e-8 would pass any answer in [0, 1e-8] for capsule-0152700's p value of 2.34e-10 and wrongly make it
  stochastic (revised 2026-10-16).

The terms are taken as a maximum, not a sum: they are three lower bounds on one allowed gap, not independent errors
(the noise term already contains floating-point noise), so adding them would count twice. No separate rounding is
applied. A question whose h exceeds 5% of |mean| is `stochastic`: at that width "within tolerance" no longer shows
the run was right, so it is reported, not scored. Tolerances are computed by code and frozen before any agent under
test runs, never adjusted after; reports should add a sensitivity check at h x 0.5 / 1 / 2.
Strings compare case-insensitively (booleans as "true"/"false"), except strings that hold a number, which compare
as numbers. Lists compare element by element in order. A task is full when every scored question passes.

`hal_grade` reproduces the original HAL harness rule (hal/benchmarks/corebench.py on princeton-pli/hal-harness
main) so the two can be compared; the v1.1 grader itself is distributed encrypted.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from . import capsule, skills
from .llm import Budget, Trace
from .models import get_profile
from .runner import BENCHMARK, RUNS, RunContext
from .sandbox import Sandbox, file_sha256
from .schemas import Task
from .spec import Answers, AnswerItem, CodeInput, Question, ReproSpec, SpecOrigin, brief

# Two splits, both drawn by CORE-Bench itself, not by us. test: the v1.1 mainline set (39 capsules, core_test.json
# from Hugging Face agent-evals), run once after the code and the skill library are frozen. dev: the original
# CORE-Bench train set (45 capsules, core_train.json from GitHub siegelz/core-bench; v1.1 ships no train set), which
# every tuning round and the skill library may use. The two are disjoint by capsule_id. The 5 PILOTED capsules below
# were tried while building this adapter and the grader was changed after them, so they are excluded from test.
ROOT = BENCHMARK / "corebench_v1.1"
DATA = ROOT / "core_test.json"
CAPSULES = ROOT / "capsules"
TASKS = ROOT / "tasks"
DEV_ROOT = BENCHMARK / "corebench_v1_train"
DEV_DATA = DEV_ROOT / "core_train.json"
DEV_CAPSULES = DEV_ROOT / "capsules"
DEV_TASKS = DEV_ROOT / "tasks"
CAPSULE_URL = {"test": "https://huggingface.co/datasets/agent-evals/core-bench-v1.1-mainline/resolve/main/capsules/"
                       "{id}.tar.gz",
               "dev": "https://corebench.cs.princeton.edu/capsules/{id}.tar.gz"}
# Test capsules already run while the adapter was built (2026-10-16 pilots, three rounds, grader fixes made on what
# they showed): seen during development, so they leave the test split.
PILOTED = frozenset({"capsule-0201673", "capsule-6049678", "capsule-7655932", "capsule-7800694", "capsule-8412128"})
TOLERANCE_RULE = "p2e tolerance rule 2026-10-16 (p2e/corebench.py docstring)"
STOCHASTIC_SHARE = 0.05
RTOL, ATOL = 1e-5, 1e-8  # numpy.isclose's defaults; ATOL only when the mean is 0, else it swamps tiny values

# two-sided 97.5% quantiles of Student's t by degrees of freedom
_T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
         15: 2.131, 20: 2.086, 30: 2.042}
_NUMBER = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")

# Table 11 of the paper: questions that accept more than one answer. Only the cases the paper describes precisely
# enough are encoded; the others need the capsule's result files and are flagged as `alternates_pending`.
ALTERNATES = {
    ("capsule-4252248", "Report the overall AUC from the PR curve"): {"round_to": 3},
    ("capsule-9477017", "Pearson correlation coefficients"): {"order_agnostic": True},
}
ALTERNATES_PENDING = {
    ("capsule-2816027", "For CTCF Signature Enrichment"): "figure label and group name differ; both accepted",
    ("capsule-3639589", "Report the color of the line"): "two plots with different colours; both accepted",
    ("capsule-0152700", "Given the Kruskal-Wallis"): "three deterministic p-values in the results; all accepted",
}


def t975(df: int) -> float:
    if df in _T975:
        return _T975[df]
    return _T975[max(k for k in _T975 if k <= df)]  # a slightly wider interval between table rows


def decimals(value) -> int:
    """Digits after the decimal point as the value is written (scientific notation counted)."""
    text = value if isinstance(value, str) else repr(value)
    mantissa, _, exp = text.lower().partition("e")
    places = len(mantissa.partition(".")[2])
    return places - int(exp) if exp else places


def tolerance(values: list[float], m: int = 1, places: int | None = None) -> dict:
    """h and its three terms for re-run `values`; `places` = printed precision (default: the values' own)."""
    n, mean = len(values), statistics.fmean(values)
    s = statistics.stdev(values) if n > 1 else 0.0
    noise = t975(n - 1) * s * math.sqrt(1 / m + 1 / n) if n > 1 else 0.0
    if places is None:
        places = max(decimals(v) for v in values)
    precision = 0.5 * 10 ** -places
    floor = RTOL * abs(mean) if mean else ATOL
    h = max(noise, precision, floor)
    term = "noise" if h == noise else "precision" if h == precision else "floor"
    return {"mean": mean, "s": s, "n": n, "m": m, "noise": noise, "precision": precision, "floor": floor, "h": h,
            "term": term, "stochastic": abs(mean) > 0 and h > STOCHASTIC_SHARE * abs(mean)}


def _as_number(x) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        t = x.strip().rstrip("%").replace(",", "").strip()
        if _NUMBER.match(t):
            return float(t)
    return None


def _as_text(x) -> str:
    return (("true" if x else "false") if isinstance(x, bool) else str(x)).strip().lower()


@dataclass
class QuestionResult:
    question: str
    kind: str  # numeric | string | list
    correct: bool
    scored: bool = True  # False for stochastic questions
    vision: bool = False
    detail: dict = field(default_factory=dict)
    note: str = ""


@dataclass
class TaskResult:
    capsule_id: str
    full: bool | None  # None when no question is scored
    questions: list[QuestionResult]
    valid: bool = True  # the answer parsed as a dict

    @property
    def scored(self) -> list[QuestionResult]:
        return [q for q in self.questions if q.scored]


def _numeric(values: list[float], answer, places: int | None = None) -> tuple[bool, dict]:
    tol = tolerance(values, places=places)
    a = _as_number(answer)
    ok = a is not None and abs(a - tol["mean"]) <= tol["h"]
    return ok, tol | {"answer": a}


def _alternate(capsule_id: str, question: str, table: dict):
    return next((v for (cid, prefix), v in table.items() if cid == capsule_id and question.startswith(prefix)), None)


def grade_question(capsule_id: str, question: str, gt: list, answer) -> QuestionResult:
    """Grade one answer against the re-run values `gt` of one question."""
    vision = "fig" in question
    alt = _alternate(capsule_id, question, ALTERNATES) or {}
    pending = _alternate(capsule_id, question, ALTERNATES_PENDING) or ""
    first = gt[0]
    if isinstance(first, (int, float)) and not isinstance(first, bool) or (
            isinstance(first, str) and _as_number(first) is not None):
        values = [_as_number(v) for v in gt]
        ok, detail = _numeric(values, answer)
        if not ok and "round_to" in alt:
            ok, detail = _numeric([round(statistics.fmean(values), alt["round_to"])], answer, alt["round_to"])
            detail["alternate"] = f"rounded to {alt['round_to']} places"
        return QuestionResult(question, "numeric", ok, scored=not detail["stochastic"], vision=vision,
                              detail=detail, note=pending)
    if isinstance(first, list):
        if not isinstance(answer, list) or len(answer) != len(first):
            return QuestionResult(question, "list", False, vision=vision, note=pending)
        if alt.get("order_agnostic") and all(isinstance(x, str) for x in first):
            ok = sorted(map(_as_text, answer)) == sorted(map(_as_text, first))
            return QuestionResult(question, "list", ok, vision=vision, note=pending)
        items = [grade_question(capsule_id, f"{question}[{i}]", [run[i] for run in gt], answer[i])
                 for i in range(len(first))]
        return QuestionResult(question, "list", all(q.correct for q in items),
                              scored=all(q.scored for q in items), vision=vision,
                              detail={"items": [q.detail for q in items]}, note=pending)
    return QuestionResult(question, "string", _as_text(answer) == _as_text(first), vision=vision, note=pending)


def grade_task(task: dict, report) -> TaskResult:
    """Grade an agent's answers (dict, or its JSON text) for one CORE-Bench task."""
    runs = task["results"]
    if isinstance(report, str):
        try:
            report = json.loads(report)
        except json.JSONDecodeError:
            report = None
    valid = isinstance(report, dict)
    report = report if valid else {}
    questions = [grade_question(task["capsule_id"], q, [r[q] for r in runs], report.get(q)) if q in report
                 else QuestionResult(q, "missing", False, vision="fig" in q, note="no answer")
                 for q in runs[0]]
    scored = [q for q in questions if q.scored]
    return TaskResult(task["capsule_id"], all(q.correct for q in scored) if scored else None, questions, valid)


def hal_grade(task: dict, report: dict) -> bool:
    """The original HAL harness rule: prediction interval for numbers, lower-cased equality for strings, exact
    equality for lists, every question correct. Kept for comparison with `grade_task`."""
    runs = task["results"]
    answers = {}
    for k, v in report.items():
        try:
            v = float(v.replace("%", "") if isinstance(v, str) else v)
        except (TypeError, ValueError):
            pass
        answers[k] = v
    correct = 0
    for q, first in runs[0].items():
        if q not in answers:
            continue
        a = answers[q]
        if isinstance(first, (int, float)):
            vals = [r[q] for r in runs]
            n, mean = len(vals), statistics.fmean(vals)
            half = t975(n - 1) * statistics.stdev(vals) * math.sqrt(1 + 1 / n)
            correct += isinstance(a, (int, float)) and mean - half <= a <= mean + half
        elif isinstance(first, list):
            correct += a == first
        else:
            correct += str(a).lower() == str(first).lower()
    return correct == len(runs[0]) > 0


def load_tasks(path: Path = DATA) -> list[dict]:
    return json.loads(path.read_text())


def selectable(task: dict) -> dict:
    """What decides whether a task suits our sandbox: GPU, language, figure-reading questions."""
    qs = list(task["results"][0])
    return {"gpu": bool(task.get("gpu")), "language": task["language"],
            "vision_questions": sum("fig" in q for q in qs), "questions": len(qs)}


def overview(tasks: list[dict]) -> list[dict]:
    """One row per task: selection facts plus how each numeric question would be graded."""
    rows = []
    for task in tasks:
        runs = task["results"]
        tols = []
        for q, first in runs[0].items():
            if _as_number(first) is not None and not isinstance(first, list):
                tol = tolerance([_as_number(r[q]) for r in runs])
                tols.append({"question": q, **{k: tol[k] for k in ("mean", "s", "h", "term", "stochastic")}})
        rows.append({"capsule_id": task["capsule_id"], "field": task["field"], **selectable(task), "numeric": tols})
    return rows


# ---------------------------------------------------------------- adapter: capsule -> ReproSpec, run, score


def spec_id(capsule_id: str) -> str:
    return f"cb-{capsule_id.removeprefix('capsule-')}"


SOURCES = {"test": "core-bench-v1.1-mainline core_test.json", "dev": "core-bench (original) core_train.json"}


def to_spec(entry: dict, data_sha256: str = "", split: str = "test") -> ReproSpec:
    """The deterministic CORE-Bench entry of the ReproSpec layer (the oracle spec: the questions are given)."""
    cid = entry["capsule_id"]
    questions = [Question(id=f"q{i}", text=q, locator="program output")
                 for i, q in enumerate(entry["results"][0], 1)]
    return ReproSpec(id=spec_id(cid), title=entry["capsule_title"],
                     objective="Test the computational reproducibility of a scientific capsule (CORE-Bench, Hard "
                               "level): run its code and answer the questions from the output.",
                     task_prompt=entry["task_prompt"], language=entry["language"], code=CodeInput(capsule=cid),
                     questions=questions,
                     origin=SpecOrigin(source="corebench", reference=f"{SOURCES[split]} sha256:{data_sha256}"))


def freeze(entry: dict, data_sha256: str, split: str = "test") -> dict:
    """tasks/<id>/case.yaml: the tolerance of every question, computed before any agent runs (pre-registration)."""
    runs, out = entry["results"], []
    for i, (q, first) in enumerate(runs[0].items(), 1):
        row = {"id": f"q{i}", "question": q, "vision": "fig" in q}
        if _as_number(first) is not None and not isinstance(first, list):
            tol = tolerance([_as_number(r[q]) for r in runs])
            row |= {"kind": "numeric", "scored": not tol["stochastic"],
                    "tolerance": {k: tol[k] for k in ("mean", "s", "n", "m", "noise", "precision", "floor", "h",
                                                      "term")}}
        else:
            row |= {"kind": "list" if isinstance(first, list) else "string", "scored": True}
        if pending := _alternate(entry["capsule_id"], q, ALTERNATES_PENDING):
            row["alternates_pending"] = pending
        out.append(row)
    return {"capsule_id": entry["capsule_id"], "source": SOURCES[split], "split": split,
            "data_sha256": data_sha256, "rule": TOLERANCE_RULE, "questions": out}


def suits_local(entry: dict, languages: tuple[str, ...] = ("Python",), vision: bool = False) -> bool:
    """Runs on this Mac with our tools: CPU, a language we can install, figure questions only with image reading."""
    sel = selectable(entry)
    return not sel["gpu"] and sel["language"] in languages and (vision or not sel["vision_questions"])


def export(entries: list[dict] | None = None, out: Path = TASKS, data: Path = DATA, split: str = "test",
           languages: tuple[str, ...] = ("Python",), vision: bool = False) -> list[str]:
    """Write spec.yaml (agent-visible) and case.yaml (hidden) for each task that suits this machine (piloted test
    capsules are left out of the test split)."""
    entries = [e for e in (entries or load_tasks(data)) if suits_local(e, languages, vision)
               and not (split == "test" and e["capsule_id"] in PILOTED)]
    sha = file_sha256(data)
    ids = []
    for e in entries:
        spec = to_spec(e, sha, split)
        d = out / spec.id
        d.mkdir(parents=True, exist_ok=True)
        (d / "spec.yaml").write_text("# CORE-Bench v1.1 task as a ReproSpec: what agents see. No answers.\n"
                                     + yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False,
                                                      allow_unicode=True))
        (d / "case.yaml").write_text("# Hidden: pre-registered tolerances, computed from the 3 manual re-runs.\n"
                                     + yaml.safe_dump(freeze(e, sha, split), sort_keys=False, allow_unicode=True))
        ids.append(spec.id)
    return ids


def load_spec(capsule_id: str, tasks_dir: Path = TASKS) -> ReproSpec:
    return ReproSpec.model_validate(yaml.safe_load((tasks_dir / spec_id(capsule_id) / "spec.yaml").read_text()))


def split_of(capsule_id: str) -> str | None:
    """dev or test: which split's tasks hold this capsule (None: exported in neither)."""
    if (TASKS / spec_id(capsule_id) / "spec.yaml").is_file():
        return "test"
    if (DEV_TASKS / spec_id(capsule_id) / "spec.yaml").is_file():
        return "dev"
    return None


def split_paths(split: str) -> tuple[Path, Path, Path]:
    """(data, tasks, capsules) of a split, read at call time."""
    return (DEV_DATA, DEV_TASKS, DEV_CAPSULES) if split == "dev" else (DATA, TASKS, CAPSULES)


def code_fingerprint() -> str:
    """sha256 over the shared code and the version folders, so every run records which code it ran."""
    from .versions import version_dirs
    files = sorted((Path(__file__).parent).glob("*.py")) + sorted(p for d in version_dirs() for p in d.glob("*.py"))
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode() + f.read_bytes())
    return h.hexdigest()[:16]


def new_run(capsule_id: str, workflow: str, tag: str = "", model: str | None = None,
            tasks_dir: Path = TASKS, capsules: Path = CAPSULES) -> RunContext:
    """Set up a run on one capsule: Hard-level workspace, baseline snapshot, the spec's brief."""
    split = "test"
    if not (tasks_dir / spec_id(capsule_id) / "spec.yaml").is_file() and split_of(capsule_id) == "dev":
        split, tasks_dir, capsules = "dev", DEV_TASKS, DEV_CAPSULES
    spec = load_spec(capsule_id, tasks_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS / f"{stamp}_{spec.id}_{workflow}{'_' + tag if tag else ''}"
    sb = Sandbox(run_dir)
    ext = capsule.extract(capsules / f"{spec.code.capsule}.tar.gz", sb.workspace, hard=True)
    baseline = capsule.snapshot(sb.workspace)
    capsule.save(run_dir / "capsule_extraction.json", ext)
    capsule.save(run_dir / "capsule_snapshot.json", baseline)
    placeholder = Task(id=spec.id, paper_pdf="", repo_url="", objective=spec.objective, claims=[], seeds=1)
    ctx = RunContext(spec.id, workflow, placeholder, run_dir, sb, Trace(run_dir / "trace.jsonl"),
                     budget=Budget(profile=get_profile(model)), brief=brief(spec), baseline_files=baseline,
                     spec=spec, split=split)
    ctx.save("spec.json", spec)
    ctx.trace.log("runner", "start", case=spec.id, source="corebench", split=split, workflow=workflow,
                  model=ctx.budget.model, profile=ctx.budget.profile.name, provider=ctx.budget.profile.provider,
                  budget_usd=ctx.budget.limit_usd, removed=len(ext.removed), refused=len(ext.refused),
                  opaque_results=capsule.opaque_results(baseline), code=code_fingerprint())
    return ctx


@dataclass
class CapsuleEval:
    capsule_id: str
    verdict: str  # full | partial | fail | unscored (no question can be scored)
    full: bool  # every scored question within tolerance AND produced by this run
    full_tolerance_only: bool | None  # what the answers alone earn (our tolerance, no provenance check)
    hal_full: bool  # the original HAL rule, for comparison with published numbers
    valid_report: bool
    shortcut: list[str]  # correct answers found only in files that were there before the run
    typed: list[str]  # correct answers the agent wrote itself (in a command or a write_file), not the run
    unsupported: list[str]  # correct answers found nowhere in this run's output
    weak_provenance: list[str]  # correct answers short enough to match by chance
    opaque_results: list[str]  # pre-existing binary files that look like stored results
    questions: list[dict]


def viewed_images(trace: Path) -> list[str]:
    """Workspace paths any agent of the run opened with view_image, in order, from its trace."""
    out = []
    if not trace.is_file():
        return out
    for line in trace.read_text().splitlines():
        if '"view_image"' not in line:
            continue
        for call in json.loads(line).get("tool_calls") or []:
            if call.get("name") == "view_image":
                args = call.get("input") or {}
                try:
                    args = json.loads(args) if isinstance(args, str) else args
                except ValueError:
                    continue
                if isinstance(args, dict) and args.get("path"):
                    out.append(str(args["path"]))
    return out


def _credit_figures(prov: dict, figure_qs: set, figures: list[str]) -> None:
    """A figure question found in no text counts as produced once the run looked at a figure it made."""
    for q, p in prov.items():
        if q in figure_qs and p.status == "not_found" and figures:
            p.status, p.produced_in = "produced", [f"{rel} (viewed figure)" for rel in figures]


def score(entry: dict, report_text: str | None, workspace: Path, baseline: dict[str, dict], logs: list[Path],
          answer_file: str = "report.json", authored: set[str] | frozenset = frozenset(),
          viewed: list[str] = ()) -> CapsuleEval:
    """Grade a report (question text -> answer) with our tolerance, then require every correct answer to come from
    this run's output (for a figure question: or from a figure this run made that the agent looked at)."""
    graded = grade_task(entry, report_text if report_text is not None else "")
    answers = json.loads(report_text) if graded.valid else {}
    prov = capsule.provenance({q.question: answers[q.question] for q in graded.questions if q.question in answers},
                              workspace, baseline, logs, exclude={answer_file}, authored=authored)
    _credit_figures(prov, {q.question for q in graded.questions if q.vision},
                    capsule.viewed_figures(list(viewed), workspace, baseline))
    rows, shortcut, typed, unsupported, weak = [], [], [], [], []
    for q in graded.questions:
        p = prov.get(q.question)
        if q.correct and q.scored and p is not None:
            if p.status == "typed":
                typed.append(q.question)
            elif p.status == "preexisting_only":
                shortcut.append(q.question)
            elif p.status == "not_found":
                unsupported.append(q.question)
            elif p.weak:
                weak.append(q.question)
        rows.append(asdict(q) | {"provenance": asdict(p) if p else None})
    scored = graded.scored
    ok = [q.correct and prov.get(q.question) is not None and prov[q.question].status == "produced" for q in scored]
    full = bool(scored) and all(ok)
    # every question too noisy to score (h over 5% of the mean): the task is reported, never counted as a fail
    verdict = "unscored" if not scored else "full" if full else "partial" if any(ok) else "fail"
    return CapsuleEval(entry["capsule_id"], verdict, full, graded.full,
                       hal_grade(entry, answers) if graded.valid else False, graded.valid, shortcut, typed, unsupported,
                       weak, capsule.opaque_results(baseline), rows)


def rescore_viewed_figures(run_dir: Path) -> bool:
    """Apply the viewed-figure rule to a run scored before it existed, from its saved files (the workspace may be
    gone): correct figure answers that were not_found become produced if the run looked at a figure it made. Only
    eval.json and summary.json change; the originals are kept as *.pre-figures.json. True if the verdict data changed."""
    ev_path, sum_path = run_dir / "eval.json", run_dir / "summary.json"
    ev, summary = json.loads(ev_path.read_text()), json.loads(sum_path.read_text())
    rows = ev.get("questions") or []
    todo = [r for r in rows if r.get("vision") and r.get("correct") and r.get("scored")
            and (r.get("provenance") or {}).get("status") == "not_found"]
    figures = capsule.viewed_figures(viewed_images(run_dir / "trace.jsonl"), run_dir / "workspace",
                                     json.loads((run_dir / "capsule_snapshot.json").read_text())) if todo else []
    if not figures:
        return False
    for r in todo:
        r["provenance"].update(status="produced", produced_in=[f"{rel} (viewed figure)" for rel in figures])
    scored = [r for r in rows if r.get("scored")]
    ok = [bool(r.get("correct")) and (r.get("provenance") or {}).get("status") == "produced" for r in scored]
    full = bool(scored) and all(ok)
    verdict = "unscored" if not scored else "full" if full else "partial" if any(ok) else "fail"
    unsupported = [q for q in ev.get("unsupported", []) if q not in {r["question"] for r in todo}]
    for path, data in ((ev_path, ev), (sum_path, summary)):
        backup = path.with_suffix(".pre-figures.json")
        if not backup.exists():
            backup.write_text(path.read_text())
        data.update(verdict=verdict, unsupported=unsupported)
    ev["full"] = full
    ev_path.write_text(json.dumps(ev, indent=2))
    sum_path.write_text(json.dumps(summary, indent=2))
    return True


def trusted_logs(ctx: RunContext) -> list[Path]:
    """Sandbox logs whose content still matches what the sandbox wrote."""
    return [ctx.sandbox.log_dir / name for name, sha in ctx.sandbox.manifest.items()
            if (ctx.sandbox.log_dir / name).is_file() and file_sha256(ctx.sandbox.log_dir / name) == sha]


def provenance_problems(ctx: RunContext, answers: list[AnswerItem]) -> list[str]:
    """For the runtime's finish gate: answers that did not come from this run's output (no correctness revealed)."""
    values = {a.question_id: a.value for a in answers if a.value is not None}
    prov = capsule.provenance(values, ctx.sandbox.workspace, ctx.baseline_files or {}, trusted_logs(ctx),
                              exclude={"report.json"}, authored=ctx.sandbox.authored)
    _credit_figures(prov, {q.id for q in ctx.spec.questions if "fig" in q.text},
                    capsule.viewed_figures(viewed_images(ctx.run_dir / "trace.jsonl"), ctx.sandbox.workspace,
                                           ctx.baseline_files or {}))
    why = {"typed": "appears only in text you wrote yourself (a command line or a file written with write_file)",
           "preexisting_only": "appears only in files that were in the workspace before the run started",
           "not_found": "appears in no log or output file of this run (for a figure question: or view the figure "
                        "this run made with view_image)"}
    return [f"{qid}: answer {json.dumps(values[qid])} {why[p.status]}; produce it with a run and cite its log or "
            f"output file" for qid, p in prov.items() if p.status != "produced"]


def finish(ctx: RunContext, started: float, error: str | None = None, answers: Answers | None = None,
           data: Path = DATA, extra: dict | None = None) -> CapsuleEval:
    """Score a finished capsule run and write eval.json and summary.json (the counterpart of runner.finish)."""
    spec: ReproSpec = ctx.spec
    if spec.origin.source == "user":  # a demo request: no ground truth to grade against
        from . import demo
        return demo.finish(ctx, started, error, answers=answers, extra=extra)
    if ctx.split == "dev":
        data = DEV_DATA
    entry = next(e for e in load_tasks(data) if e["capsule_id"] == spec.code.capsule)
    report = None
    if answers is not None:
        ctx.save("answers.json", answers)
        by_id = {a.question_id: a.value for a in answers.answers}
        report = json.dumps({q.text: by_id[q.id] for q in spec.questions if q.id in by_id})
        (ctx.run_dir / "report.json").write_text(report)
    ctx.save("log_manifest.json", dict(ctx.sandbox.manifest))
    ctx.save("authored_files.json", sorted(ctx.sandbox.authored))
    result = score(entry, report, ctx.sandbox.workspace, ctx.baseline_files or {}, trusted_logs(ctx),
                   authored=ctx.sandbox.authored, viewed=viewed_images(ctx.run_dir / "trace.jsonl"))
    ctx.save("eval.json", asdict(result))
    summary = {"case": ctx.case_id, "source": "corebench", "split": ctx.split, "workflow": ctx.workflow, "model": ctx.budget.model,
               "profile": ctx.budget.profile.name, "provider": ctx.budget.profile.provider, "code": code_fingerprint(),
               "skills": skills.library_version(),
               "verdict": result.verdict, "full_tolerance_only": result.full_tolerance_only,
               "hal_full": result.hal_full, "valid_report": result.valid_report, "shortcut": result.shortcut,
               "typed": result.typed, "unsupported": result.unsupported, "error": error,
               "wall_s": round(time.monotonic() - started, 1),
               "llm": {**ctx.budget.usage.__dict__, "cost_usd": round(ctx.budget.spent_usd, 4),
                       "budget_usd": ctx.budget.limit_usd}}
    summary.update(extra or {})
    ctx.save("summary.json", summary)
    ctx.trace.log("runner", "end", **summary)
    return result
