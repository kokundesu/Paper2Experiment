"""Objective evaluation: no LLM involved.

A claim passes when (1) its mean (or median, per `rubric.aggregate`) over at least `min_seeds` values is within
the case's tolerance of the paper value and (2) every submitted value can be
found in one of the cited log files (so a workflow cannot just type a number), and
every cited log matches the claim's `evidence_pattern` if the case sets one. When the run's log manifest is
given, every cited log must also be `logs/<name>` written by the sandbox and unchanged since (the agent's
shell can write into logs/, so it could otherwise forge one).

Claims marked `diagnostic_only` (known not to reproduce from the released code) are measured the same way but
left out of the verdict; they count only through the diagnosis.

The run's DiscrepancyReport is graded separately (`diagnose`) and never changes the verdict.
"""
from __future__ import annotations

import math
import re
import statistics
from pathlib import Path, PurePosixPath

from .capsule import saved_shipped, shipped_files, shortcut_read, split_log, typed_lines
from .sandbox import file_sha256
from .schemas import Attribution, Case, ClaimVerdict, DiagnosisScore, DiscrepancyReport, EvalResult, Metrics

_NUM = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")


def _numbers_in(path: Path) -> list[float]:
    try:
        return [float(x) for x in _NUM.findall(path.read_text(errors="replace"))]
    except (OSError, ValueError):
        return []


def _text(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _matches(path: Path, pattern: str) -> bool:
    try:
        return re.search(pattern, path.read_text(errors="replace")) is not None
    except OSError:
        return False


def _appears(value: float, numbers: list[float]) -> bool:
    """True if `value` is printed in the log, allowing a x100 / /100 unit change and rounding."""
    for n in numbers:
        for scaled in (n, n * 100, n / 100):
            if math.isclose(scaled, value, rel_tol=1e-3, abs_tol=1e-9):
                return True
    return False


def _untrusted(ev: str, run_dir: Path, manifest: dict[str, str]) -> str | None:
    """Why a cited log cannot be trusted as sandbox output, or None if it can."""
    parts = PurePosixPath(ev).parts
    if len(parts) != 2 or parts[0] != "logs" or parts[1] not in manifest:
        return "log not written by the sandbox"
    try:
        same = file_sha256(run_dir / ev) == manifest[parts[1]]
    except OSError:
        same = False
    return None if same else "log modified after it was written"


def evaluate(case: Case, metrics: Metrics, run_dir: Path, workflow: str,
             report: DiscrepancyReport | None = None, manifest: dict[str, str] | None = None) -> EvalResult:
    """`manifest` (log name -> sha256, from the run's Sandbox) enables the log integrity check; None skips it
    (manual calibration, runs from before the manifest existed)."""
    submitted = {m.claim_id: m for m in metrics.claims}
    verdicts: list[ClaimVerdict] = []
    # Files the agent's clones shipped with (tracked by git, unchanged): a log that only prints one of them shows the
    # authors' stored result, not a run. Needs the workspace, so only for real runs (manifest given).
    workspace = run_dir / "workspace"
    shipped = {}
    if manifest is not None:  # the live workspace, else the copies saved before it was discarded
        shipped = shipped_files(workspace.resolve()) if workspace.exists() else saved_shipped(run_dir)
    for gt in case.claims:
        m = submitted.get(gt.id)
        if m is None or not m.values:
            verdicts.append(ClaimVerdict(claim_id=gt.id, target=gt.value, measured_mean=None, measured_std=None,
                                         n_values=0, within_tolerance=False, evidence_ok=False,
                                         reason="no measurement submitted", diagnostic_only=gt.diagnostic_only))
            continue
        mean = statistics.fmean(m.values)
        std = statistics.stdev(m.values) if len(m.values) > 1 else 0.0
        agg = statistics.median(m.values) if case.aggregate == "median" else mean
        within = gt.tolerance.accepts(agg, gt.value)
        identical = bool(gt.ref_spread) and len(m.values) > 1 and len(set(m.values)) == 1

        # A value counts only when a cited log both prints it and shows the run itself (evidence_pattern): an extra
        # summary log may be cited, but numbers an agent printed by hand cannot carry a value on their own.
        shortcut = {ev: hits for ev in m.evidence if shipped and (hits := sorted({
            h for v in m.values for h in shortcut_read(_text(run_dir / ev), v, shipped)}))}
        # A log whose command writes a claimed value out itself (echo, a literal in print(...)) shows typing, not a run.
        typed = [ev for ev in m.evidence if any(typed_lines(split_log(_text(run_dir / ev))[0], v) for v in m.values)]
        proving = [ev for ev in m.evidence if ev not in shortcut and ev not in typed
                   and (not gt.evidence_pattern or _matches(run_dir / ev, gt.evidence_pattern))]
        numbers = [n for ev in proving for n in _numbers_in(run_dir / ev)]
        missing = [v for v in m.values if not _appears(v, numbers)]
        untrusted = {} if manifest is None else {ev: r for ev in m.evidence if (r := _untrusted(ev, run_dir, manifest))}
        evidence_ok = bool(m.evidence) and not missing and not untrusted

        reasons = []
        if not within:
            reasons.append(f"{case.aggregate} {agg:.4g} outside tolerance {gt.tolerance.model_dump(exclude_none=True)} of {gt.value}")
        if identical:
            reasons.append(f"the {len(m.values)} values are identical although the official code varies between runs "
                           f"(s = {gt.ref_spread:.3g}): the seeds did not change the run")
        if len(m.values) < case.min_seeds:
            reasons.append(f"only {len(m.values)} values, need {case.min_seeds}")
        if not evidence_ok:
            if not m.evidence:
                reasons.append("no evidence logs cited")
            if missing and typed:
                reasons.append(f"values typed into the command of the cited logs: {typed}")
            if missing and shortcut:
                reasons.append(f"values found only in logs that print files shipped with the repository: "
                               f"{ {ev: hits for ev, hits in shortcut.items()} }")
            elif missing and gt.evidence_pattern:
                reasons.append(f"values not found in a cited log that shows the run /{gt.evidence_pattern}/: {missing}")
            elif missing:
                reasons.append(f"values not found in cited logs: {missing}")
            for why in dict.fromkeys(untrusted.values()):
                reasons.append(f"{why}: {[ev for ev, r in untrusted.items() if r == why]}")
        verdicts.append(ClaimVerdict(claim_id=gt.id, target=gt.value, aggregate=case.aggregate, measured_agg=agg,
                                     measured_mean=mean, measured_std=std,
                                     n_values=len(m.values),
                                     within_tolerance=within and len(m.values) >= case.min_seeds and not identical,
                                     evidence_ok=evidence_ok, reason="; ".join(reasons),
                                     diagnostic_only=gt.diagnostic_only, agg_within=within))

    passed = [v.within_tolerance and v.evidence_ok for v in verdicts if not v.diagnostic_only]
    verdict = "full" if all(passed) else "partial" if any(passed) else "fail"
    return EvalResult(case_id=case.id, workflow=workflow, verdict=verdict, claims=verdicts,
                      diagnosis=diagnose(case, verdicts, report))


_WORD = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
_STOP = {"that", "this", "with", "from", "were", "when", "than", "then", "they", "their", "which", "while",
         "does", "only", "into", "also", "each", "same", "used", "uses", "have", "been", "paper", "code"}


def _keywords(text: str) -> set[str]:
    # "learning-rate" yields itself and its parts, so it matches "learning rate"; "1e-3" stays whole too
    words = {p for w in _WORD.findall(text.lower()) for p in (w, *re.split(r"[._-]", w))}
    return {w for w in words if w not in _STOP and (len(w) >= 4 or (len(w) >= 2 and any(c.isdigit() for c in w)))}


def _evidence_hit(item: str, agent_words: set[str]) -> bool:
    """Heuristic: at least half of the item's keywords occur in the agent's text."""
    kw = _keywords(item)
    return bool(kw) and len(kw & agent_words) >= len(kw) / 2


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _decisive_hit(any_of: list[str], agent_text: str) -> bool:
    """Plain substring match (no regex) of any phrase in the normalised agent text."""
    return any(_norm(p) in agent_text for p in any_of)


def diagnose(case: Case, verdicts: list[ClaimVerdict], report: DiscrepancyReport | None) -> DiagnosisScore:
    # A diagnosis is about matching the paper, so "failing" means a numerical miss: no value, or an aggregate
    # outside tolerance. Too few seeds or missing evidence already cost the verdict and say nothing about whether
    # the result matches the paper, so they do not count here (they made correct claims look like false successes).
    failing = [v for v in verdicts if v.n_values == 0 or not v.agg_within]
    failing_ids = {v.claim_id for v in failing}
    scored_gt = [d for d in case.discrepancies if d.confidence != "unresolved" and d.claim_id in failing_ids]
    if report is None:
        return DiagnosisScore(present=False, note="no diagnosis", failing=sorted(failing_ids),
                              detection=0.0 if failing else None, attribution=0.0 if scored_gt else None,
                              strict_attribution=0.0 if scored_gt else None,
                              evidence_recall=0.0 if any(d.key_evidence for d in scored_gt) else None)

    diag = {}
    for d in report.claims:
        diag.setdefault(d.claim_id, d)  # first diagnosis per claim counts
    detected, false_success = [], []
    for v in failing:
        d = diag.get(v.claim_id)
        if d is None:
            continue
        # With no value at all, saying "not measured" is the honest flag; with values it would hide a miss.
        if d.status == "discrepancy" or (d.status == "not_measured" and v.n_values == 0):
            detected.append(v.claim_id)
        elif d.status == "reproduced":
            false_success.append(v.claim_id)
    false_alarm = [v.claim_id for v in verdicts
                   if v.claim_id not in failing_ids and v.claim_id in diag and diag[v.claim_id].status == "discrepancy"]

    attributions = []
    for gt in case.discrepancies:
        d = diag.get(gt.claim_id)
        got = d.category if d else None
        expected = [gt.category, *gt.also_acceptable]
        text = " ".join([d.conclusion, *(f"{h.hypothesis} {h.evidence_for} {h.evidence_against}"
                                         for h in d.hypotheses)]) if d else ""
        words, norm = _keywords(text), _norm(text)
        correct = got in expected
        decisive_hits = sum(_decisive_hit(e.any_of, norm) for e in gt.decisive_evidence)
        attributions.append(Attribution(
            claim_id=gt.claim_id, expected=expected, got=got, gt_confidence=gt.confidence,
            scored=gt in scored_gt, correct=correct,
            evidence_hits=sum(_evidence_hit(k, words) for k in gt.key_evidence), evidence_total=len(gt.key_evidence),
            decisive_hits=decisive_hits, decisive_total=len(gt.decisive_evidence),
            strict_correct=correct and (not gt.decisive_evidence or decisive_hits > 0)))
    scored = [a for a in attributions if a.scored]
    ev_total = sum(a.evidence_total for a in scored)
    return DiagnosisScore(
        present=True, failing=sorted(failing_ids), detected=detected, false_success=false_success,
        false_alarm=false_alarm, detection=len(detected) / len(failing) if failing else None,
        attribution=sum(a.correct for a in scored) / len(scored) if scored else None,
        strict_attribution=sum(a.strict_correct for a in scored) / len(scored) if scored else None,
        attributions=attributions,
        evidence_recall=sum(a.evidence_hits for a in scored) / ev_total if ev_total else None)
