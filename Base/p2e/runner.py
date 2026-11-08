"""Shared plumbing for all workflows: run directory, inputs, executor, scoring."""
from __future__ import annotations

import json
import logging
import re
import shutil
import statistics
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

from .capsule import save_shipped_reads
from .evaluator import evaluate
from .llm import Budget, Trace
from .models import get_profile
from .sandbox import MACHINE, PROJECT_ROOT, Sandbox
from .skills import library_version
from .schemas import Case, ClaimMeasurement, DiscrepancyReport, EvalResult, Metrics, RunRecord, RunSpec, Task

# pypdf warns at length about fonts it can't fully decode; text extraction still works.
logging.getLogger("pypdf").setLevel(logging.ERROR)

BENCHMARK = PROJECT_ROOT / "benchmark"
RUNS = PROJECT_ROOT / "runs"


@dataclass
class RunContext:
    case_id: str
    workflow: str
    task: Task
    run_dir: Path
    sandbox: Sandbox
    trace: Trace
    budget: Budget = field(default_factory=Budget)
    # claim id -> pre-registered reproduction criterion (from case.yaml: tolerance, aggregate, seeds; no target)
    criteria: dict[str, str] = field(default_factory=dict)
    # A task brief that replaces the paper-based one (CORE-Bench capsules, see p2e.corebench)
    brief: str | None = None
    # sha256 of every workspace file before the agents start (capsule runs); kept in memory, like the log manifest
    baseline_files: dict[str, dict] | None = None
    # the ReproSpec of a spec-based run (p2e.spec); None for the paper cases, which still use task + case.yaml
    spec: object | None = None
    # dev | test for runs on a split benchmark (CORE-Bench); test-split runs never feed tuning or the skill library
    split: str | None = None

    def save(self, name: str, obj) -> Path:
        path = self.run_dir / name
        data = obj.model_dump() if hasattr(obj, "model_dump") else obj
        path.write_text(json.dumps(data, indent=2, default=str))
        return path

    def task_brief(self) -> str:
        """The task as agents see it: paper location, repo, claims, output contract."""
        if self.brief is not None:
            return self.brief
        claims = "\n".join(f"- `{c.id}` ({c.metric}, {c.setting}, unit {c.unit or 'none'}): {c.description}"
                           + (f"\n  Reproduced if: {self.criteria[c.id]}." if c.id in self.criteria else "")
                           for c in self.task.claims)
        return (
            f"Objective: {self.task.objective}\n\n"
            f"Paper: `paper/paper.pdf` (extracted text: `paper/paper.txt`)\n"
            f"Official repository: {self.task.repo_url} (not cloned yet)\n"
            f"Seeds required per claim: {self.task.seeds}\n\n"
            f"Claims to measure, by id. Each criterion is fixed in advance and is the one the evaluator applies; "
            + ("it names the value it refers to. Where that is the official code's own result, still compare your "
               "values with the paper's and report any gap in the diagnosis"
               if any(REFERENCE_TARGET in c for c in self.criteria.values())
               else "the value it refers to is the one the paper reports") + f":\n{claims}\n\n"
            f"Machine: {MACHINE}, CPU only, no CUDA. `uv` and `git` are available. "
            f"Keep any single experiment run under 20 minutes."
        )


def new_run(case_id: str, workflow: str, tag: str = "", model: str | None = None) -> RunContext:
    case_dir = BENCHMARK / case_id
    task = Task.load(case_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS / f"{stamp}_{case_id}_{workflow}{'_' + tag if tag else ''}"
    sb = Sandbox(run_dir)

    pdf = case_dir / task.paper_pdf
    if not pdf.exists() and task.paper_url:
        pdf.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(task.paper_url, pdf)
    paper_dir = sb.workspace / "paper"
    paper_dir.mkdir(exist_ok=True)
    shutil.copy(pdf, paper_dir / "paper.pdf")
    reader = PdfReader(paper_dir / "paper.pdf")
    pages = [f"=== page {i} ===\n{p.extract_text() or ''}" for i, p in enumerate(reader.pages, 1)]
    (paper_dir / "paper.txt").write_text("\n".join(pages))

    ctx = RunContext(case_id, workflow, task, run_dir, sb, Trace(run_dir / "trace.jsonl"),
                     budget=Budget(profile=get_profile(model)), criteria=_criteria(case_dir, task))
    ctx.save("task.json", task)
    ctx.trace.log("runner", "start", case=case_id, workflow=workflow, model=ctx.budget.model,
                  profile=ctx.budget.profile.name, provider=ctx.budget.profile.provider, budget_usd=ctx.budget.limit_usd)
    return ctx


def _criteria(case_dir: Path, task: Task) -> dict[str, str]:
    """claim id -> the pre-registered reproduction criterion shown to agents (no target value)."""
    case = Case.load(case_dir)
    return {c.id: f"the {case.aggregate} over at least {max(case.min_seeds, task.seeds)} seed runs is "
                  f"{c.tolerance.describe(c.unit, of=REFERENCE_TARGET if c.target == 'reference' else 'the paper value')}"
                  + (f"; one run = {c.run_definition}" if c.run_definition else "")
            for c in case.claims}


REFERENCE_TARGET = ("the result the official code gives on this machine (the benchmark's own re-runs of it; that "
                    "value is not shown)")


def resume_run(run_dir: Path) -> RunContext:
    """The context of an interrupted run, rebuilt from its directory: same task, model profile, logs and workspace
    (which must still exist). The workflow restores its own progress from its checkpoint."""
    run_dir = run_dir.resolve()
    start = next((json.loads(l) for l in (run_dir / "trace.jsonl").read_text().splitlines()
                  if '"agent": "runner"' in l and '"event": "start"' in l), None)
    if start is None:
        raise ValueError(f"{run_dir}: no runner start event in trace.jsonl")
    if (run_dir / "summary.json").exists():
        raise ValueError(f"{run_dir}: already finished (summary.json exists)")
    if (run_dir / "spec.json").exists():
        raise ValueError(f"{run_dir}: spec-based (CORE-Bench) runs cannot be resumed yet")
    task = Task.model_validate_json((run_dir / "task.json").read_text())
    sb = Sandbox(run_dir)
    if not (sb.workspace / "paper" / "paper.txt").exists():
        raise ValueError(f"{run_dir}: workspace is gone ({sb.workspace}); the run cannot resume")
    ctx = RunContext(start["case"], start["workflow"], task, run_dir, sb, Trace(run_dir / "trace.jsonl"),
                     budget=Budget(profile=get_profile(start.get("profile") or start.get("model"))),
                     criteria=_criteria(BENCHMARK / start["case"], task))
    ctx.trace.log("runner", "resume", case=ctx.case_id, workflow=ctx.workflow, profile=ctx.budget.profile.name)
    return ctx


# ---------------------------------------------------------------- deterministic executor


def parse_metric(output: str, regex: str, scale: float = 1.0) -> float | None:
    try:
        matches = re.findall(regex, output)
    except re.error:
        return None
    if not matches:
        return None
    last = matches[-1]
    if isinstance(last, tuple):
        last = next((g for g in last if g), "")
    try:
        return float(last) * scale
    except ValueError:
        return None


def execute(ctx: RunContext, spec: RunSpec) -> RunRecord:
    """Run one planned experiment exactly as specified and parse its metric. No LLM here."""
    res = ctx.sandbox.run(spec.command, spec.workdir, spec.timeout_s, tag=f"exp_{spec.run_id}")
    value = parse_metric(res.output, spec.metric_regex, spec.scale) if res.ok else None
    rec = RunRecord(run_id=spec.run_id, claim_id=spec.claim_id, seed=spec.seed, command=spec.command,
                    workdir=spec.workdir, exit_code=res.exit_code, duration_s=round(res.duration_s, 2),
                    value=value, log_path=str(res.log_path.relative_to(ctx.run_dir)))
    ctx.trace.log("executor", "run", **rec.model_dump())
    return rec


def aggregate(records: list[RunRecord], notes: str = "") -> Metrics:
    by_claim: dict[str, ClaimMeasurement] = {}
    for r in records:
        if r.value is None:
            continue
        m = by_claim.setdefault(r.claim_id, ClaimMeasurement(claim_id=r.claim_id, values=[], evidence=[]))
        m.values.append(r.value)
        m.evidence.append(r.log_path)
    return Metrics(claims=list(by_claim.values()), notes=notes)


# ---------------------------------------------------------------- scoring


def finish(ctx: RunContext, metrics: Metrics, started: float, error: str | None = None,
           extra: dict | None = None) -> EvalResult:
    ctx.save("metrics.json", metrics)
    # All agents are done, so the sandbox's log hashes can go to disk now (written earlier, an agent could edit them).
    manifest = dict(ctx.sandbox.manifest)
    ctx.save("log_manifest.json", manifest)
    if ctx.sandbox.workspace.exists():  # keep what the shortcut check needs, so the workspace can be discarded
        save_shipped_reads(ctx.run_dir, ctx.sandbox.workspace, [ctx.sandbox.log_dir / n for n in manifest])
    result = evaluate(Case.load(BENCHMARK / ctx.case_id), metrics, ctx.run_dir, ctx.workflow,
                      DiscrepancyReport.load(ctx.run_dir), manifest)
    ctx.save("eval.json", result)
    dg = result.diagnosis
    summary = {
        "case": ctx.case_id,
        "workflow": ctx.workflow,
        "model": ctx.budget.model,
        "profile": ctx.budget.profile.name,
        "provider": ctx.budget.profile.provider,
        "skills": library_version(),
        "verdict": result.verdict,
        "error": error,
        "wall_s": round(time.monotonic() - started, 1),
        "llm": {**ctx.budget.usage.__dict__, "cost_usd": round(ctx.budget.spent_usd, 4),
                "budget_usd": ctx.budget.limit_usd},
        "claims": {v.claim_id: {"target": v.target, "aggregate": v.aggregate, "value": v.measured_agg,
                                "mean": v.measured_mean, "std": v.measured_std,
                                "n": v.n_values, "pass": v.within_tolerance and v.evidence_ok, "reason": v.reason,
                                "diagnostic_only": v.diagnostic_only}
                   for v in result.claims},
        "diagnosis": {"present": dg.present, "detection": dg.detection, "n_failing": len(dg.failing),
                      "n_detected": len(dg.detected), "false_success": dg.false_success,
                      "attribution": dg.attribution, "n_attributed": sum(a.scored for a in dg.attributions),
                      "n_attribution_correct": sum(a.scored and a.correct for a in dg.attributions),
                      "strict_attribution": dg.strict_attribution,
                      "n_strict_correct": sum(a.scored and a.strict_correct for a in dg.attributions),
                      "evidence_recall_heuristic": dg.evidence_recall},
    }
    summary.update(extra or {})  # workflow-specific facts, e.g. multi-agent analyst reruns
    ctx.save("summary.json", summary)
    ctx.trace.log("runner", "end", **summary)
    return result


DIAGNOSIS_RULES = """Diagnosis rules (one ClaimDiagnosis per claim):
- Each claim comes with a pre-registered criterion ("Reproduced if: ..."). Apply it to your measured values:
  status=reproduced if they meet it, status=discrepancy if they do not (however small the gap looks), and
  status=not_measured if the claim produced no value. Do not substitute your own idea of "close enough".
- For each discrepancy, write competing hypotheses for the cause and test the cheapest discriminating ones
  first. Run at least one diagnostic experiment per discrepancy, or say in the conclusion why none was
  possible. Record evidence for and against each hypothesis, with the log of the diagnostic run.
- Checklist (general reproduction practice; go through it before concluding):
  1. Does a quantity that needs no training also deviate (a model-based or analytic baseline the paper
     reports, a data statistic)? If so, the cause is in the setup, data or evaluation, not in training.
  2. Has the code changed since the paper? The clone may be shallow: `git fetch --unshallow`, then look at
     commits around and after the paper's date, other branches and the README changelog. If an older
     version exists, a run of it is a strong test. Diff it against the current code and list every change
     that could matter (model, defaults, scripts, data handling); test them separately and together.
     Changes can interact: one change having no effect on its own does not rule out the version.
  3. Do other versions of the paper or its appendix state settings that differ from the code's?
  4. Is the gap constant across settings or seeds (systematic) or does it vary (noise)? Compare it with the
     seed-to-seed spread you measured.
  5. If you can produce the paper's number only by changing something, say exactly what: that change is
     the finding. It is not a fix, and it never goes into the metrics.
- Then pick the most likely root cause as `category`:
  reproducer_error (a mistake in our own setup or commands), paper_code_mismatch (the official code does
  something other than what the paper says), underspecified_paper (the paper omits a detail that changes
  the result), randomness (seed/initialisation variance explains it), environment (library versions,
  hardware, CPU vs GPU), paper_error (the reported number itself looks wrong), unknown.
- Use only the paper, the code and your own runs. NEVER tune hyperparameters away from the paper to make a
  number match; a diagnostic run explains a gap, it does not replace the measurement.
- Be honest: calling a clear miss "reproduced" is the worst possible answer. Set confidence to high only
  when a diagnostic run confirmed the cause.
- Write the `conclusion` of every discrepancy: the cause you settled on, the decisive evidence, and what
  remains uncertain."""


def claim_stats(values: list[float]) -> str:
    if not values:
        return "-"
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return f"{statistics.fmean(values):.4g} ± {std:.2g} (n={len(values)})"
