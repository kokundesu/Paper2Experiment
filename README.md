# Paper2Experiment: A Multi-Agent LLM System for Reproducing Engineering Research Papers

Paper2Experiment (package `p2e`, v4) is an LLM agent system that reproduces the results of research papers. It reads
the paper and its official repository, sets up the environment and runs the experiments in a sandbox, then reports
the values it measured together with a diagnosis of every mismatch. Runs are scored against hidden ground truth by a
deterministic evaluator, with no LLM judge.

The repository compares three workflow designs (A, B, D) on the same tasks, with the same sandbox, model layer,
skill library and evaluator:

- **A: a single ReAct agent** that holds every tool;
- **B: a fixed multi-agent pipeline**, where code routes the work between six LLM roles;
- **D: an LLM Planner over a verifying runtime**, with an isolated worker sub-agent for each agent task.

The main benchmark is [CORE-Bench](docs/corebench-inventory.md). The dev split is the original train set and the test
split is the v1.1 mainline. The 20 self-built papers in `Base/benchmark/v4` form a supplementary set. The design
follows the close reading in [docs/reading-notes.md](docs/reading-notes.md) and the plan in
[docs/v4-plan.md](docs/v4-plan.md) (both in Chinese).

## Results

**CORE-Bench test, Hard level.** The test set has 30 CPU tasks with 46 questions; 33 of the questions need reading a
figure. The model was Haiku55 and the skill library was v5, frozen before the run. Each task and workflow pair ran
once, with a budget of $5 per run. Full report: [Base/runs/reports/cb_test_summary.md](Base/runs/reports/cb_test_summary.md).

| Workflow | Fully correct | 95% CI (Wilson) | HAL rule | Questions correct | Mean cost / run |
|---|---|---|---|---|---|
| A `single` | 29/30 (97%) | 83–99% | 24/30 | 44/46 | $0.013 |
| B `fixed` | 28/30 (93%) | 79–98% | 25/30 | 43/46 | $0.017 |
| D `planner_workers` | 26/30 (87%) | 70–95% | 22/30 | 40/46 | $0.025 |

None of the paired differences is significant (exact McNemar test, p ≥ 0.25). A scores highest at the lowest cost.
Our rule is stricter than HAL's in one way: an answer must also be proven to come from the run itself. It is more
lenient in another, because it accepts unrounded answers, in line with the v1.1 fixes. Both sets of numbers are
reported. One of D's failures was an evaluator bug (an unhandled `KeyError` in the patch check). It has been fixed and
covered by a regression test.

**CORE-Bench dev, round 3.** This round has 42 scored tasks and three groups of 135 runs each. Summary:
[Base/runs/reports/cb_dev_round3_summary.md](Base/runs/reports/cb_dev_round3_summary.md).

| Group | A | B | D |
|---|---|---|---|
| Haiku55, skills v5 | 32 (76%) | 33 (79%) | 35 (83%) |
| Sonnet55, skills v5 | 31 (74%) | 33 (79%) | 36 (86%) |
| Haiku55, skills off | 31 (74%) | 33 (79%) | 31 (74%) |

Three observations stand out:

- **D leads with skills on, but not significantly.** D ranks first in both skills-on groups, yet p > 0.1 in every
  paired test. With skills off, its advantage disappears.
- **Sonnet55 costs 7.6× as much with no gain.** It reached exactly the same total as Haiku55: 100 fully correct
  runs in each group. On these tasks, the bottleneck is getting the environment installed and the programs to run to
  completion, not model capability.
- **The ranking flips between splits.** D is best on dev and worst on test. At this sample size, the three designs
  cannot be told apart.

## Versions

| | Workflow name | Who plans | Who verifies runs | Context |
|---|---|---|---|---|
| **A** [SingleAgent](SingleAgent/) | `single` | one ReAct agent, all tools | the evaluator, at the end | one |
| **B** [FixedPipeline](Multiagent/FixedPipeline/) | `fixed` | code: a fixed six-role pipeline | a Result Reviewer once, the evaluator at the end | one per role |
| **D** [PlannerWorkers](Multiagent/PlannerWorkers/) | `planner_workers` | one LLM Planner (task-DAG patches) | the runtime: plan check, smoke run, evidence check; only the runtime ends a run | Planner + a worker per agent task |

The comparison is between three whole designs: a ReAct harness (A), a code-routed role pipeline (B), and an LLM
planner over a verifying runtime with isolated workers (D). Versions C (D without workers) and C- (C without gates)
were run in the first development round. They are kept only as ablation switches in D's code
(`PlannerRuntimeWorkflow(ctx, gates=..., workers=...)`) and are not part of the comparison. All three versions read
the same skill library through the same tool; `P2E_SKILLS=off` runs without it.

## How it works

**Sandbox.** Every run gets its own workspace outside the project tree, with timeouts, a scrubbed environment (API
keys removed) and a guard that blocks commands touching the benchmark, `case.yaml` or `.env`. The full output of
every command goes to its own log, and the sha256 of each log is recorded. See
[Base/README.md](Base/README.md#sandbox-limits) for the limits.

**Objective scoring.** An answer counts only if it lies within the pre-registered tolerance *and* a log the sandbox
wrote, unchanged since, shows that the run actually produced it. For a figure question, viewing an image this run
generated also counts as proof. The tolerance criterion is given to the agents in their brief; the target values stay
hidden.

**Failure diagnosis.** When a number does not match the paper, the agents must explain why. They write a
`discrepancy_report.json` with a root-cause category, competing hypotheses and the evidence for each. The evaluator
grades the report on detection, false success, attribution and strict attribution, still without an LLM.

**Skill library.** [skills/](skills/) holds the reusable know-how every agent can read through the `read_skill` tool,
for example `r-environment`, `legacy-environment` and `notebook-execution`. The library is upgraded round by round from
development runs (digest → curator → leakage check → new version) and frozen before any test run.

**Demo.** [Base/demo-web](Base/demo-web/) is a chat interface. The user says what to reproduce, and the assistant
turns the request into a task, runs the chosen workflow and model, and shows a live graph of the agents. At the end
it compares each answer with the value the paper reports.

## Layout

```
Base/                         shared infrastructure (package p2e), benchmark cases, shared tests
  p2e/sandbox.py              per-run workspace, timeouts, scrubbed env, command guard, one log per command (+ sha256)
  p2e/llm.py                  agent loop as a LangGraph subgraph; every model-visible message is recorded in the
                              trace; tool pipeline hooks (pre guards, post hooks); converse() continues a conversation
  p2e/models.py, models.yaml  model profiles (Anthropic, OpenAI, OpenAI-compatible endpoints), tiered pricing
  p2e/runtime.py              task DAG, three verification gates, event-driven wakes with deltas, stall counter,
                              finish gate: the substrate of version D
  p2e/skills.py               skill library shared by every agent (read_skill tool), upgraded round by round from
                              development runs (digest -> curator -> leakage check -> new version), frozen before tests
  p2e/corebench.py, spec.py   CORE-Bench adapter (dev/test splits) and the ReproSpec task format
  p2e/runner.py, evaluator.py run setup, deterministic executor, objective scoring (tolerance + log evidence)
  p2e/versions.py             discovers the version folders below; `p2e run --workflow <name>`
  p2e/workflows/deterministic.py   built-in baseline without an LLM
  p2e/demo.py, web/           demo backend (prompt -> spec -> run -> compare) and the web UIs
  demo-web/                   demo frontend (Vite + React)
  benchmark/<case>/           task.yaml (what agents see), case.yaml (hidden ground truth)
  runs/reports/               result reports of the CORE-Bench rounds
SingleAgent/                  A
Multiagent/FixedPipeline/     B
Multiagent/PlannerWorkers/    D (holds the shared Planner + runtime code; switches gates/workers for ablations)
skills/                       the skill library: <name>/SKILL.md, CHANGELOG.md, history/, library.yaml
docs/                         reading notes, the v4 plan, CORE-Bench inventory
conftest.py, pytest.ini       fixtures and test paths for all folders
```

Each version folder has a `workflow.py` (defines `NAME`, `DESCRIPTION`, `run(ctx)`), a README and its own tests.

## Getting started

**Requirements:** Python 3.11 and [uv](https://docs.astral.sh/uv/). The demo frontend also needs Node.js.

```bash
uv venv --python 3.11.16 .venv                  # versions pinned in Base/uv.lock
(cd Base && uv export --frozen --extra dev --no-hashes --no-emit-project) | uv pip sync --python .venv/bin/python -
uv pip install --python .venv/bin/python -e "Base[dev]" --no-deps
cp Base/.env.example Base/.env                  # then fill in ANTHROPIC_API_KEY and/or OPENAI_API_KEY
.venv/bin/python -m pytest                      # offline tests of Base and every version (no API calls)
```

Model profiles (`haiku55`, `sonnet55`, `luna`, `sol`, ...) are defined in [Base/models.yaml](Base/models.yaml).
Settings, budgets, the evaluator and the sandbox are described in [Base/README.md](Base/README.md).

## Usage

```bash
# CORE-Bench
.venv/bin/p2e corebench overview                # tasks and how our tolerance grades them
.venv/bin/p2e corebench run downloaded --split dev --workflow single fixed planner_workers --model haiku55 --update-skills
.venv/bin/p2e corebench report --split test     # summary report of finished runs

# supplementary paper set
.venv/bin/p2e run --case <v4 case> --workflow single fixed planner_workers --model haiku55
.venv/bin/p2e resume Base/runs/<run_dir>        # continue an interrupted paper run of B or D

# skill library
.venv/bin/p2e skills status | update <run dirs> | freeze "<reason>"

# results and UIs
.venv/bin/p2e table                             # all runs so far
.venv/bin/p2e serve                             # web UI: live view of any run, workflow comparison
.venv/bin/p2e demo serve                        # demo chat UI at http://127.0.0.1:8780
```

Build the demo frontend once, and again after frontend changes, before running `p2e demo serve`:

```bash
cd Base/demo-web && npm install && npm run build
```

## Status

- **Done:** all three workflows, the evaluator, the skill library (v5, frozen), three CORE-Bench dev rounds, the
  CORE-Bench test run, and the demo UI.
- **Open:** the test run was single-shot, so repeated runs would tighten the confidence intervals. The supplementary
  v4 paper set was last run in development round 1 (2026-10-17), before the final versions.

Project history before v4 (EE6008, single agent vs fixed pipeline): [Base/docs/OVERVIEW.en.md](Base/docs/OVERVIEW.en.md)
· [Base/docs/OVERVIEW.zh.md](Base/docs/OVERVIEW.zh.md).
