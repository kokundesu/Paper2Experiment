"""Version D: one Planner (the only planner) + the deterministic Runtime of p2e.runtime with three verification stages,
and worker sub-agents with their own context for every agent task.

    plan     the Planner reads the paper and the runtime update, keeps the task ledger, and submits an ExperimentPatch
             (tasks to add / cancel / replace, or a finish proposal); the runtime applies it or returns the problems
    execute  the runtime runs ready tasks: `run` tasks itself (plan check, smoke run, full run, evidence check),
             `agent` tasks (setup / debug / diagnose) through `run_agent`; it wakes the Planner on a failure, a finished
             agent task, or when nothing is left, handing over only what changed (plus progress, loop and stall fields)
    replan   after STALL_LIMIT stalls the Planner's conversation is reset and re-seeded from the ledger and the task
             list (Magentic-One); after MAX_REPLANS resets the run is scored as it stands
    diagnose once the runtime accepts a finish proposal (or the budget or the wake limit ends the run), every claim is
             diagnosed; numbers come only from counted runs that passed the gates
    finalize metrics -> evaluator

Spec runs (a ReproSpec such as a CORE-Bench capsule, ctx.spec set): the code is already in the workspace and the
task is a list of questions. The Planner gets the spec prompt below, runs need no metric regex, the finish proposal
carries the answers (the runtime checks where each came from), there is no diagnosis phase, and p2e.corebench scores
the run.

Workers: each agent task (setup, debug, diagnose) goes to a fresh worker that sees only the delegation message and
returns a structured report; diagnosis tasks run up to three at a time and workers never talk to each other.

Ablation switches: `PlannerRuntimeWorkflow(ctx, gates=..., workers=...)`. The comparison runs D only (gates and
workers on); gates=False and workers=False reproduce the round-1 C- and C settings, kept for the appendix and tests.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from p2e import corebench
from p2e.llm import REVIEW_EFFORT, Agent, Tool, Usage, sandbox_tools
from p2e.prompts import RUNTIME_RULES, SETUP_CHECK_RULES
from p2e.runner import DIAGNOSIS_RULES, RunContext, finish
from p2e.runtime import (MAX_PARALLEL_DIAGNOSE, STALL_LIMIT, AgentTask, ExperimentPatch, RunTask, Runtime)
from p2e.schemas import ClaimDiagnosis, DiscrepancyReport, EvalResult
from p2e.spec import AnswerItem, Answers

NAME = "planner_workers"
DESCRIPTION = "D: one Planner submitting task-DAG patches + deterministic runtime with 3-stage verification + worker sub-agents"
RESUMABLE = True

PLANNER_TURNS = 16  # tool calls per planning turn (reading files, then the patch)
MAX_PATCH_TRIES = 3  # patches the runtime may refuse per wake before execution continues without one
MAX_WAKES = 60
MAX_REPLANS = 3

# ---------------------------------------------------------------- prompts

PLANNER = """You are the Planner of a team reproducing results of a research paper with its official code. You are
the only one who decides what happens. You never run experiments yourself: you submit an ExperimentPatch and a
deterministic runtime executes it. When tasks finish or fail, the runtime wakes you with what changed.

Tasks you can add:
- run: one experiment run of one claim and seed. The runtime runs `command` in `workdir` (relative to the workspace)
  and parses `metric_regex` (last match, one capture group) times `scale`. Counted runs (counts=true) are the claim's
  measurements: each claim needs {seeds} counted runs with distinct seeds. Exactly one variant per claim counts; other
  variants (for example the paper-text setting when the official command differs) are diagnostics (counts=false).
- agent: work that needs an LLM with tools.
    setup    clone the repository (full history), build the environment, make the entrypoint runnable on this
             machine with minimal patches, smoke-test it and measure the time per epoch/iteration
    debug    investigate a failed task from its log, fix code or environment minimally, propose corrected run tasks
    diagnose explain the gap of one claim, with cheap diagnostic runs
  Write the delegation fully: objective, tools_and_sources, boundaries, context_refs (paths of logs and files to read),
  done_criteria, effort_turns. Results come back to you as a structured report.
Use depends_on for order (runs depend on the setup task). A failed task can be replaced: add the corrected task and a
`replace` entry old -> new; tasks waiting on the old one are moved to the new one.

Task ledger (keep it current through `ledger`): facts given or verified, facts to look up (and where), facts to derive,
assumptions, and the plan. Every setting the paper does not state that you or a task infer goes into `assumptions`
with its basis; mark it verified only when a run or a file confirms it. When a number misses the paper, the
assumptions are checked first.

{verification}

Finishing: propose `finish` only when every claim has its counted values, or state for a claim why it cannot be
measured after real attempts. The runtime checks the proposal and refuses it otherwise.

{setup_rules}

{runtime_rules}

Your own tools are read-only (read_file, list_dir): read `paper/paper.txt` and any file you need. Each time you are
woken, submit one ExperimentPatch."""

PLANNER_SPEC = """You are the Planner of a team testing the computational reproducibility of research code. The code (and
its data) is already in the workspace; the task is to run it and answer questions about its results. You are the only
one who decides what happens. You never run commands yourself: you submit an ExperimentPatch and a deterministic
runtime executes it. When tasks finish or fail, the runtime wakes you with what changed.

Tasks you can add:
- run: one command, run in `workdir` (relative to the workspace): a script, a notebook execution (for example
  `jupyter nbconvert --to html --execute ...`), a shell script. Its full output goes to a log (logs/<name>); files it
  writes stay in the workspace. metric_regex is optional: set it if you want the runtime to parse one number for you.
  timeout_s up to 1800.
- agent: work that needs an LLM with tools.
    setup    read the README and the code, create an environment (e.g. `uv venv --python 3.11 .venv`), install what the
             code needs, make the entry point runnable on this machine with minimal patches and smoke-test it
    debug    investigate a failed task from its log, fix code or environment minimally, propose corrected run tasks
  Write the delegation fully: objective, tools_and_sources, boundaries, context_refs (paths of logs and files to read),
  done_criteria, effort_turns. Results come back to you as a structured report.
Use depends_on for order (runs depend on the setup task). A failed task can be replaced: add the corrected task and a
`replace` entry old -> new; tasks waiting on the old one are moved to the new one.

Task ledger (keep it current through `ledger`): facts given or verified, facts to look up, assumptions, and the plan.

{verification}

Finishing: when the runs are done, read their logs (read_log) and the files they wrote (read_file, list_dir) and
propose `finish` with `answers`: one per question id, the value exactly as a run printed or wrote it, and `evidence`
(the log, e.g. logs/cmd_012_exp_main.log, or the output file's workspace path). If a question cannot be answered after
real attempts, put it in `not_measured` with the reason.

{runtime_rules}

Your own tools are read-only (read_file, list_dir, read_log). Each time you are woken, submit one ExperimentPatch."""

VERIFICATION_ON_SPEC = """Verification, enforced by the runtime:
1. When you add a run task: its command must print its full output (no pipes into grep, tail, head, sed..., no
   redirection of stdout to a file); writing result files through the program's own options is fine. The workdir must
   exist unless the task depends on the setup task. smoke_command is optional; if given, it must exit 0 first.
2. A run counts when it exits 0.
3. Finish: every answer must appear in the output of a run of this session (its log, or a file a run created or
   changed). An answer found only in files that were in the workspace before the run, or only in text you or a task
   wrote yourselves, is refused."""

VERIFICATION_OFF_SPEC = """Every command must print its full output to stdout/stderr, never filtered or redirected, and
every answer must cite the log or output file of the run that produced it."""

VERIFICATION_ON = """Verification, enforced by the runtime:
1. When you add a run task: its command and smoke_command must print their full output (no pipes into grep, tail,
   head, sed..., no redirection to files or /dev/null), metric_regex must have one capture group, smoke_command is
   required, and the workdir must exist unless the task depends on the setup task.
2. Before the full command, the runtime runs smoke_command: the same command cut down to a few steps or one epoch. It
   must exit 0, print training progress (per-step or per-epoch losses) and print the metric line.
3. After the full command: the run counts only if it exited 0 and its own log shows both training progress and the
   metric. If the code prints progress only with a flag (e.g. --verbose), use the flag.
A task that fails a check comes back to you with the problems."""

VERIFICATION_OFF = """Every command must print its full output (training progress and the metric) to stdout/stderr,
never filtered or redirected: the run's log is the only evidence the evaluator accepts."""

ROLE_GUIDE = {
    "setup": f"""Setup guidance: `git clone <repo> repo` with full history, read the README and the code, create a
Python environment with `uv venv` (e.g. `uv venv --python 3.11 .venv`) and install what the code needs. Old pinned
versions often do not exist for this machine (Apple Silicon, CPU only): prefer the closest working modern versions and
the libraries' own compatibility layers over rewriting code. Make each claim's setting and the seed selectable from
the command line, patch minimally and list every patch. Smoke-test a short run and report the time per epoch or
iteration and the projected time of one full run. Do not run the full experiments.
{RUNTIME_RULES}""",
    "debug": """Debug guidance: diagnose the failure from the log first, then change code or environment minimally
and faithfully, verify with a short run, and propose corrected run tasks (keep claim_id and seed; new task ids). Never
change a hyperparameter away from the paper to make a number look better. If it cannot be fixed, set give_up.""",
    "diagnose": f"""Diagnosis guidance: the measured values are final and nothing you run changes them. Apply the
claim's pre-registered criterion, then explain the gap.
{DIAGNOSIS_RULES}""",
}

ROLE_GUIDE_SPEC = {
    "setup": f"""Setup guidance: the code is already in the workspace (do not clone or download it). Read the README and
the code, create a Python environment with `uv venv` (e.g. `uv venv --python 3.11 .venv`) and install what the code
needs. Old pinned versions often do not exist for this machine (Apple Silicon, CPU only): prefer the closest working
modern versions over rewriting code. Patch minimally and list every patch. Smoke-test briefly; do not run the full
program and do not answer the questions.
{RUNTIME_RULES}""",
    "debug": ROLE_GUIDE["debug"],
    "diagnose": "Diagnosis is not part of this task: report that nothing was diagnosed.",
}

WORKER = """You are a {role} worker in a team reproducing a paper. The Planner delegated one task to you. Do only that
task, stay within its boundaries, and submit the requested report. Logs sit outside the workspace: read them with
run_shell, e.g. `tail -n 60 ../logs/<name>`."""


class SetupReport(BaseModel):
    repo_dir: str = Field(description="Repository path relative to the workspace")
    python: str = Field(description="Interpreter to run experiments with, relative to the workspace")
    entrypoint: str = Field(description="Main script relative to the workspace")
    patches: list[str] = Field(default_factory=list, description="One line per source change made and why")
    smoke_test: str = Field(description="The short run you made and its outcome")
    seconds_per_epoch: float | None = Field(None, description="Measured time per epoch or iteration, if known")
    projected_full_run_min: float | None = None
    ok: bool
    notes: str = ""


class DebugReport(BaseModel):
    diagnosis: str
    changes: list[str] = Field(default_factory=list, description="Code/env changes made, one per line")
    suggested_tasks: list[RunTask] = Field(default_factory=list, description="Corrected run tasks (new task ids)")
    give_up: bool = False


ROLE_OUTPUT: dict[str, type[BaseModel]] = {"setup": SetupReport, "debug": DebugReport, "diagnose": ClaimDiagnosis}


# ---------------------------------------------------------------- state and workflow


class PlannerState(TypedDict, total=False):
    runtime: dict  # Runtime.state
    history: list  # the Planner's conversation (LangChain messages)
    note: str  # the next message to the Planner
    phase: str  # plan | execute | diagnose
    wakes: int
    error: str | None
    manifest: dict
    usage: dict
    elapsed_s: float


class PlannerRuntimeWorkflow:
    def __init__(self, ctx: RunContext, *, gates: bool = True, workers: bool = True):
        self.ctx = ctx
        self.gates = gates
        self.workers = workers
        self.cap = ctx.budget.limit_usd
        self.brief = ctx.task_brief()
        self.is_spec = ctx.spec is not None
        self.guide = ROLE_GUIDE_SPEC if self.is_spec else ROLE_GUIDE
        self._t0 = time.monotonic()
        self._elapsed_before = 0.0
        if self.is_spec:
            system = PLANNER_SPEC.format(verification=VERIFICATION_ON_SPEC if gates else VERIFICATION_OFF_SPEC,
                                         runtime_rules=RUNTIME_RULES)
        else:
            system = PLANNER.format(seeds=ctx.task.seeds, verification=VERIFICATION_ON if gates else VERIFICATION_OFF,
                                    setup_rules=SETUP_CHECK_RULES, runtime_rules=RUNTIME_RULES)
        self.planner = Agent(
            "planner", system,
            self._read_tools(), ExperimentPatch, ctx.trace, ctx.budget, max_turns=PLANNER_TURNS,
            # in C the Planner also does the agent tasks, so it gets nearly the whole budget; in D workers share it
            max_cost_usd=(0.5 if workers else 0.9) * self.cap)
        self.history: list = []

    # ---- tools and helpers

    def _read_tools(self):
        tools = sandbox_tools(self.ctx.sandbox, shell=False, write=False)
        if self.is_spec:
            tools.append(self._read_log_tool())
        return tools

    def _read_log_tool(self) -> Tool:
        log_dir = self.ctx.sandbox.log_dir

        def read_log(a: dict) -> str:
            name = a["name"].removeprefix("logs/").removeprefix("../logs/")
            path = (log_dir / name).resolve()
            if not path.is_relative_to(log_dir.resolve()) or not path.is_file():
                return f"no such log: {a['name']} (logs: {sorted(p.name for p in log_dir.glob('*.log'))[-20:]})"
            lines = path.read_text(errors="replace").splitlines()
            start, limit = max(int(a.get("offset", 1)), 1), int(a.get("limit", 400))
            body = "\n".join(f"{i:5d}\t{line}" for i, line in enumerate(lines[start - 1:start - 1 + limit], start))
            more = f"\n[{len(lines)} lines total]" if start - 1 + limit < len(lines) else ""
            return body + more
        return Tool("read_log", "Read a command log (logs/<name>) with line numbers.",
                    {"type": "object", "properties": {"name": {"type": "string"}, "offset": {"type": "integer"},
                                                      "limit": {"type": "integer"}}, "required": ["name"]},
                    read_log)

    def _runtime(self, state: PlannerState) -> Runtime:
        return Runtime(self.ctx, gates=self.gates, parallel=MAX_PARALLEL_DIAGNOSE if self.workers else 1,
                       state=state.get("runtime"))

    def _carry(self, rt: Runtime | None = None) -> dict:
        out = {"manifest": dict(self.ctx.sandbox.manifest), "usage": dict(self.ctx.budget.usage.__dict__),
               "elapsed_s": self._elapsed_before + time.monotonic() - self._t0, "history": self.history}
        if rt is not None:
            out["runtime"] = rt.state
        return out

    def _budget_spent(self) -> bool:
        b = self.ctx.budget
        return b.spent_usd >= b.limit_usd - b.reserve_usd

    def delegation(self, task: AgentTask, rt: Runtime) -> str:
        """The delegation message of an agent task (Anthropic's template), plus what its role needs to know."""
        parts = [f"Task {task.task_id} ({task.role}).", f"Objective: {task.objective}"]
        if task.tools_and_sources:
            parts.append(f"Tools and sources: {task.tools_and_sources}")
        if task.boundaries:
            parts.append(f"Boundaries: {task.boundaries}")
        if task.context_refs:
            parts.append("Read these files (logs are at ../logs/<name>): " + ", ".join(task.context_refs))
        if task.done_criteria:
            parts.append(f"Done when: {task.done_criteria}")
        if task.role == "debug" and task.about_task in rt.tasks:
            failed = rt.tasks[task.about_task]
            parts.append("Failed task:\n" + json.dumps({"spec": failed["spec"], **{k: failed.get(k) for k in
                                                        ("stage", "problems", "log", "signature")}}, indent=1))
        if task.role == "diagnose" and task.claim_id:
            parts.append(f"Measured values of {task.claim_id} (value, log): "
                         + json.dumps(rt.counted_values().get(task.claim_id, [])))
        parts.append(self.guide[task.role])
        parts.append(f"Budget: at most {task.effort_turns} tool calls. Submit a {ROLE_OUTPUT[task.role].__name__}.")
        return "\n\n".join(parts)

    def run_agent(self, task: AgentTask, rt: Runtime) -> tuple[bool, dict, str]:
        """Execute an agent task: in C inside the Planner's own conversation, in D by a fresh worker."""
        output = ROLE_OUTPUT[task.role]
        tools = sandbox_tools(self.ctx.sandbox, write=task.role != "diagnose", max_timeout_s=1800)
        message = self.delegation(task, rt)
        if self.workers:
            worker = Agent(f"{task.role}_{task.task_id}", WORKER.format(role=task.role) + "\n\n" + RUNTIME_RULES,
                           tools, output, self.ctx.trace, self.ctx.budget, max_turns=task.effort_turns,
                           effort=REVIEW_EFFORT if task.role == "diagnose" else self.planner.effort,
                           max_cost_usd=0.2 * self.cap)
            report = worker.run(message)
        else:
            report, self.history = self.planner.converse(self.history, message, output=output, tools=tools,
                                                         max_turns=task.effort_turns)
        ok = not ((isinstance(report, SetupReport) and not report.ok) or (isinstance(report, DebugReport)
                                                                          and report.give_up))
        summary = getattr(report, "diagnosis", None) or getattr(report, "smoke_test", None) \
            or getattr(report, "conclusion", "") or "done"
        return ok, report.model_dump(mode="json"), summary

    # ---- messages to the Planner

    def first_message(self) -> str:
        if self.is_spec:
            return (f"{self.brief}\n\nThe code is in the workspace (list_dir, read_file). Read the README and the "
                    f"code, start the task ledger, and submit your first ExperimentPatch (typically a setup task, and "
                    f"runs depending on it once you know the commands).")
        return (f"{self.brief}\n\nThe workspace has the paper in paper/ (paper.txt is its text); the repository is "
                f"not cloned yet. Read the paper, start the task ledger, and submit your first ExperimentPatch "
                f"(typically a setup task, and runs depending on it once you know the commands).")

    def wake_message(self, view: dict, rt: Runtime) -> str:
        changed = []
        for c in view["changed"]:
            item = dict(c)
            task = rt.tasks[c["task_id"]]
            if task["spec"]["kind"] == "agent" and task.get("artifact"):
                item["report"] = task["artifact"]
            if self.is_spec and task["spec"]["kind"] == "run" and task.get("log"):
                item["output_tail"] = self._tail(task["log"])
            changed.append(item)
        flags = {k: view[k] for k in ("is_progress_being_made", "is_in_loop")}
        return ("Runtime update.\n"
                f"Changed since your last patch:\n{json.dumps(changed, indent=1)}\n"
                f"Progress: {json.dumps(flags)}; stalls: {rt.state['stalls']} of {STALL_LIMIT}\n"
                + (f"Questions: {[q.id for q in self.ctx.spec.questions]} (answer them in a finish proposal)\n"
                   if self.is_spec else f"Claims (counted values / needed): {json.dumps(view['claims'])}\n") +
                f"Not finished yet: {view['pending']}\n"
                f"Budget left: ${view['budget_left_usd']}\n"
                "Submit an ExperimentPatch (or a finish proposal).")

    def _tail(self, log: str, chars: int = 1500) -> str:
        try:
            text = (self.ctx.run_dir / log).read_text(errors="replace")
        except OSError:
            return ""
        return text[-chars:]

    def replan_message(self, rt: Runtime) -> str:
        """A fresh conversation after repeated stalls: the ledger and the task list carry over, the chat does not."""
        tasks = [rt._view(tid) for tid in rt.state["order"]]
        for t in tasks:
            artifact = rt.tasks[t["task_id"]].get("artifact")
            if artifact:
                t["report"] = artifact
        return (f"{self.brief}\n\nThe run stalled ({STALL_LIMIT} wakes without progress, or the same failure "
                f"repeating). Your earlier conversation was cleared; this is what persists.\n\n"
                f"Task ledger:\n{json.dumps(rt.state['ledger'], indent=1)}\n\nTasks so far:\n{json.dumps(tasks, indent=1)}\n\n"
                "Re-plan: state the root cause of the stall and what must not be repeated in `reasoning`, update the "
                "ledger, and submit an ExperimentPatch with a different approach.")

    # ---- nodes

    def plan(self, state: PlannerState) -> dict:
        rt = self._runtime(state)
        wakes = state.get("wakes", 0) + 1
        if wakes > MAX_WAKES:
            self.ctx.trace.log("planner_runtime", "stop", reason=f"wake limit {MAX_WAKES}")
            return {"phase": "diagnose", "wakes": wakes, **self._carry(rt)}
        message = state.get("note") or self.first_message()
        for attempt in range(MAX_PATCH_TRIES):
            patch, self.history = self.planner.converse(self.history, message, output=ExperimentPatch,
                                                        tools=self._read_tools(), max_turns=PLANNER_TURNS)
            problems = rt.apply(patch.model_copy(update={"finish": None}))
            if not problems and patch.finish is not None:
                problems = rt.check_finish(patch.finish)
                if not problems:
                    return {"phase": "diagnose", "wakes": wakes, "note": "", **self._carry(rt)}
                message = ("The runtime refused to finish:\n- " + "\n- ".join(problems)
                           + "\nFix this with another patch (tasks, or not-measured reasons backed by attempts).")
                continue
            if not problems:
                return {"phase": "execute", "wakes": wakes, "note": "", **self._carry(rt)}
            message = ("The runtime refused the patch; nothing in it was applied:\n- " + "\n- ".join(problems)
                       + "\nSubmit a corrected ExperimentPatch.")
        return {"phase": "execute", "wakes": wakes, "note": "", **self._carry(rt)}

    def execute(self, state: PlannerState) -> dict:
        rt = self._runtime(state)
        while True:
            if self._budget_spent():
                self.ctx.trace.log("planner_runtime", "stop", reason="run budget exhausted")
                return {"phase": "diagnose", **self._carry(rt)}
            executed = rt.step(self.run_agent)
            if rt.should_wake(executed):
                break
        view = rt.wake()
        if not view["replan"]:
            return {"phase": "plan", "note": self.wake_message(view, rt), **self._carry(rt)}
        self.ctx.trace.log("planner_runtime", "replan", n=rt.state["replans"])
        if rt.state["replans"] > MAX_REPLANS:
            self.ctx.trace.log("planner_runtime", "stop", reason=f"more than {MAX_REPLANS} re-plans")
            return {"phase": "diagnose", **self._carry(rt)}
        self.history = []  # Magentic-One: reset the conversation, keep the ledger and the artifacts
        return {"phase": "plan", "note": self.replan_message(rt), **self._carry(rt)}

    def diagnose(self, state: PlannerState) -> dict:
        rt = self._runtime(state)
        if self.is_spec:  # questions have no paper value to explain
            return self._carry(rt)
        if self._budget_spent():
            self.ctx.trace.log("diagnosis", "skipped", reason="run budget exhausted")
            return self._carry(rt)
        claims = [c.id for c in self.ctx.task.claims]
        try:
            if self.workers:
                tasks = [AgentTask(task_id=f"final_diag_{c}", role="diagnose", claim_id=c,
                                   objective=f"Diagnose claim {c}: does it meet its criterion, and if not, why?")
                         for c in claims]
                with ThreadPoolExecutor(min(MAX_PARALLEL_DIAGNOSE, len(tasks))) as pool:
                    results = list(pool.map(lambda t: self.run_agent(t, rt), tasks))
                report = DiscrepancyReport(claims=[ClaimDiagnosis.model_validate(art) for ok, art, _ in results if art])
            else:
                values = {c: rt.counted_values().get(c, []) for c in claims}
                report, self.history = self.planner.converse(
                    self.history,
                    f"The run is over. Measured values per claim (value, log): {json.dumps(values)}\n\n"
                    f"{ROLE_GUIDE['diagnose']}\n\nSubmit a DiscrepancyReport with one ClaimDiagnosis per claim.",
                    output=DiscrepancyReport, tools=sandbox_tools(self.ctx.sandbox, write=False, max_timeout_s=600),
                    max_turns=30)
            self.ctx.save("discrepancy_report.json", report)
        except Exception as e:  # the run is scored either way; no report counts as no diagnosis
            self.ctx.trace.log("diagnosis", "error", error=f"{type(e).__name__}: {e}")
        return self._carry(rt)

    def _guarded(self, fn):
        def node(state: PlannerState) -> dict:
            try:
                return fn(state)
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                self.ctx.trace.log("planner_runtime", "error", error=error)
                rt = self._runtime(state)
                return {"error": error, "phase": "diagnose", **self._carry(rt)}
        node.__name__ = fn.__name__
        return node

    def graph(self) -> StateGraph:
        g = StateGraph(PlannerState)
        g.add_node("plan", self._guarded(self.plan))
        g.add_node("execute", self._guarded(self.execute))
        g.add_node("diagnose", self.diagnose)
        g.add_node("finalize", lambda state: self._carry())
        g.add_edge(START, "plan")
        g.add_conditional_edges("plan", lambda s: s["phase"], {"execute": "execute", "diagnose": "diagnose"})
        g.add_conditional_edges("execute", lambda s: s["phase"], {"plan": "plan", "diagnose": "diagnose"})
        g.add_edge("diagnose", "finalize")
        g.add_edge("finalize", END)
        return g

    # ---- entry point

    def checkpoint_path(self) -> Path:
        return self.ctx.sandbox.home / "checkpoints.sqlite"

    def run(self, resume: bool = False) -> EvalResult:
        from langgraph.checkpoint.sqlite import SqliteSaver

        config = {"configurable": {"thread_id": self.ctx.run_dir.name}, "recursion_limit": 4 * MAX_WAKES + 20}
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
                self.history = values.get("history", [])
                self.planner.adopt(self.history)
                self.ctx.trace.log("planner_runtime", "resume", next=list(snap.next))
                final = app.invoke(None, config) if snap.next else values
            else:
                self.ctx.trace.log("planner_runtime", "start", gates=self.gates, workers=self.workers)
                final = app.invoke({"wakes": 0, "note": "", "history": []}, config)
        rt = self._runtime(final)
        error = final.get("error")
        ledger = rt.state["ledger"]
        notes = "\n".join([f"assumptions: {json.dumps(ledger.get('assumptions', []))}",
                           f"finish: {json.dumps(rt.state['finished'])}"] + ([error] if error else []))
        started = time.monotonic() - final.get("elapsed_s", time.monotonic() - self._t0)
        status_counts: dict[str, int] = {}
        for t in rt.tasks.values():
            status_counts[t["status"]] = status_counts.get(t["status"], 0) + 1
        if self.is_spec:
            raw = rt.answers()
            answers = Answers(answers=[AnswerItem.model_validate(a) for a in raw], notes=notes) if raw else None
            return corebench.finish(self.ctx, started, error, answers=answers, extra={
                "gates": self.gates, "workers": self.workers, "planner_wakes": final.get("wakes", 0),
                "replans": rt.state["replans"], "finish_accepted": rt.state["finished"] is not None,
                "tasks": status_counts})
        return finish(self.ctx, rt.metrics(notes), started, error, extra={
            "gates": self.gates, "workers": self.workers, "planner_wakes": final.get("wakes", 0),
            "replans": rt.state["replans"], "finish_accepted": rt.state["finished"] is not None,
            "tasks": status_counts})


def run(ctx: RunContext, resume: bool = False) -> EvalResult:
    return PlannerRuntimeWorkflow(ctx).run(resume=resume)
