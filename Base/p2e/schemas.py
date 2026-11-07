"""Data contracts passed between workflow stages.

Everything an agent produces is one of these models, so every stage boundary
is validated and serialised into the run directory as evidence.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------- benchmark


class ClaimSpec(BaseModel):
    """A number the workflow must measure (visible to agents, no target value)."""
    id: str
    metric: str
    setting: str
    unit: str = ""
    description: str


class Task(BaseModel):
    """benchmark/<case>/task.yaml: the only benchmark file agents see."""
    id: str
    paper_pdf: str
    paper_url: str | None = None  # where to fetch the PDF if it is missing (PDFs are not committed)
    repo_url: str
    objective: str
    claims: list[ClaimSpec]
    seeds: int = 3

    @classmethod
    def load(cls, case_dir: Path) -> "Task":
        return cls.model_validate(yaml.safe_load((case_dir / "task.yaml").read_text()))


class Tolerance(BaseModel):
    abs: float | None = None
    rel: float | None = None
    factor: float | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "Tolerance":
        if sum(v is not None for v in (self.abs, self.rel, self.factor)) != 1:
            raise ValueError("tolerance needs exactly one of abs / rel / factor")
        return self

    def accepts(self, measured: float, target: float) -> bool:
        eps = 1e-9 * max(abs(target), 1e-12)  # don't fail on float noise exactly at the boundary
        if self.abs is not None:
            return abs(measured - target) <= self.abs + eps
        if self.rel is not None:
            return abs(measured - target) <= self.rel * abs(target) + eps
        return target / self.factor - eps <= measured <= target * self.factor + eps

    def describe(self, unit: str = "", of: str = "the paper value") -> str:
        """The criterion in words, for the pre-registered task brief (no target value)."""
        if self.abs is not None:
            # "±0.5 %" reads like a relative tolerance; for accuracies in % it is percentage points
            span = f"{self.abs:g} percentage points" if unit == "%" else f"{self.abs:g}{(' ' + unit) if unit else ''}"
            return f"within ±{span} (absolute) of {of}"
        if self.rel is not None:
            return f"within ±{self.rel * 100:g}% (relative) of {of}"
        return f"within a factor of {self.factor:g} of {of}"


class GroundTruthClaim(BaseModel):
    id: str
    metric: str
    setting: str
    unit: str = ""
    value: float
    tolerance: Tolerance
    # paper: `value` is the paper's number. reference: `value` is the official code's mean over the benchmark's
    # reference re-runs on this machine (v4, see p2e.reference); the paper value is kept apart.
    target: Literal["paper", "reference"] = "paper"
    paper_value: float | None = None
    # standard deviation of the reference re-runs: when the official code varies between runs, identical submitted
    # values mean the seeds did not change the run, and the runs do not count as independent
    ref_spread: float | None = None
    # what one submitted value is (e.g. the mean over the paper's 10 random splits); shown in the criterion line
    run_definition: str = ""
    # Regex every cited log must match, e.g. proof that training ran (not just a shipped checkpoint).
    evidence_pattern: str | None = None
    # Known not to reproduce from the released code: scored only through the diagnosis, never in the verdict.
    # Agents are not told which claims these are (task.yaml lists every claim the same way).
    diagnostic_only: bool = False


RootCause = Literal["reproducer_error", "paper_code_mismatch", "underspecified_paper", "randomness",
                    "environment", "paper_error", "unknown"]


class DecisiveEvidence(BaseModel):
    """A fact that separates the right explanation from a lucky category; hit when any phrase occurs in the
    agent's diagnosis text (case-insensitive plain substring, whitespace collapsed)."""
    fact: str
    any_of: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _no_blank_phrase(self) -> "DecisiveEvidence":
        if any(not p.strip() for p in self.any_of):
            raise ValueError("any_of phrases must be non-empty (an empty phrase would match everything)")
        return self


class GroundTruthDiscrepancy(BaseModel):
    """Why a faithful reproduction of a claim misses the paper value, as established by the human reproduction."""
    claim_id: str
    category: RootCause
    also_acceptable: list[RootCause] = Field(default_factory=list)
    summary: str
    key_evidence: list[str] = Field(default_factory=list)
    # Strict attribution: a right category counts only if at least one of these is hit (when any are given).
    decisive_evidence: list[DecisiveEvidence] = Field(default_factory=list)
    confirmed_by: str = ""
    confidence: Literal["confirmed", "likely", "unresolved"]  # unresolved: reported, not scored


class Case(BaseModel):
    """benchmark/<case>/case.yaml: hidden ground truth, read only by the evaluator."""
    model_config = {"extra": "allow"}
    id: str
    claims: list[GroundTruthClaim]
    rubric: dict = Field(default_factory=dict)
    discrepancies: list[GroundTruthDiscrepancy] = Field(default_factory=list)

    @model_validator(mode="after")
    def _discrepancy_claims_exist(self) -> "Case":
        ids = {c.id for c in self.claims}
        if unknown := [d.claim_id for d in self.discrepancies if d.claim_id not in ids]:
            raise ValueError(f"discrepancies refer to unknown claim ids: {unknown}")
        if all(c.diagnostic_only for c in self.claims):
            raise ValueError("at least one claim must count toward the verdict (not diagnostic_only)")
        explained = {d.claim_id for d in self.discrepancies}
        if unexplained := [c.id for c in self.claims if c.diagnostic_only and c.id not in explained]:
            raise ValueError(f"diagnostic_only claims need a discrepancies entry: {unexplained}")
        return self

    @classmethod
    def load(cls, case_dir: Path) -> "Case":
        return cls.model_validate(yaml.safe_load((case_dir / "case.yaml").read_text()))

    @property
    def min_seeds(self) -> int:
        return int(self.rubric.get("min_seeds", 1))

    @property
    def aggregate(self) -> Literal["mean", "median"]:
        agg = self.rubric.get("aggregate", "mean")
        if agg not in ("mean", "median"):
            raise ValueError(f"rubric.aggregate must be mean or median, got {agg!r}")
        return agg


# ---------------------------------------------------------------- agent outputs


class Hyperparameter(BaseModel):
    name: str
    value: str
    source: str = Field(description="Where it was found, e.g. 'Sec 5.2' or 'train.py default'")


class ClaimProtocol(BaseModel):
    claim_id: str
    paper_value: float | None = Field(None, description="Value the paper reports for this claim, if stated")
    paper_location: str = Field("", description="Table/figure/section that reports it")
    protocol: str = Field(description="How the paper measures it: data split, training procedure, evaluation")


class PaperSpec(BaseModel):
    """Paper Analyst output."""
    summary: str
    hyperparameters: list[Hyperparameter]
    claims: list[ClaimProtocol]
    pitfalls: list[str] = Field(default_factory=list, description="Details easy to get wrong when reproducing")


class EnvReport(BaseModel):
    """Repo/Env Agent output."""
    repo_dir: str = Field(description="Repository path relative to the workspace")
    python: str = Field(description="Interpreter to run experiments with, relative to the workspace")
    entrypoint: str = Field(description="Main script relative to the workspace")
    setup_log: list[str] = Field(description="Commands that set up the environment, in order")
    patches: list[str] = Field(default_factory=list, description="One line per source change made and why")
    smoke_test: str = Field(description="Command that was run to check the code starts, and its outcome")
    ok: bool


class RunSpec(BaseModel):
    run_id: str
    claim_id: str
    seed: int
    command: str = Field(description="Shell command, run from `workdir`")
    workdir: str = Field(".", description="Directory relative to the workspace")
    timeout_s: int = 1200
    metric_regex: str = Field(description="Python regex with ONE capture group matching the metric in stdout; last match is used")
    scale: float = Field(1.0, description="Multiply the parsed value by this to get the claim's unit, e.g. 100 for 0.815 -> 81.5%")


class ExperimentPlan(BaseModel):
    """Planner output: everything the deterministic executor needs."""
    rationale: str
    runs: list[RunSpec]


class Hypothesis(BaseModel):
    hypothesis: str
    evidence_for: str = ""
    evidence_against: str = ""
    diagnostic_log: str | None = Field(None, description="Log of the diagnostic run that tested it, e.g. logs/cmd_031_shell.log")


class ClaimDiagnosis(BaseModel):
    claim_id: str
    paper_value: float | None = Field(None, description="Value the paper reports for this claim")
    measured: float | None = Field(None, description="Your mean/median of the measured values; informational, never scored")
    status: Literal["reproduced", "discrepancy", "not_measured"]
    category: RootCause | None = Field(None, description="Most likely root cause; required for status=discrepancy, else null")
    hypotheses: list[Hypothesis] = Field(default_factory=list, description="Competing explanations and how each was tested")
    conclusion: str = ""
    confidence: Literal["high", "medium", "low"]

    @model_validator(mode="after")
    def _category_iff_discrepancy(self) -> "ClaimDiagnosis":
        if (self.status == "discrepancy") != (self.category is not None):
            raise ValueError("category is required when status is discrepancy and must be null otherwise")
        if self.status == "discrepancy" and not self.conclusion.strip():
            raise ValueError("conclusion is required when status is discrepancy: state the root cause and why")
        return self


class DiscrepancyReport(BaseModel):
    """Discrepancy Analyst (or single agent) output: one diagnosis per claim, saved as discrepancy_report.json."""
    claims: list[ClaimDiagnosis]
    summary: str = ""

    @classmethod
    def load(cls, run_dir: Path) -> "DiscrepancyReport | None":
        """None when the run wrote no (valid) report; the evaluator then scores 'no diagnosis'."""
        path = run_dir / "discrepancy_report.json"
        try:
            return cls.model_validate_json(path.read_text())
        except (OSError, ValueError):
            return None


# ---------------------------------------------------------------- execution and evaluation


class RunRecord(BaseModel):
    run_id: str
    claim_id: str
    seed: int
    command: str
    workdir: str
    exit_code: int | None
    duration_s: float
    value: float | None
    log_path: str
    attempts: int = 1
    debug_notes: list[str] = Field(default_factory=list)


class ClaimMeasurement(BaseModel):
    claim_id: str
    values: list[float] = Field(description="One value per experiment run (one per seed), as printed in its log; "
                                            "never a mean, median or other aggregate")
    evidence: list[str] = Field(description="Log files (relative to the run dir) of the runs that printed each value")


class Metrics(BaseModel):
    """What a workflow submits. The evaluator checks it against case.yaml."""
    claims: list[ClaimMeasurement]
    notes: str = ""


class ClaimVerdict(BaseModel):
    claim_id: str
    target: float
    aggregate: Literal["mean", "median"] = "mean"
    measured_agg: float | None = Field(None, description="Mean or median over seeds, per the case rubric; this is what is compared")
    measured_mean: float | None
    measured_std: float | None
    n_values: int
    within_tolerance: bool
    evidence_ok: bool
    reason: str = ""
    diagnostic_only: bool = False  # excluded from the verdict, still graded by the diagnosis
    # The aggregate alone is within tolerance (ignores the seed count and the evidence). The diagnosis compares
    # against the paper, so it uses this, not within_tolerance.
    agg_within: bool | None = None


class Attribution(BaseModel):
    claim_id: str
    expected: list[RootCause] = Field(description="Ground-truth category followed by also_acceptable")
    got: RootCause | None
    gt_confidence: Literal["confirmed", "likely", "unresolved"]
    scored: bool = Field(description="False for unresolved entries and for claims that passed in this run")
    correct: bool
    evidence_hits: int = 0
    evidence_total: int = 0
    decisive_hits: int = 0
    decisive_total: int = 0
    strict_correct: bool = Field(False, description="correct, and at least one decisive_evidence item hit (if any)")


class DiagnosisScore(BaseModel):
    """How well the run explained its own misses; computed without an LLM. Rates are None when nothing applies."""
    present: bool
    note: str = ""
    failing: list[str] = Field(default_factory=list, description="Claims that did not pass the verdict")
    detected: list[str] = Field(default_factory=list, description="Failing claims flagged discrepancy/not_measured")
    false_success: list[str] = Field(default_factory=list, description="Failing claims the agent called reproduced")
    false_alarm: list[str] = Field(default_factory=list, description="Passing claims the agent called a discrepancy")
    detection: float | None = None
    attribution: float | None = None
    strict_attribution: float | None = Field(None, description="like attribution, but a right category also needs "
                                                               "a decisive_evidence hit when the case lists any")
    attributions: list[Attribution] = Field(default_factory=list)
    evidence_recall: float | None = Field(None, description="HEURISTIC: share of key_evidence items whose keywords "
                                                            "mostly appear in the agent's hypotheses/conclusion")


class EvalResult(BaseModel):
    case_id: str
    workflow: str
    verdict: Literal["full", "partial", "fail"]
    claims: list[ClaimVerdict]
    diagnosis: DiagnosisScore | None = None
