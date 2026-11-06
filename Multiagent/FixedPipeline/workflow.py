"""Version B: fixed multi-agent pipeline, role separation and a deterministic executor, as a LangGraph StateGraph.

    paper_analyst  (read-only)      -> PaperSpec
    env_agent      (shell)          -> EnvReport                (not ok -> stop)
    planner        (read-only)      -> ExperimentPlan, pilots first
    executor       (no LLM)         -> runs one RunSpec per step, parses the metric from its log
      -> debugger  (shell, bounded) -> revised RunSpecs when a run fails or prints no metric
      -> result_reviewer (shell, once, after one pilot per claim) -> fixes setup errors, never tunes
    discrepancy_analyst (read-only + shell) -> DiscrepancyReport; may request ONE rerun for setup errors
      -> executor (the rerun replaces those claims' measurements) -> discrepancy_analyst again
    finalize       (no LLM)         -> metrics; the evaluator scores the run against hidden ground truth

Spec runs (a ReproSpec such as a CORE-Bench capsule, ctx.spec set) use the same fixed shape with roles fitted to a
list of questions about code that is already in the workspace (SpecPipeline below):

    env_agent      (shell)          -> EnvReport for the code in place (not ok -> answerer, which reports what it can)
    planner        (read-only)      -> SpecPlan: the commands that produce the outputs the questions ask about
    executor       (no LLM)         -> runs one command per step; its full output is a log
      -> debugger  (shell, bounded) -> revised commands when a run exits non-zero
    answerer       (shell, no write)-> Answers read from the logs and output files; may hand commands back ONCE
    finalize       (no LLM)         -> p2e.corebench scores the answers (tolerance + provenance)

Numbers only ever come from the executor's logs, never from an LLM's text. The analyst's own diagnostic runs never
count; only RunSpecs it hands back for a justified setup error are executed, once, and the run records that it
happened. Each node's update is checkpointed (SQLite next to the workspace), so an interrupted run can resume.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from p2e import corebench
from p2e.llm import REVIEW_EFFORT, Agent, BudgetExceeded, Usage, sandbox_tools
from p2e.prompts import RUNTIME_RULES, SETUP_CHECK_RULES
from p2e.runner import DIAGNOSIS_RULES, RunContext, aggregate, execute, finish
from p2e.schemas import DiscrepancyReport, EnvReport, EvalResult, ExperimentPlan, PaperSpec, RunRecord, RunSpec
from p2e.spec import Answers

NAME = "fixed"
DESCRIPTION = "B: fixed six-role pipeline routed by code (v3.1)"
RESUMABLE = True

MAX_ANALYST_RERUNS = 1

ANALYST = """You are the Paper Analyst in a team reproducing a paper. Read `paper/paper.txt` (and the PDF
text page markers) and extract, for the requested claims only: the value the paper reports and where,
the exact evaluation protocol (dataset, split, number of runs/seeds, what is averaged), and every
hyperparameter needed to run it, each with its source. List pitfalls a reproducer could easily get wrong.
Do not guess: write "not stated" when the paper does not say. Submit a PaperSpec."""

ENV = f"""You are the Repo/Environment Engineer in a team reproducing a paper. In the workspace:
1. `git clone <repo> repo` (full history: later diagnosis may need older versions of the code).
2. Read the README and code; find the script that produces the requested claims.
3. Create a Python environment with `uv venv` (e.g. `uv venv --python 3.11 .venv`) and install what the
   code needs. Pinned old versions often do not exist for this machine (Apple Silicon, CPU only):
   prefer the closest working modern versions and the libraries' own compatibility layers over
   rewriting the code.
4. Make the entrypoint runnable and make sure each claim's setting and the random seed can be chosen
   from the command line or an environment variable. Patch minimally and list every patch.
5. Smoke-test: start a short run (few iterations if the script allows) and confirm it gets past setup.
   Measure the time per iteration/epoch and report the projected time of one full-length run in
   `smoke_test`, so the planner does not have to guess.
{RUNTIME_RULES}
Do not run the full experiments; that is someone else's job. Submit an EnvReport."""

PLANNER = """You are the Experiment Planner in a team reproducing a paper. Using the PaperSpec and the
EnvReport, write the exact list of runs: one RunSpec per (claim, seed), using the paper's hyperparameters.
If the authors' own reproduction command or script for this table (README, scripts/...) disagrees with the
paper's text, use the official command and record the conflict in `rationale`; a plain code default that no
reproduction command sets does not override the paper.
You can read the code to get flags and the printed output format right.
- `command` runs from `workdir` (relative to the workspace) with the EnvReport's python interpreter.
- `metric_regex` is a Python regex with ONE capture group for the number the script prints for this
  claim; the executor takes the last match in the combined stdout/stderr.
- `scale` converts it to the claim's unit (e.g. 100 if the script prints 0.815 and the claim is in %).
- Keep each run under 20 minutes on CPU. Scale the paper's setting down only if the EnvReport's measured
  timing projects a full run above that limit; write the estimate and the deviation in `rationale`.
- The command must print its full output (training progress and the final metric) to stdout/stderr: the
  run's log is the only evidence the evaluator accepts. Never redirect it to files or filter it with
  grep/tail/sed.
Submit an ExperimentPlan."""

DEBUGGER = """You are the Debugger in a team reproducing a paper. A planned run failed or printed no
parsable metric. Diagnose from the log, inspect and fix the code or environment with minimal, faithful
changes, verify your fix with a short run if possible, and return revised RunSpecs for the failed run and
all remaining runs (fix the command, workdir, regex or scale as needed; keep run_id, claim_id and seed).
Do not change hyperparameters away from the paper to make numbers look better. If the problem cannot be
fixed, set give_up=true and explain. Revised commands must print their full output (training progress and
the final metric) to stdout/stderr, never redirected to files or filtered: the log is the evidence.
Submit a DebugFix."""




ANALYST_DISCREPANCY = f"""You are the Discrepancy Analyst in a team reproducing a paper. The planned experiments are
done: their numbers come only from the executor's logs, and nothing you run yourself changes them.
Your job is to explain, claim by claim, whether the measured values match the paper and, if not, why.
You can read the paper, the code and every log, and run cheap diagnostic experiments with `run_shell`
(keep each one short; prefer runs of seconds to minutes).

{DIAGNOSIS_RULES}

Rerun for a setup error (at most once per run, and only when the brief says it is still available): if a
claim's measurements are invalid because the runs did not follow the paper, judged by the setup check below,
you may hand corrected runs back to the executor instead of only reporting the gap. List each error with the
paper section or code location that justifies the fix in `setup_errors`, the affected claim ids in
`rerun_claims`, and in `revised_runs` the complete runs for those claims (every seed; keep run_id, claim_id and
seed). The executor runs them, their values replace those claims' measurements, and you then write the final
report. Never request a rerun to tune hyperparameters or seeds, to get closer to the paper's number, or for a
gap that remains under a faithful setup: that gap is your finding.

{SETUP_CHECK_RULES}
Submit a DiscrepancyReport (with empty rerun fields unless you request a rerun)."""


REVIEWER = f"""You are the Result Reviewer in a team reproducing a paper. One pilot run per claim has
finished. Before the remaining seeds run, compare each pilot value with the value the paper reports and
look for setup errors. You can read the paper, the code and the logs, and run short checks with
`run_shell` (e.g. a quantity that needs no training, or a timed short run).

{SETUP_CHECK_RULES}

If the setup is faithful, return no revised runs, even when values differ from the paper: those gaps go to
the Discrepancy Analyst. If you fix setup errors, list each with its justification in `setup_errors`, put
the claim ids whose pilot must be repeated in `rerun_claims`, and return `revised_runs`: the complete list
of runs still to execute (repeated pilots and all remaining seeds; keep run_id, claim_id and seed).
Submit a ReviewDecision."""


class ReviewDecision(BaseModel):
    assessment: str = Field(description="Pilot value vs paper value per claim, and whether the setup is faithful")
    setup_errors: list[str] = Field(default_factory=list,
                                    description="Each error found, with the paper section or code location that justifies the fix")
    rerun_claims: list[str] = Field(default_factory=list, description="Claims whose pilot run is invalid and must run again")
    revised_runs: list[RunSpec] = Field(default_factory=list,
                                        description="Empty to proceed unchanged; otherwise every run still to execute")


class DebugFix(BaseModel):
    diagnosis: str
    changes: list[str] = Field(description="Code/env changes made, one per line")
    revised_runs: list[RunSpec] = Field(description="Replacement for the failed run and every remaining run")
    give_up: bool = False


class AnalystDecision(DiscrepancyReport):
    """The Discrepancy Analyst's submission: the report, plus an optional rerun request for setup errors."""
    setup_errors: list[str] = Field(default_factory=list,
                                    description="Only with a rerun request: each setup error, with the paper section or code location that justifies the fix")
    rerun_claims: list[str] = Field(default_factory=list, description="Only with a rerun request: the claims whose measurements are invalid")
    revised_runs: list[RunSpec] = Field(default_factory=list,
                                        description="Only with a rerun request: every run (all seeds) for the rerun claims")

    def report(self) -> DiscrepancyReport:
        return DiscrepancyReport(claims=self.claims, summary=self.summary)


def _measurements(records: list[RunRecord]) -> str:
    by_claim: dict[str, list[dict]] = {}
    for r in records:
        by_claim.setdefault(r.claim_id, []).append(
            {"run_id": r.run_id, "seed": r.seed, "value": r.value, "exit_code": r.exit_code, "log": r.log_path,
             **({"debug_notes": r.debug_notes} if r.debug_notes else {})})
    return json.dumps(by_claim, indent=1)


class MultiState(TypedDict, total=False):
    """Everything the graph carries between nodes, as plain data so every step can be checkpointed."""
    spec: dict | None  # PaperSpec
    env: dict | None  # EnvReport
    plan: dict | None  # ExperimentPlan
    pending: list[dict]  # RunSpecs still to execute, in order
    records: list[dict]  # RunRecords that count (failed runs the debugger gave up on included)
    failed: dict | None  # {"spec", "record"}: a run without a metric, waiting for the debugger
    n_pilots: int
    reviewed: bool
    debug_sessions: int
    reruns: int  # analyst rerun requests carried out (spec runs: answerer hand-backs)
    answers: dict | None  # spec runs: the answerer's Answers
    rerun_pending: bool  # the analyst just handed runs back to the executor
    history: list[str]
    error: str | None
    # for resuming: the sandbox's log hashes, the run's LLM usage and its wall time so far
    manifest: dict
    usage: dict
    elapsed_s: float


class MultiAgentWorkflow:
    def __init__(self, ctx: RunContext, max_debug_sessions: int = 4):
        self.ctx = ctx
        self.max_debug_sessions = max_debug_sessions
        self.cap = ctx.budget.limit_usd  # per-role caps below are shares of the shared run budget
        self.brief = ctx.task_brief()
        self._t0 = time.monotonic()
        self._elapsed_before = 0.0  # wall time of earlier sessions of a resumed run

    # ---- helpers

    def _agent(self, name: str, system: str, tools, out, **kw) -> Agent:
        return Agent(name, system, tools, out, self.ctx.trace, self.ctx.budget, **kw)

    def _budget_spent(self) -> bool:
        b = self.ctx.budget
        return b.spent_usd >= b.limit_usd - b.reserve_usd

    def _carry(self) -> dict:
        return {"manifest": dict(self.ctx.sandbox.manifest), "usage": dict(self.ctx.budget.usage.__dict__),
                "elapsed_s": self._elapsed_before + time.monotonic() - self._t0}

    def _guarded(self, fn):
        """Budget, API or validation failures stop the pipeline but not the run: record the error and let the
        routing send the run to the analyst (if anything was planned) and then to scoring."""
        def node(state: MultiState) -> dict:
            try:
                update = fn(state)
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                self.ctx.trace.log("multi_agent", "error", error=error)
                update = {"error": error}
            return {**update, **self._carry()}
        node.__name__ = fn.__name__
        return node

    def _context(self, state: MultiState, *keys: str) -> str:
        names = {"spec": "PaperSpec", "env": "EnvReport", "plan": "ExperimentPlan"}
        return "".join(f"\n\n{names[k]}:\n{json.dumps(state[k], indent=1)}" for k in keys if state.get(k))

    # ---- nodes

    def paper_analyst(self, state: MultiState) -> dict:
        spec: PaperSpec = self._agent("paper_analyst", ANALYST, sandbox_tools(self.ctx.sandbox, shell=False, write=False),
                                      PaperSpec, max_turns=20, max_cost_usd=0.15 * self.cap).run(self.brief)
        self.ctx.save("paper_spec.json", spec)
        return {"spec": spec.model_dump(mode="json")}

    def env_agent(self, state: MultiState) -> dict:
        env: EnvReport = self._agent("env_agent", ENV, sandbox_tools(self.ctx.sandbox), EnvReport, max_turns=50,
                                     max_cost_usd=0.4 * self.cap).run(
            f"{self.brief}\n\nPaperSpec from the analyst:\n{json.dumps(state['spec'], indent=1)}")
        self.ctx.save("env_report.json", env)
        if not env.ok:
            raise BudgetExceeded(f"environment not ready: {env.smoke_test}")
        return {"env": env.model_dump(mode="json")}

    def planner(self, state: MultiState) -> dict:
        plan: ExperimentPlan = self._agent("planner", PLANNER, sandbox_tools(self.ctx.sandbox, shell=False, write=False),
                                           ExperimentPlan, max_turns=20, max_cost_usd=0.15 * self.cap).run(
            self.brief + self._context(state, "spec", "env"))
        self.ctx.save("plan.json", plan)
        # One pilot run per claim goes first, so the reviewer can catch setup errors before every seed runs.
        pilots = list({r.claim_id: r for r in reversed(plan.runs)}.values())[::-1]
        pending = pilots + [r for r in plan.runs if all(r is not q for q in pilots)]
        return {"plan": plan.model_dump(mode="json"), "pending": [r.model_dump(mode="json") for r in pending],
                "n_pilots": len(pilots), "records": [], "reviewed": False, "debug_sessions": 0}

    def executor(self, state: MultiState) -> dict:
        pending = list(state["pending"])
        spec = RunSpec.model_validate(pending.pop(0))
        rec = execute(self.ctx, spec)
        update: dict = {"pending": pending, "rerun_pending": False}
        if rec.value is None and state.get("debug_sessions", 0) < self.max_debug_sessions and not self._budget_spent():
            update["failed"] = {"spec": spec.model_dump(mode="json"), "record": rec.model_dump(mode="json")}
        else:
            update["records"] = [*state.get("records", []), rec.model_dump(mode="json")]
        return update

    def debugger(self, state: MultiState) -> dict:
        session = state.get("debug_sessions", 0) + 1
        spec, rec = RunSpec.model_validate(state["failed"]["spec"]), RunRecord.model_validate(state["failed"]["record"])
        history = list(state.get("history", []))
        log_tail = (self.ctx.run_dir / rec.log_path).read_text(errors="replace")[-6000:]
        try:
            fix: DebugFix = self._agent(f"debugger_{session}", DEBUGGER, sandbox_tools(self.ctx.sandbox), DebugFix,
                                        max_turns=30, max_cost_usd=0.25 * self.cap).run(
                f"{self.brief}{self._context(state, 'env')}\n\n"
                f"Failed run (exit_code={rec.exit_code}, parsed value={rec.value}):\n{spec.model_dump_json(indent=1)}\n\n"
                f"End of its log:\n```\n{log_tail}\n```\n\n"
                f"Remaining runs:\n{json.dumps(state.get('pending', []), indent=1)}\n\n"
                f"Earlier debug sessions:\n{chr(10).join(history) or '(none)'}")
        except Exception as e:
            fix = DebugFix(diagnosis=f"debugger stopped: {type(e).__name__}: {e}", changes=[], revised_runs=[], give_up=True)
        history.append(f"session {session}: {fix.diagnosis} | changes: {fix.changes}")
        self.ctx.save(f"debug_{session}.json", fix)
        update: dict = {"debug_sessions": session, "history": history, "failed": None}
        if fix.give_up or not fix.revised_runs:
            rec.debug_notes.append(fix.diagnosis)
            update["records"] = [*state.get("records", []), rec.model_dump(mode="json")]
        else:
            update["pending"] = [r.model_dump(mode="json") for r in fix.revised_runs]
        return update

    def result_reviewer(self, state: MultiState) -> dict:
        update: dict = {"reviewed": True}
        if self._budget_spent():
            self.ctx.trace.log("result_reviewer", "skipped", reason="run budget exhausted")
            return update
        records = [RunRecord.model_validate(r) for r in state.get("records", [])]
        try:
            d: ReviewDecision = self._agent("result_reviewer", REVIEWER, sandbox_tools(self.ctx.sandbox, max_timeout_s=600),
                                            ReviewDecision, effort=REVIEW_EFFORT, max_turns=30,
                                            max_cost_usd=0.15 * self.cap).run(
                f"{self.brief}\n\nPaperSpec (paper_value per claim):{self._context(state, 'spec', 'env', 'plan')}\n\n"
                f"Pilot results per claim. Logs sit outside the workspace: read them with run_shell, e.g. "
                f"`tail -n 60 ../<log>`:\n{_measurements(records)}\n\n"
                f"Runs still to execute:\n{json.dumps(state.get('pending', []), indent=1)}")
        except Exception as e:  # a failed review must not stop the experiments
            self.ctx.trace.log("result_reviewer", "error", error=f"{type(e).__name__}: {e}")
            return update
        self.ctx.save("review.json", d)
        update["history"] = [*state.get("history", []), f"review: {d.assessment} | setup errors: {d.setup_errors}"]
        if d.revised_runs:
            update["records"] = [r.model_dump(mode="json") for r in records if r.claim_id not in set(d.rerun_claims)]
            update["pending"] = [r.model_dump(mode="json") for r in d.revised_runs]
        return update

    def discrepancy_analyst(self, state: MultiState) -> dict:
        if self._budget_spent():
            self.ctx.trace.log("discrepancy_analyst", "skipped", reason="run budget exhausted")
            return {"rerun_pending": False}
        records = [RunRecord.model_validate(r) for r in state.get("records", [])]
        reruns = state.get("reruns", 0)
        rerun_open = reruns < MAX_ANALYST_RERUNS and not state.get("error")
        try:
            d: AnalystDecision = self._agent(
                "discrepancy_analyst", ANALYST_DISCREPANCY, sandbox_tools(self.ctx.sandbox, write=False, max_timeout_s=600),
                AnalystDecision, effort=REVIEW_EFFORT, max_turns=30, max_cost_usd=0.2 * self.cap).run(
                f"{self.brief}\n\nPaperSpec (paper_value per claim):{self._context(state, 'spec', 'env', 'plan')}\n\n"
                f"Executor results per claim. Logs sit outside the workspace: read them with run_shell, e.g. "
                f"`tail -n 60 ../<log>`, and cite them as `<log>`:\n{_measurements(records)}\n\n"
                f"Debug sessions and reviews:\n{chr(10).join(state.get('history', [])) or '(none)'}\n\n"
                + ("A rerun for setup errors is still available (once)." if rerun_open else
                   "No rerun is available any more: write the final report and leave the rerun fields empty."))
        except Exception as e:  # the run is scored either way; no report counts as no diagnosis
            self.ctx.trace.log("discrepancy_analyst", "error", error=f"{type(e).__name__}: {e}")
            return {"rerun_pending": False}
        self.ctx.save("discrepancy_report.json", d.report())
        if not (rerun_open and d.revised_runs and d.rerun_claims):
            return {"rerun_pending": False}
        n = reruns + 1
        self.ctx.save(f"analyst_rerun_{n}.json", {"setup_errors": d.setup_errors, "rerun_claims": d.rerun_claims,
                                                   "revised_runs": [r.model_dump() for r in d.revised_runs]})
        self.ctx.trace.log("discrepancy_analyst", "rerun", n=n, claims=d.rerun_claims, setup_errors=d.setup_errors,
                           runs=len(d.revised_runs))
        drop = set(d.rerun_claims)
        return {"rerun_pending": True, "reruns": n,
                "records": [r.model_dump(mode="json") for r in records if r.claim_id not in drop],
                "pending": [r.model_dump(mode="json") for r in d.revised_runs],
                "history": [*state.get("history", []), f"analyst rerun {n}: claims {d.rerun_claims} | "
                                                       f"setup errors: {d.setup_errors}"]}

    # ---- routing

    def _after_setup(self, state: MultiState) -> str:
        return "finalize" if state.get("error") else "next"

    def _next_step(self, state: MultiState) -> str:
        if state.get("error"):
            return "discrepancy_analyst" if state.get("plan") else "finalize"
        if state.get("failed"):
            return "debugger"
        if not state.get("reviewed") and len(state.get("records", [])) >= state.get("n_pilots", 0):
            return "result_reviewer"
        if state.get("pending"):
            return "executor"
        return "discrepancy_analyst"

    def _after_analyst(self, state: MultiState) -> str:
        return "executor" if state.get("rerun_pending") and state.get("pending") else "finalize"

    def graph(self) -> StateGraph:
        g = StateGraph(MultiState)
        for name in ("paper_analyst", "env_agent", "planner", "executor", "debugger", "result_reviewer",
                     "discrepancy_analyst"):
            g.add_node(name, self._guarded(getattr(self, name)))
        g.add_node("finalize", lambda state: self._carry())
        g.add_edge(START, "paper_analyst")
        g.add_conditional_edges("paper_analyst", self._after_setup, {"next": "env_agent", "finalize": "finalize"})
        g.add_conditional_edges("env_agent", self._after_setup, {"next": "planner", "finalize": "finalize"})
        # Where each node can go next (all through _next_step); listed per node so the drawn graph is the real one.
        g.add_conditional_edges("planner", self._next_step, ["executor", "result_reviewer", "finalize"])
        g.add_conditional_edges("executor", self._next_step,
                                ["executor", "debugger", "result_reviewer", "discrepancy_analyst"])
        g.add_conditional_edges("debugger", self._next_step, ["executor", "result_reviewer", "discrepancy_analyst"])
        g.add_conditional_edges("result_reviewer", self._next_step, ["executor", "discrepancy_analyst"])
        g.add_conditional_edges("discrepancy_analyst", self._after_analyst, ["executor", "finalize"])
        g.add_edge("finalize", END)
        return g

    # ---- entry points

    def checkpoint_path(self) -> Path:
        # next to the workspace: deleted with it once the run is scored, since resuming needs the workspace anyway
        return self.ctx.sandbox.home / "checkpoints.sqlite"

    def run(self, resume: bool = False) -> EvalResult:
        from langgraph.checkpoint.sqlite import SqliteSaver

        config = {"configurable": {"thread_id": self.ctx.run_dir.name}, "recursion_limit": 1000}
        with SqliteSaver.from_conn_string(str(self.checkpoint_path())) as saver:
            app = self.graph().compile(checkpointer=saver)
            if resume:
                snap = app.get_state(config)
                if not snap.values:
                    raise RuntimeError(f"no checkpoint to resume in {self.checkpoint_path()}")
                values = snap.values
                self.ctx.sandbox.manifest.update(values.get("manifest", {}))
                self.ctx.budget.usage = Usage(**values.get("usage", {}))
                self._elapsed_before = values.get("elapsed_s", 0.0)
                self.ctx.trace.log("multi_agent", "resume", next=list(snap.next),
                                   spent_usd=round(self.ctx.budget.spent_usd, 4))
                final = app.invoke(None, config) if snap.next else values
            else:
                final = app.invoke({"history": [], "records": [], "pending": [], "reruns": 0}, config)
        records = [RunRecord.model_validate(r) for r in final.get("records", [])]
        error = final.get("error")
        metrics = aggregate(records, notes="\n".join(final.get("history", []) + ([error] if error else [])))
        started = time.monotonic() - final.get("elapsed_s", time.monotonic() - self._t0)
        return finish(self.ctx, metrics, started, error, extra={"analyst_reruns": final.get("reruns", 0)})


# ---------------------------------------------------------------- spec runs (questions about code in the workspace)

ENV_SPEC = f"""You are the Environment Engineer in a team testing the computational reproducibility of research code.
The authors' code (and data) is already in the workspace; do not clone or download the code from elsewhere.
1. Read the README and the code; find the scripts or notebooks that produce the results the questions ask about.
2. Create an environment (for Python, `uv venv --python 3.11 .venv` and `uv pip install`) with what the code needs.
   Pinned old versions often do not exist for this machine (Apple Silicon, CPU only): prefer the closest working
   versions and the libraries' own compatibility layers over rewriting the code.
3. Make the entry points runnable on this machine with minimal patches; list every patch.
4. Smoke-test: start each entry point briefly and confirm it gets past setup. Report the time a full run will take
   in `smoke_test`, so the planner does not have to guess.
{RUNTIME_RULES}
Do not run the full experiments and do not answer the questions; that is someone else's job. Submit an EnvReport
(`repo_dir` is the code's directory, e.g. `code`)."""

PLANNER_SPEC = """You are the Experiment Planner in a team testing the computational reproducibility of research code.
Using the task, its questions and the EnvReport, write the exact list of commands to run so that every question can
be answered from their output: one SpecRun per command, in order, each naming the question ids it serves.
You can read the code to get arguments, output files and the printed output format right.
- `command` runs from `workdir` (relative to the workspace) with the EnvReport's interpreter: a script, a notebook
  execution (for example `jupyter nbconvert --to html --execute ...`), a shell script. timeout_s up to 1800.
- The command must print its full output: its log is the evidence. Never filter it with grep/tail/sed or redirect it
  away. Files the program writes (tables, html reports, figures) are evidence too.
Submit a SpecPlan."""

DEBUGGER_SPEC = """You are the Debugger in a team testing the computational reproducibility of research code. A planned
command failed. Diagnose from the log, fix the code or environment with minimal changes, verify your fix with a
short run if possible, and return revised SpecRuns for the failed run and all remaining runs (keep run ids where the
run is the same). Never change what the code computes to get a particular answer. If the problem cannot be fixed, set
give_up=true and explain. Revised commands must print their full output, never filtered or redirected away.
Submit a SpecDebugFix."""

ANSWERER = f"""You are the Answerer in a team testing the computational reproducibility of research code. The planned
commands have run. Answer every question from their output: the logs (they sit outside the workspace, read them with
run_shell, e.g. `tail -n 80 ../<log>`, and cite them as `logs/<name>`) and the files the runs wrote (cite their
workspace path). Give each value exactly as a run printed or wrote it. Never type, estimate or compute an answer
yourself, and never take one from a file that was in the workspace before the runs.

Hand back once (only when the brief says it is still available): if a question cannot be answered because an
output is missing (a script that was not run, a run that stopped early), list the reason in `rerun_reasons` and in
`revised_runs` the complete commands to run; their logs are added and you answer again. Never hand back to get a
different value for a question that already has one.
If a question cannot be answered, leave it out and explain in `notes`.
{RUNTIME_RULES}
Submit an AnswerDecision."""


class SpecRun(BaseModel):
    run_id: str
    command: str = Field(description="Shell command, run from `workdir`")
    workdir: str = Field(".", description="Directory relative to the workspace")
    timeout_s: int = 1800
    questions: list[str] = Field(default_factory=list, description="Question ids this run's output answers")


class SpecPlan(BaseModel):
    rationale: str
    runs: list[SpecRun]


class SpecDebugFix(BaseModel):
    diagnosis: str
    changes: list[str] = Field(description="Code/env changes made, one per line")
    revised_runs: list[SpecRun] = Field(description="Replacement for the failed run and every remaining run")
    give_up: bool = False


class AnswerDecision(Answers):
    rerun_reasons: list[str] = Field(default_factory=list, description="Only with a hand-back: why each output is "
                                                                        "missing")
    revised_runs: list[SpecRun] = Field(default_factory=list, description="Only with a hand-back: commands to run")

    def answers_only(self) -> Answers:
        return Answers(answers=self.answers, notes=self.notes)


class SpecPipeline(MultiAgentWorkflow):
    """B on a spec: environment -> plan -> execute (+ debug) -> answer (+ one hand-back), routed by code."""

    def env_agent(self, state: MultiState) -> dict:
        env: EnvReport = self._agent("env_agent", ENV_SPEC,
                                     sandbox_tools(self.ctx.sandbox), EnvReport, max_turns=50,
                                     max_cost_usd=0.4 * self.cap).run(self.brief)
        self.ctx.save("env_report.json", env)
        if not env.ok:
            raise BudgetExceeded(f"environment not ready: {env.smoke_test}")
        return {"env": env.model_dump(mode="json")}

    def planner(self, state: MultiState) -> dict:
        plan: SpecPlan = self._agent("planner", PLANNER_SPEC, sandbox_tools(self.ctx.sandbox, shell=False, write=False),
                                     SpecPlan, max_turns=20, max_cost_usd=0.15 * self.cap).run(
            self.brief + self._context(state, "env"))
        self.ctx.save("plan.json", plan)
        return {"plan": plan.model_dump(mode="json"), "pending": [r.model_dump(mode="json") for r in plan.runs],
                "records": [], "debug_sessions": 0}

    def executor(self, state: MultiState) -> dict:
        pending = list(state["pending"])
        run = SpecRun.model_validate(pending.pop(0))
        res = self.ctx.sandbox.run(run.command, run.workdir, min(run.timeout_s, 1800), tag=f"exp_{run.run_id}")
        rec = {"run_id": run.run_id, "command": run.command, "workdir": run.workdir, "questions": run.questions,
               "exit_code": res.exit_code, "duration_s": round(res.duration_s, 2),
               "log": str(res.log_path.relative_to(self.ctx.run_dir))}
        self.ctx.trace.log("executor", "run", **rec)
        update: dict = {"pending": pending, "rerun_pending": False}
        if not res.ok and state.get("debug_sessions", 0) < self.max_debug_sessions and not self._budget_spent():
            update["failed"] = {"spec": run.model_dump(mode="json"), "record": rec}
        else:
            update["records"] = [*state.get("records", []), rec]
        return update

    def debugger(self, state: MultiState) -> dict:
        session = state.get("debug_sessions", 0) + 1
        run, rec = state["failed"]["spec"], state["failed"]["record"]
        history = list(state.get("history", []))
        log_tail = (self.ctx.run_dir / rec["log"]).read_text(errors="replace")[-6000:]
        try:
            fix: SpecDebugFix = self._agent(f"debugger_{session}", DEBUGGER_SPEC, sandbox_tools(self.ctx.sandbox),
                                            SpecDebugFix, max_turns=30, max_cost_usd=0.25 * self.cap).run(
                f"{self.brief}{self._context(state, 'env')}\n\n"
                f"Failed run (exit_code={rec['exit_code']}):\n{json.dumps(run, indent=1)}\n\n"
                f"End of its log:\n```\n{log_tail}\n```\n\n"
                f"Remaining runs:\n{json.dumps(state.get('pending', []), indent=1)}\n\n"
                f"Earlier debug sessions:\n{chr(10).join(history) or '(none)'}")
        except Exception as e:
            fix = SpecDebugFix(diagnosis=f"debugger stopped: {type(e).__name__}: {e}", changes=[], revised_runs=[],
                               give_up=True)
        history.append(f"session {session}: {fix.diagnosis} | changes: {fix.changes}")
        self.ctx.save(f"debug_{session}.json", fix)
        update: dict = {"debug_sessions": session, "history": history, "failed": None}
        if fix.give_up or not fix.revised_runs:
            update["records"] = [*state.get("records", []), {**rec, "debug_notes": [fix.diagnosis]}]
        else:
            update["pending"] = [r.model_dump(mode="json") for r in fix.revised_runs]
        return update

    def answerer(self, state: MultiState) -> dict:
        reruns = state.get("reruns", 0)
        rerun_open = reruns < MAX_ANALYST_RERUNS and not state.get("error")
        try:
            d: AnswerDecision = self._agent(
                "answerer", ANSWERER,
                sandbox_tools(self.ctx.sandbox, write=False, max_timeout_s=600), AnswerDecision,
                effort=REVIEW_EFFORT, max_turns=30, max_cost_usd=0.2 * self.cap).run(
                f"{self.brief}{self._context(state, 'env', 'plan')}\n\n"
                f"Executed runs:\n{json.dumps(state.get('records', []), indent=1)}\n\n"
                f"Debug sessions:\n{chr(10).join(state.get('history', [])) or '(none)'}\n\n"
                + (f"Setup stopped early: {state['error']}\n\n" if state.get("error") else "")
                + ("A hand-back for missing outputs is still available (once)." if rerun_open else
                   "No hand-back is available any more: answer from what exists and leave the hand-back fields empty."))
        except Exception as e:  # the run is scored either way
            self.ctx.trace.log("answerer", "error", error=f"{type(e).__name__}: {e}")
            return {"rerun_pending": False}
        self.ctx.save("answers_draft.json", d)
        update: dict = {"answers": d.answers_only().model_dump(mode="json"), "rerun_pending": False}
        if rerun_open and d.revised_runs:
            n = reruns + 1
            self.ctx.trace.log("answerer", "rerun", n=n, reasons=d.rerun_reasons, runs=len(d.revised_runs))
            update |= {"rerun_pending": True, "reruns": n, "pending": [r.model_dump(mode="json") for r in d.revised_runs],
                       "history": [*state.get("history", []), f"answerer hand-back {n}: {d.rerun_reasons}"]}
        return update

    def _next_step(self, state: MultiState) -> str:
        if state.get("error"):
            return "answerer"
        if state.get("failed"):
            return "debugger"
        return "executor" if state.get("pending") else "answerer"

    def _after_answerer(self, state: MultiState) -> str:
        return "executor" if state.get("rerun_pending") and state.get("pending") else "finalize"

    def graph(self) -> StateGraph:
        g = StateGraph(MultiState)
        for name in ("env_agent", "planner", "executor", "debugger", "answerer"):
            g.add_node(name, self._guarded(getattr(self, name)))
        g.add_node("finalize", lambda state: self._carry())
        g.add_edge(START, "env_agent")
        g.add_conditional_edges("env_agent", lambda s: "answerer" if s.get("error") else "planner",
                                ["planner", "answerer"])
        g.add_conditional_edges("planner", self._next_step, ["executor", "answerer"])
        g.add_conditional_edges("executor", self._next_step, ["executor", "debugger", "answerer"])
        g.add_conditional_edges("debugger", self._next_step, ["executor", "answerer"])
        g.add_conditional_edges("answerer", self._after_answerer, ["executor", "finalize"])
        g.add_edge("finalize", END)
        return g

    def run(self, resume: bool = False) -> corebench.CapsuleEval:
        from langgraph.checkpoint.sqlite import SqliteSaver

        if resume:
            raise RuntimeError("spec runs are not resumable")
        config = {"configurable": {"thread_id": self.ctx.run_dir.name}, "recursion_limit": 1000}
        with SqliteSaver.from_conn_string(str(self.checkpoint_path())) as saver:
            final = self.graph().compile(checkpointer=saver).invoke(
                {"history": [], "records": [], "pending": [], "reruns": 0}, config)
        answers = Answers.model_validate(final["answers"]) if final.get("answers") else None
        started = time.monotonic() - final.get("elapsed_s", time.monotonic() - self._t0)
        return corebench.finish(self.ctx, started, final.get("error"), answers=answers,
                                extra={"answerer_reruns": final.get("reruns", 0)})


def run(ctx: RunContext, max_debug_sessions: int = 4, resume: bool = False) -> EvalResult:
    if ctx.spec is not None:
        return SpecPipeline(ctx, max_debug_sessions).run(resume=resume)
    return MultiAgentWorkflow(ctx, max_debug_sessions).run(resume=resume)
