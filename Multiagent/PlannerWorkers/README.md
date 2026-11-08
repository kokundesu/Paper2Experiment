# D: PlannerWorkers (`planner_workers`)

One LLM Planner, the only planner, over the deterministic runtime of [`p2e.runtime`](../../Base/p2e/runtime.py), with
a worker sub-agent for every agent task. Design sources: DeepSeek Harness / Cuti (single planner, declarative patches,
runtime as source of truth, event-driven wakes), HiRAS (a supervisor that inspects and re-invokes), MAST (verify at
several stages; only the verifier ends a run), Magentic-One (task and progress ledgers, stall-triggered re-planning),
AutoReproduce (dry run before training), Anthropic's multi-agent research system (isolated worker contexts).

**Loop.** The Planner reads the task and each runtime update and submits an `ExperimentPatch`: tasks to add (with
dependencies), cancel or replace, ledger updates, or a finish proposal. The runtime applies a patch atomically or
returns its problems, executes ready tasks, and wakes the Planner on a failure, a finished agent task, or when nothing
is left, with only what changed plus computed progress fields.

**Reparse.** A run that exited 0 and failed only because its `metric_regex` matched nothing is not run again: the
Planner submits a `reparse` with a corrected regex, and the runtime reads the same log, after checking its sha256
against the sandbox's manifest. Added on 2026-11-08 after a demo run re-trained for six minutes only because the value
printed as `tensor(-21.86)`; runs before that date may have rerun in this situation instead.

**Tasks.** `run`: one experiment run. `agent`: setup, debug or diagnose, written as a delegation (objective, tools and
sources, boundaries, context references, done criteria, effort). Each agent task goes to a fresh worker that sees
only the delegation and returns a structured report (SetupReport, DebugReport, ClaimDiagnosis); diagnosis tasks run
up to three at a time; workers never talk to each other and each has its own budget share.

**Verification gates (runtime, deterministic).** (1) Plan check when a run is added. (2) Smoke run of the cut-down
command. (3) Evidence check of the full run's log. On spec runs (CORE-Bench) the finish gate also checks that every
answer came from this run's output, without revealing whether it is right.

**Ledgers and finishing.** As before: the Planner keeps the task ledger, the runtime computes progress; three stalls
reset the Planner's conversation from the ledger; more than three re-plans end the run; only the runtime ends a run.

**Ablation switches.** `PlannerRuntimeWorkflow(ctx, gates=..., workers=...)`: `workers=False` is the round-1 version
C (agent tasks in the Planner's own context), `gates=False, workers=False` the round-1 version C-. They are kept for
the appendix and the tests, not for the comparison.

Tests: [tests/](tests/) (`test_planner_core.py` and `test_planner_spec.py` exercise the shared code with
`workers=False`; `test_ablation_nogates.py` the gates switch; `test_planner_workers.py` the workers).
