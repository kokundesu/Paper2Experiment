"""Deterministic runtime for the Planner + Runtime versions (Multiagent/PlannerRuntime and its variants).

Design, after DeepSeek Harness / Cuti (one planner, declarative plan patches, the runtime as the source of truth,
event-driven wakes) and the papers read for v4 (MAST: verify at several stages and let only the verifier end a run;
AutoReproduce: dry-run before full training; Magentic-One: progress ledger and stall-triggered re-planning):

* The Planner never runs an experiment. It submits an `ExperimentPatch`: tasks to add (with dependencies), tasks to
  cancel, failed tasks to replace, ledger updates, or a finish proposal.
* The Runtime owns the task DAG and executes ready tasks one at a time (diagnosis tasks may run in parallel).
  `run` tasks are the only source of numbers. `agent` tasks (setup / debug / diagnose) are executed by a callback the
  version provides (in the Planner's own context, or by a worker with its own context).
* Three verification stages, all deterministic, for `run` tasks when gates are on:
    1. plan check when the task is added: workdir exists, the regex has one group, the command does not filter or
       redirect its output, a smoke command is given, one counted variant per claim, replacement budget;
    2. smoke run: the cut-down command must exit 0, print training progress and print a parsable metric;
    3. evidence check after the full run: exit 0, a parsed value and training progress in the same log.
  With gates off (version C-), a run only has to print a parsable value.
* After every step the Runtime decides whether to wake the Planner (a failure, a finished agent task, or nothing left
  to run) and hands it only what changed since the last wake, plus computed progress fields (Magentic-One's
  progress ledger minus the fields the Planner decides: what to do next and how to ask for it).
* Only the Runtime ends a run: a finish proposal is accepted when every claim has enough validated values or a
  stated not-measured reason backed by attempts.
* A run that exited 0 and failed only because its metric_regex matched nothing can be re-read: the Planner submits a
  `reparse` with a corrected regex, and the runtime parses the same log again (after checking it is the log the sandbox
  wrote) instead of running the experiment a second time. A demo run once spent six more minutes of training only
  because the value printed as `tensor(-21.86)` and the first regex expected a bare number.
* Spec runs (a ReproSpec, e.g. CORE-Bench): runs need no metric regex and no training progress (the program may be a
  notebook or an analysis script), and the finish proposal carries the answers. With gates on, the finish gate checks
  where each answer came from: it must appear in this run's output, not only in files the capsule shipped with or
  in text the agent wrote itself (p2e.capsule.provenance). Correctness is never revealed.

All state is plain data (`Runtime.state`), so it sits in LangGraph state and is checkpointed with it.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any, Callable, Literal, Union

from pydantic import BaseModel, Field

from .capsule import split_log
from .runner import RunContext, parse_metric
from .sandbox import file_sha256
from .schemas import ClaimMeasurement, Metrics
from .spec import AnswerItem, answer_problems

# Lines that show a run doing its work: epochs, steps, losses, folds, progress bars. Case-insensitive, needs a number.
PROGRESS_RE = re.compile(r"(?i)\b(epoch|step|iter(?:ation)?s?|loss|train(?:ing)?|progress|fold|batch)\b[^\n]{0,80}\d")
# Output filtering or redirection: the log must be the run's full output (MAST FM-2.4: evidence withheld downstream).
_FILTERS = [
    (re.compile(r"\|\s*(grep|egrep|fgrep|tail|head|sed|awk|cut|sort|uniq|wc|less|more)\b"), "pipes its output into a filter"),
    (re.compile(r"(?<![0-9&])>{1,2}\s*(?!&)[^\s|&;]+"), "redirects stdout to a file"),
    (re.compile(r"\d?>\s*/dev/null|&>"), "discards output"),
]
STALL_LIMIT = 3  # Magentic-One (AutoGen code): re-plan when net stalls reach 3; progress lowers the count by 1
MAX_REPLACEMENTS = 8  # AutoReproduce App. A.2: bugs are fixed within 5-8 tries, more rarely help
SMOKE_TIMEOUT_S = 300
MAX_PARALLEL_DIAGNOSE = 3  # Scaling Agent Systems: per-agent capacity thins beyond 3-4 agents


# ---------------------------------------------------------------- what the Planner submits


class RunTask(BaseModel):
    """One experiment run. Counted runs of a claim are its measurements; others are diagnostics."""
    kind: Literal["run"] = "run"
    task_id: str = Field(description="Unique id, e.g. acc_main_s0")
    claim_id: str = Field("", description="The claim this run measures (paper tasks); optional for question tasks")
    seed: int = 0
    variant: str = Field("main", description="Protocol variant label, e.g. main / readme / paper_text")
    counts: bool = Field(True, description="True: a measurement of the claim. Exactly one variant per claim counts")
    command: str = Field(description="Shell command run from workdir; prints its full output (no pipes, no redirection)")
    workdir: str = Field(".", description="Directory relative to the workspace")
    timeout_s: int = 1200
    metric_regex: str | None = Field(None, description="Python regex with ONE capture group; the last match is "
                                                         "used. Required for paper claims")
    scale: float = Field(1.0, description="Multiply the parsed value by this to get the claim's unit")
    smoke_command: str | None = Field(None, description="Same command cut down to finish in minutes (few steps / one "
                                                        "epoch) that still prints progress and the metric line")
    depends_on: list[str] = Field(default_factory=list)
    purpose: str = ""


class AgentTask(BaseModel):
    """Work that needs an LLM with tools. The fields are the delegation message (objective, output, tools and sources,
    boundaries, context references, effort, done criteria)."""
    kind: Literal["agent"] = "agent"
    task_id: str
    role: Literal["setup", "debug", "diagnose"]
    objective: str
    tools_and_sources: str = Field("", description="Commands, files and paper sections to use")
    boundaries: str = Field("", description="What the task may change and what it must not touch")
    context_refs: list[str] = Field(default_factory=list, description="Paths of logs/files to read (not pasted text)")
    done_criteria: str = ""
    effort_turns: int = Field(30, ge=1, le=60, description="Tool-call budget for the task")
    claim_id: str | None = None
    about_task: str | None = Field(None, description="debug: the failed task to investigate")
    depends_on: list[str] = Field(default_factory=list)


Task = Annotated[Union[RunTask, AgentTask], Field(discriminator="kind")]


class Assumption(BaseModel):
    setting: str
    value: str
    basis: str = Field(description="Where it comes from: paper section, code default, inferred from ...")
    status: Literal["assumed", "verified"] = "assumed"


class LedgerUpdate(BaseModel):
    """Task ledger sections (Magentic-One). A section that is given replaces the old one."""
    given_or_verified: list[str] | None = None
    to_look_up: list[str] | None = None
    to_derive: list[str] | None = None
    assumptions: list[Assumption] | None = None
    plan: str | None = None


class Replacement(BaseModel):
    old_task_id: str
    new_task_id: str = Field(description="A task in add_tasks of the same patch")


class Reparse(BaseModel):
    """Read a finished run's log again with a corrected regex, instead of running it again."""
    task_id: str = Field(description="A failed run task whose only problem was 'no parsable metric value'")
    metric_regex: str = Field(description="Corrected Python regex with ONE capture group; the last match is used")
    scale: float | None = Field(None, description="Multiply the parsed value by this; omit to keep the task's scale")


# the only problem a reparse can fix: the command ran to the end, only the regex missed
REPARSABLE = ["no parsable metric value"]


class FinishProposal(BaseModel):
    not_measured: dict[str, str] = Field(default_factory=dict,
                                         description="claim or question id -> why it cannot be measured (only after "
                                                     "attempts)")
    answers: list[AnswerItem] = Field(default_factory=list,
                                      description="Question tasks: one answer per question, with the log or output "
                                                  "file of the run that printed or wrote it")
    summary: str = ""


class ExperimentPatch(BaseModel):
    reasoning: str = Field(description="Why these changes: what the last wake showed and what you decided")
    ledger: LedgerUpdate | None = None
    add_tasks: list[Task] = Field(default_factory=list)
    cancel_task_ids: list[str] = Field(default_factory=list)
    replace: list[Replacement] = Field(default_factory=list)
    reparse: list[Reparse] = Field(default_factory=list,
                                   description="Failed runs that exited 0 but whose metric_regex matched nothing: the "
                                               "runtime reads the same log with the new regex. Never rerun those.")
    finish: FinishProposal | None = Field(None, description="Propose to end the run; the runtime checks it")


# ---------------------------------------------------------------- checks


def filtering_problems(command: str) -> list[str]:
    return [why for rx, why in _FILTERS if rx.search(command)]


def _regex_problem(regex: str) -> str | None:
    try:
        n = re.compile(regex).groups
    except re.error as e:
        return f"metric_regex does not compile: {e}"
    return None if n == 1 else f"metric_regex must have exactly one capture group, has {n}"


def error_signature(output: str) -> str | None:
    """The last error-looking line, with numbers and paths blurred, so repeats of the same failure can be counted."""
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    hits = [l for l in lines if re.search(r"(?i)(error|exception|traceback|not found|no such|killed|timeout)", l)]
    if not hits:
        return None
    sig = re.sub(r"\d+", "N", re.sub(r"(/[\w.\-]+)+", "<path>", hits[-1]))[:200]
    return sig


def progress_lines(output: str) -> int:
    return len(PROGRESS_RE.findall(output))


# ---------------------------------------------------------------- the runtime


AgentExecutor = Callable[[AgentTask, "Runtime"], tuple[bool, dict, str]]
# (task, runtime) -> (ok, artifact as plain data, one-line summary). Raising counts as a failed task.


class Runtime:
    """Task DAG, gates, wakes and the finish gate. `state` is the whole persistent state, as plain data."""

    def __init__(self, ctx: RunContext, *, gates: bool = True, parallel: int = MAX_PARALLEL_DIAGNOSE,
                 state: dict | None = None):
        self.ctx = ctx
        self.gates = gates
        self.parallel = max(1, parallel)  # how many ready diagnosis tasks may run at once
        self.state: dict = state or {
            "tasks": {},  # task_id -> {"spec", "status", "added", "lineage", "attempt", ...}
            "order": [],  # task ids in the order they were added
            "events": 0,  # monotonically increasing event number
            "since_wake": [],  # task ids whose status changed since the last wake
            "stalls": 0,
            "signatures": {},  # error signature -> count
            "smoke_passed": [],  # smoke commands (with workdir) that already passed
            "ledger": {"given_or_verified": [], "to_look_up": [], "to_derive": [], "assumptions": [], "plan": ""},
            "replans": 0,
            "finished": None,  # set when the finish gate accepts: {"not_measured": {...}, "summary": ...}
        }

    # ---- helpers

    @property
    def tasks(self) -> dict[str, dict]:
        return self.state["tasks"]

    def _log(self, event: str, **data) -> None:
        self.state["events"] += 1
        self.ctx.trace.log("runtime", event, n=self.state["events"], **data)

    def _set(self, tid: str, status: str, **fields) -> None:
        t = self.tasks[tid]
        t.update(status=status, **fields)
        if tid not in self.state["since_wake"]:
            self.state["since_wake"].append(tid)
        self._log("task/" + status, task_id=tid, **{k: v for k, v in fields.items() if k != "artifact"})

    @property
    def questions(self):
        """The ReproSpec of a spec run, or None for a paper run."""
        return self.ctx.spec

    def spec(self, tid: str) -> RunTask | AgentTask:
        raw = self.tasks[tid]["spec"]
        return RunTask.model_validate(raw) if raw["kind"] == "run" else AgentTask.model_validate(raw)

    # ---- patches

    def apply(self, patch: ExperimentPatch) -> list[str]:
        """Apply a patch atomically. Returns the problems (empty when applied); a patch with problems changes nothing."""
        problems: list[str] = []
        new_ids = [t.task_id for t in patch.add_tasks]
        dupes = [i for i, n in Counter(new_ids).items() if n > 1] + [i for i in new_ids if i in self.tasks]
        problems += [f"task id {i!r} is already used" for i in dupes]
        known = set(self.tasks) | set(new_ids)
        claims = {c.id for c in self.ctx.task.claims}
        replaced = {r.new_task_id: r.old_task_id for r in patch.replace}
        for r in patch.replace:
            if r.old_task_id not in self.tasks:
                problems.append(f"replace: unknown task {r.old_task_id!r}")
            elif self.tasks[r.old_task_id]["status"] not in ("failed", "pending", "blocked"):
                problems.append(f"replace: {r.old_task_id!r} is {self.tasks[r.old_task_id]['status']}; only failed, "
                                f"blocked or not-started tasks can be replaced")
            if r.new_task_id not in new_ids:
                problems.append(f"replace: {r.new_task_id!r} must be one of this patch's add_tasks")
        for t in patch.add_tasks:
            problems += [f"{t.task_id}: depends on unknown task {d!r}" for d in t.depends_on if d not in known]
            if isinstance(t, RunTask):
                if self.questions is None and t.claim_id not in claims:
                    problems.append(f"{t.task_id}: unknown claim {t.claim_id!r} (claims: {sorted(claims)})")
                problems += [f"{t.task_id}: {p}" for p in self._run_problems(t, replaced.get(t.task_id))]
            elif t.role == "debug" and t.about_task and t.about_task not in known:
                problems.append(f"{t.task_id}: about_task {t.about_task!r} is unknown")
        if self.questions is None:
            problems += self._variant_problems(patch)
        for tid in patch.cancel_task_ids:
            if tid not in self.tasks:
                problems.append(f"cancel: unknown task {tid!r}")
            elif self.tasks[tid]["status"] in ("done", "running"):
                problems.append(f"cancel: {tid!r} is {self.tasks[tid]['status']}")
        reparsed: dict[str, tuple[float, int]] = {}  # task id -> (value, progress lines), all checked before any change
        for r in patch.reparse:
            got = self._reparse_problem(r, patch)
            if isinstance(got, str):
                problems.append(f"reparse {r.task_id}: {got}")
            else:
                reparsed[r.task_id] = got
        if problems:
            self._log("patch/rejected", problems=problems)
            return problems

        if patch.ledger:
            for k, v in patch.ledger.model_dump(exclude_none=True).items():
                self.state["ledger"][k] = v
        for tid in patch.cancel_task_ids:
            self._set(tid, "cancelled")
        for r in patch.reparse:
            spec = self.tasks[r.task_id]["spec"]
            old = {"metric_regex": spec["metric_regex"], "scale": spec["scale"]}
            spec["metric_regex"] = r.metric_regex
            if r.scale is not None:
                spec["scale"] = r.scale
            value, progress = reparsed[r.task_id]
            for k in ("stage", "problems", "signature", "signature_repeats"):
                self.tasks[r.task_id].pop(k, None)
            self._set(r.task_id, "done", value=value, log=self.tasks[r.task_id]["log"], exit_code=0,
                      progress_lines=progress, reparsed_from=old)
            for tid in self.state["order"]:  # tasks blocked on its failure may go again (ready() re-checks the rest)
                t = self.tasks[tid]
                if t["status"] == "blocked" and r.task_id in t["spec"]["depends_on"]:
                    self._set(tid, "pending", reason=f"{r.task_id} was reparsed")
        for r in patch.replace:
            if self.tasks[r.old_task_id]["status"] != "failed":
                self._set(r.old_task_id, "cancelled")
            self.tasks[r.old_task_id]["replaced_by"] = r.new_task_id
        for t in patch.add_tasks:
            old = replaced.get(t.task_id)
            lineage = self.tasks[old]["lineage"] if old else t.task_id
            attempt = self.tasks[old]["attempt"] + 1 if old else 1
            self.tasks[t.task_id] = {"spec": t.model_dump(mode="json"), "status": "pending", "lineage": lineage,
                                     "attempt": attempt, "added": self.state["events"]}
            self.state["order"].append(t.task_id)
            self._log("task/added", task_id=t.task_id, kind=t.kind, lineage=lineage, attempt=attempt)
        for r in patch.replace:  # tasks waiting on the replaced one now wait on its replacement (Cuti rewiring)
            for tid in self.state["order"]:
                t = self.tasks[tid]
                if r.old_task_id in t["spec"]["depends_on"] and t["status"] in ("pending", "blocked"):
                    t["spec"]["depends_on"] = [r.new_task_id if d == r.old_task_id else d for d in t["spec"]["depends_on"]]
                    if t["status"] == "blocked":
                        self._set(tid, "pending", reason=f"rewired to {r.new_task_id}")
        self._log("patch/applied", added=new_ids, cancelled=patch.cancel_task_ids,
                  replaced=[r.model_dump() for r in patch.replace], reparsed=[r.task_id for r in patch.reparse])
        return []

    def _reparse_problem(self, r: Reparse, patch: ExperimentPatch) -> str | tuple[float, int]:
        """Why this reparse cannot be applied, else (the value the new regex reads from the run's log, its progress
        lines). Only a run that ran to the end with exit 0 and missed only its value qualifies, and only from the log
        the sandbox itself wrote (its sha256 is in the sandbox's in-memory manifest, out of the agents' reach)."""
        t = self.tasks.get(r.task_id)
        if t is None:
            return "unknown task"
        if t["spec"]["kind"] != "run":
            return "only run tasks can be reparsed"
        if t["status"] != "failed" or t.get("stage") != "run" or t.get("problems") != REPARSABLE:
            return (f"only a run that exited 0 and failed only with {REPARSABLE[0]!r} can be reparsed "
                    f"(this one is {t['status']}, problems {t.get('problems')}); replace it instead")
        if t.get("replaced_by") or r.task_id in {x.old_task_id for x in patch.replace}:
            return "it is being replaced; reparse it or replace it, not both"
        if p := _regex_problem(r.metric_regex):
            return p
        path = self.ctx.run_dir / t["log"]
        expected = self.ctx.sandbox.manifest.get(path.name)
        if expected is None or not path.is_file() or file_sha256(path) != expected:
            return "its log is not the one the sandbox wrote (changed or missing); rerun it instead"
        _, output = split_log(path.read_text(errors="replace"))
        value = parse_metric(output, r.metric_regex, t["spec"]["scale"] if r.scale is None else r.scale)
        if value is None:
            return f"the new metric_regex also finds no value in {t['log']}; read the log (read_log) and fix the regex"
        progress = progress_lines(output)
        if self.gates and self.questions is None and not progress:  # stage 3 holds for a reparse too
            return "no training progress in the log: the value would not count as evidence"
        return value, progress

    def _run_problems(self, t: RunTask, replaces: str | None) -> list[str]:
        out = []
        if t.metric_regex is None:
            if self.questions is None:
                out.append("metric_regex is required for a claim's run")
        elif p := _regex_problem(t.metric_regex):
            out.append(p)
        if self.gates:  # stage 1: plan check
            out += [f"command {p}; print the full output instead" for p in filtering_problems(t.command)]
            if not t.smoke_command and self.questions is None:
                out.append("smoke_command is required: the same command cut down to a few steps or one epoch")
            elif t.smoke_command:
                out += [f"smoke_command {p}" for p in filtering_problems(t.smoke_command)]
            workdir = self.ctx.sandbox.workspace / t.workdir
            depends_on_setup = any(self.tasks.get(d, {}).get("spec", {}).get("kind") == "agent" for d in t.depends_on)
            if not depends_on_setup and not workdir.is_dir():
                out.append(f"workdir {t.workdir!r} does not exist (depend on the setup task that creates it)")
        if replaces in self.tasks:  # an unknown one is reported by apply
            attempt = self.tasks[replaces]["attempt"] + 1
            if attempt > MAX_REPLACEMENTS:
                out.append(f"lineage {self.tasks[replaces]['lineage']!r} reached {MAX_REPLACEMENTS} attempts: declare "
                           f"the claim not measured or try a different approach under a new task id")
        return out

    def _variant_problems(self, patch: ExperimentPatch) -> list[str]:
        """Exactly one counted variant per claim, across the existing (live) tasks and the patch."""
        gone = set(patch.cancel_task_ids) | {r.old_task_id for r in patch.replace}
        counted: dict[str, set[str]] = {}
        for tid, t in self.tasks.items():
            s = t["spec"]
            if s["kind"] == "run" and s["counts"] and t["status"] != "cancelled" and tid not in gone \
                    and not t.get("replaced_by"):
                counted.setdefault(s["claim_id"], set()).add(s["variant"])
        for t in patch.add_tasks:
            if isinstance(t, RunTask) and t.counts:
                counted.setdefault(t.claim_id, set()).add(t.variant)
        return [f"claim {c!r}: only one variant may count, got {sorted(v)}; mark the others counts=false"
                for c, v in counted.items() if len(v) > 1]

    # ---- execution

    def ready(self) -> list[str]:
        out = []
        for tid in self.state["order"]:
            t = self.tasks[tid]
            if t["status"] != "pending":
                continue
            deps = [self.tasks[d] for d in t["spec"]["depends_on"]]
            if any(d["status"] in ("failed", "cancelled") for d in deps):
                self._set(tid, "blocked", reason="a dependency failed or was cancelled")
            elif all(d["status"] == "done" for d in deps):
                out.append(tid)
        return out

    def step(self, run_agent: AgentExecutor) -> list[str]:
        """Execute the next ready task (or up to MAX_PARALLEL_DIAGNOSE ready diagnosis tasks). Returns the task ids
        executed; [] when nothing is ready."""
        ready = self.ready()
        if not ready:
            return []
        first = self.spec(ready[0])
        if isinstance(first, AgentTask) and first.role == "diagnose":
            batch = [tid for tid in ready if (s := self.spec(tid)).kind == "agent" and s.role == "diagnose"]
            batch = batch[:self.parallel]
            for tid in batch:
                self._set(tid, "running")
            with ThreadPoolExecutor(len(batch)) as pool:
                results = list(pool.map(lambda tid: self._agent(self.spec(tid), run_agent), batch))
            for tid, res in zip(batch, results):
                self._finish_agent(tid, res)
            return batch
        self._set(ready[0], "running")
        if isinstance(first, RunTask):
            self._run(first)
        else:
            self._finish_agent(first.task_id, self._agent(first, run_agent))
        return [ready[0]]

    def _agent(self, task: AgentTask, run_agent: AgentExecutor) -> tuple[bool, dict, str]:
        try:
            return run_agent(task, self)
        except Exception as e:  # a failed agent task is reported to the Planner, not raised
            return False, {}, f"{type(e).__name__}: {e}"

    def _finish_agent(self, tid: str, res: tuple[bool, dict, str]) -> None:
        ok, artifact, summary = res
        self._set(tid, "done" if ok else "failed", summary=summary[:2000], artifact=artifact)

    def _run(self, t: RunTask) -> None:
        sb = self.ctx.sandbox
        if self.gates and t.smoke_command:
            key = f"{t.workdir}::{t.smoke_command}"
            if key not in self.state["smoke_passed"]:  # stage 2: smoke run
                res = sb.run(t.smoke_command, t.workdir, min(SMOKE_TIMEOUT_S, t.timeout_s), tag=f"smoke_{t.task_id}")
                problems = []
                if res.exit_code != 0:
                    problems.append("timed out" if res.exit_code is None else f"exit code {res.exit_code}")
                if self.questions is None and not progress_lines(res.output):
                    problems.append("no training progress in the output (print per-step/epoch losses, e.g. a "
                                    "verbose flag)")
                if t.metric_regex and parse_metric(res.output, t.metric_regex, t.scale) is None:
                    problems.append("metric_regex finds no value in the output")
                log = str(res.log_path.relative_to(self.ctx.run_dir))
                if problems:
                    self._fail(t.task_id, "smoke", problems, res.output, log)
                    return
                self.state["smoke_passed"].append(key)
                self._log("gate/smoke_passed", task_id=t.task_id, log=log)
        res = sb.run(t.command, t.workdir, t.timeout_s, tag=f"exp_{t.task_id}")
        log = str(res.log_path.relative_to(self.ctx.run_dir))
        value = parse_metric(res.output, t.metric_regex, t.scale) if res.ok and t.metric_regex else None
        problems = []
        if res.exit_code != 0:
            problems.append("timed out" if res.exit_code is None else f"exit code {res.exit_code}")
        if value is None and t.metric_regex:
            problems.append("no parsable metric value")
        if self.gates and self.questions is None and not progress_lines(res.output):  # stage 3: evidence check
            problems.append("no training progress in the log: the value would not count as evidence")
        if problems:
            self._fail(t.task_id, "run" if res.exit_code != 0 or value is None or not self.gates else "evidence",
                       problems, res.output, log)
            return
        self._set(t.task_id, "done", value=value, log=log, exit_code=res.exit_code, duration_s=round(res.duration_s, 1),
                  progress_lines=progress_lines(res.output))

    def _fail(self, tid: str, stage: str, problems: list[str], output: str, log: str) -> None:
        sig = error_signature(output) or f"{stage}: {'; '.join(problems)}"
        self.state["signatures"][sig] = self.state["signatures"].get(sig, 0) + 1
        self._set(tid, "failed", stage=stage, problems=problems, log=log, signature=sig,
                  signature_repeats=self.state["signatures"][sig])

    # ---- wakes

    def should_wake(self, executed: list[str]) -> bool:
        if not executed:
            return True  # nothing left to run, or everything is blocked
        return any(self.tasks[t]["status"] == "failed" or self.tasks[t]["spec"]["kind"] == "agent" for t in executed)

    def wake(self) -> dict:
        """What changed since the last wake, plus computed progress fields. Updates the stall counter."""
        changed = [self._view(tid) for tid in self.state["since_wake"]]
        progress = any(c["status"] == "done" for c in changed)
        looping = any(c.get("signature_repeats", 0) >= 2 for c in changed)
        self.state["stalls"] = max(0, self.state["stalls"] - 1) if progress and not looping else self.state["stalls"] + 1
        replan = self.state["stalls"] >= STALL_LIMIT
        if replan:
            self.state["replans"] += 1
            self.state["stalls"] = 0
        self.state["since_wake"] = []
        counts = Counter(t["status"] for t in self.tasks.values())
        view = {"changed": changed, "is_progress_being_made": progress, "is_in_loop": looping, "replan": replan,
                "task_counts": dict(counts), "pending": [tid for tid in self.state["order"]
                                                          if self.tasks[tid]["status"] in ("pending", "running")],
                "claims": self.claim_status(), "budget_left_usd": round(self.ctx.budget.limit_usd - self.ctx.budget.spent_usd, 3)}
        self._log("wake", **{k: v for k, v in view.items() if k != "changed"}, changed=[c["task_id"] for c in changed])
        return view

    def _view(self, tid: str) -> dict:
        t = self.tasks[tid]
        s = t["spec"]
        v = {"task_id": tid, "kind": s["kind"], "status": t["status"], "attempt": t["attempt"]}
        for k in ("value", "log", "stage", "problems", "signature", "signature_repeats", "summary", "reason"):
            if k in t:
                v[k] = t[k]
        if s["kind"] == "run" and self.questions is not None:
            v.update(command=s["command"])
        elif s["kind"] == "run":
            v.update(claim_id=s["claim_id"], seed=s["seed"], variant=s["variant"], counts=s["counts"])
        else:
            v["role"] = s["role"]
        return v

    # ---- claims and finishing

    def counted_values(self) -> dict[str, list[tuple[float, str]]]:
        """claim id -> (value, log) of every finished counted run (all of them passed the gates that were on)."""
        out: dict[str, list[tuple[float, str]]] = {c.id: [] for c in self.ctx.task.claims}
        for tid in self.state["order"]:
            t = self.tasks[tid]
            s = t["spec"]
            if s["kind"] == "run" and s["counts"] and t["status"] == "done":
                out[s["claim_id"]].append((t["value"], t["log"]))
        return out

    def claim_status(self) -> dict[str, dict]:
        if self.questions is not None:  # questions are answered in the finish proposal
            return {}
        need = self.ctx.task.seeds
        vals = self.counted_values()
        return {c: {"values": len(v), "needed": need, "satisfied": len(v) >= need} for c, v in vals.items()}

    def check_finish(self, proposal: FinishProposal) -> list[str]:
        """The finish gate. Problems (empty = accepted); on acceptance the run is marked finished."""
        if self.questions is not None:
            return self._check_answers(proposal)
        problems = []
        status = self.claim_status()
        for claim, st in status.items():
            if st["satisfied"]:
                continue
            reason = proposal.not_measured.get(claim)
            if not reason:
                problems.append(f"{claim}: {st['values']}/{st['needed']} counted values and no not-measured reason")
                continue
            tried = [t for t in self.tasks.values() if t["spec"]["kind"] == "run" and t["spec"]["claim_id"] == claim
                     and t["status"] in ("failed", "done")]
            budget_low = self.ctx.budget.spent_usd >= 0.8 * self.ctx.budget.limit_usd
            if not tried and not budget_low:
                problems.append(f"{claim}: declared not measured, but no run of it was attempted")
        unfinished = [tid for tid in self.state["order"] if self.tasks[tid]["status"] in ("pending", "running")]
        if unfinished:
            problems.append(f"tasks still pending: {unfinished}; cancel them or wait")
        if problems:
            self._log("finish/rejected", problems=problems)
            return problems
        self.state["finished"] = proposal.model_dump()
        self._log("finish/accepted", not_measured=proposal.not_measured)
        return []

    def _check_answers(self, proposal: FinishProposal) -> list[str]:
        """Finish gate of a spec run: every question answered (or not measured after attempts), and with gates on,
        every answer found in this run's own output."""
        from .corebench import provenance_problems
        self.state["proposed_answers"] = [a.model_dump(mode="json") for a in proposal.answers]
        problems = answer_problems(self.questions, proposal.answers, proposal.not_measured)
        attempted = any(t["spec"]["kind"] == "run" and t["status"] in ("failed", "done") for t in self.tasks.values())
        budget_low = self.ctx.budget.spent_usd >= 0.8 * self.ctx.budget.limit_usd
        if proposal.not_measured and not attempted and not budget_low:
            problems.append("questions declared not measured, but no run was attempted")
        if self.gates and not problems:
            problems += provenance_problems(self.ctx, proposal.answers)
        unfinished = [tid for tid in self.state["order"] if self.tasks[tid]["status"] in ("pending", "running")]
        if unfinished:
            problems.append(f"tasks still pending: {unfinished}; cancel them or wait")
        if problems:
            self._log("finish/rejected", problems=problems)
            return problems
        self.state["finished"] = proposal.model_dump(mode="json")
        self._log("finish/accepted", not_measured=proposal.not_measured, answered=len(proposal.answers))
        return []

    def answers(self) -> list[dict]:
        """The accepted answers, else the last proposed ones (a run that ends without acceptance is scored as is)."""
        if self.state.get("finished") and "answers" in self.state["finished"]:
            return self.state["finished"]["answers"]
        return self.state.get("proposed_answers", [])

    def metrics(self, notes: str = "") -> Metrics:
        claims = [ClaimMeasurement(claim_id=c, values=[v for v, _ in vals], evidence=[log for _, log in vals])
                  for c, vals in self.counted_values().items() if vals]
        return Metrics(claims=claims, notes=notes)

    def digest(self) -> str:
        """A short fingerprint of the DAG, for logs."""
        return hashlib.sha256(repr([(t, self.tasks[t]["status"]) for t in self.state["order"]]).encode()).hexdigest()[:12]
