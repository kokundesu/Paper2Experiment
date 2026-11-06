"""Version A: one ReAct agent with every tool does the whole reproduction and submits the metrics and its diagnosis.

The harness (p2e.llm.Agent) executes its tool calls in the sandbox and records every message, tool call and command
log; nothing checks the run until the evaluator scores it at the end."""
from __future__ import annotations

import time

from pydantic import BaseModel, Field, model_validator

from p2e import corebench
from p2e.llm import Agent, sandbox_tools
from p2e.prompts import RUNTIME_RULES, SETUP_CHECK_RULES
from p2e.runner import DIAGNOSIS_RULES, RunContext, finish
from p2e.schemas import DiscrepancyReport, EvalResult, Metrics
from p2e.spec import Answers

NAME = "single"
DESCRIPTION = "A: one ReAct agent with all tools (harness baseline)"

SYSTEM = f"""You are a research engineer reproducing a result from a paper on a local machine.

You work inside a sandboxed workspace. The paper is in `paper/`. Clone the official repository (full
history: diagnosis may need older versions of the code), set up a
working Python environment with `uv`, fix whatever breaks on a modern environment (keep fixes minimal and
faithful to the paper), and run the experiments the paper used for the requested claims.

Rules:
- Use the paper's experimental setup (data split, hyperparameters, evaluation protocol). If a code default
  differs from the paper, follow the paper and say so in your notes. If the authors' own reproduction command
  or script for this table differs from the paper's text, follow the setup check below.
- Run every experiment with `run_shell`. Each result starts with the name of a full log file, e.g.
  `cmd_012_shell.log`; it lives under `logs/`. The evaluator trusts only these logs: a run's full output
  (training progress and the final metric) must be printed there. Do not redirect it to files or filter it
  with grep/tail/sed; long output is fine, the log keeps all of it. One run per command is easiest to cite.
- Never write or estimate a number yourself. Submit one value per run (per seed), exactly as that run
  printed it, never a mean or other aggregate (the evaluator aggregates), and cite the run logs that print
  them as `logs/<file name>`.
- Report values in the unit the claim asks for (e.g. percent).
- If something cannot be reproduced within the limits, submit what you have and explain in `notes`.

{RUNTIME_RULES}

{SETUP_CHECK_RULES}

When the measurements are done, diagnose them in `diagnosis`. Diagnostic runs are for explaining a gap
only: never put their numbers in `metrics` unless the run follows the paper's setup.
{DIAGNOSIS_RULES}
Finish by calling `submit` with your metrics and diagnosis."""


SYSTEM_SPEC = f"""You are a research engineer testing the computational reproducibility of research code on a local
machine.

You work inside a sandboxed workspace that already holds the authors' code (and data). Set up a working environment
(for Python, `uv venv` and `uv pip install`), fix whatever breaks on a modern environment (keep fixes minimal), run the
code as the task asks, and answer the questions from its results.

Rules:
- Run every command with `run_shell`. Each result starts with the name of a full log file, e.g. `cmd_012_shell.log`;
  it lives under `logs/`. Do not filter a run's output with grep/tail/sed or redirect it away: the log is the evidence.
  Files the program writes (tables, html reports) are evidence too.
- Never type, estimate or compute an answer yourself, and never take one from a file that was in the workspace before
  you started: every answer must be printed or written by a run you made. Cite its log as `logs/<file name>` or the
  output file's workspace path.
- If a question cannot be answered within the limits, leave it out and explain in `notes`.

{RUNTIME_RULES}

Finish by calling `submit` with one answer per question id."""


class Submission(BaseModel):
    """Only `metrics` is scored as numbers (each value must be in a cited log); `diagnosis` is graded separately."""
    metrics: Metrics
    diagnosis: DiscrepancyReport = Field(description="One ClaimDiagnosis per claim")


def submission_for(seeds: int) -> type[Submission]:
    """Submission that sends back claims with fewer values than seed runs: a real run submitted one 3-seed mean
    per claim, which the evaluator then had to fail for too few values."""
    class PerSeedSubmission(Submission):
        @model_validator(mode="after")
        def _one_value_per_seed(self) -> "PerSeedSubmission":
            short = [c.claim_id for c in self.metrics.claims if 0 < len(c.values) < seeds]
            if short:
                raise ValueError(f"{short}: submit one value per seed run ({seeds} required), as each run printed "
                                 f"it, not a mean or other aggregate")
            return self
    PerSeedSubmission.__name__ = "Submission"
    return PerSeedSubmission


def run_spec(ctx: RunContext, max_turns: int) -> corebench.CapsuleEval:
    """A spec run (e.g. a CORE-Bench capsule): answers instead of metrics, no diagnosis."""
    started = time.monotonic()
    agent = Agent("single_agent", SYSTEM_SPEC, sandbox_tools(ctx.sandbox), Answers, ctx.trace, ctx.budget,
                  max_turns=max_turns, max_cost_usd=ctx.budget.limit_usd)
    error, answers = None, None
    try:
        answers = agent.run(ctx.task_brief())
    except Exception as e:  # budget, API or validation failure: still score what we have
        error = f"{type(e).__name__}: {e}"
        ctx.trace.log("single_agent", "error", error=error)
    return corebench.finish(ctx, started, error, answers=answers)


def run(ctx: RunContext, max_turns: int = 80) -> EvalResult:
    if ctx.spec is not None:
        return run_spec(ctx, max_turns)
    started = time.monotonic()
    agent = Agent("single_agent", SYSTEM, sandbox_tools(ctx.sandbox), submission_for(ctx.task.seeds), ctx.trace, ctx.budget,
                  max_turns=max_turns, max_cost_usd=ctx.budget.limit_usd)
    error = None
    try:
        sub: Submission = agent.run(ctx.task_brief())
        metrics = sub.metrics
        ctx.save("discrepancy_report.json", sub.diagnosis)
    except Exception as e:  # budget, API or validation failure: still score what we have
        error = f"{type(e).__name__}: {e}"
        metrics = Metrics(claims=[], notes=error)
        ctx.trace.log("single_agent", "error", error=error)
    return finish(ctx, metrics, started, error)
