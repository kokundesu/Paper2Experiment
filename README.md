# Paper2Exp

Paper2Experiment v4: an LLM agent system that reproduces results of research papers from the paper and the official
repository, runs the experiments in a sandbox, and scores them against hidden ground truth without an LLM judge.
This repository compares three workflow versions (A, B, D) on the same tasks, with the same sandbox, model layer,
skill library and evaluator. The main benchmark is CORE-Bench (dev: the original train set; test: v1.1 mainline);
the 20 self-built papers of `Base/benchmark/v4` are a supplementary set. See [docs/corebench-inventory.md](docs/corebench-inventory.md).

The design of the new versions follows the close reading in [docs/reading-notes.md](docs/reading-notes.md) and the
plan in [docs/v4-plan.md](docs/v4-plan.md) (both in Chinese).

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
  benchmark/<case>/           task.yaml (what agents see), case.yaml (hidden ground truth)
SingleAgent/                  A
Multiagent/FixedPipeline/     B
Multiagent/PlannerWorkers/    D (holds the shared Planner + runtime code; switches gates/workers for ablations)
skills/                       the skill library: <name>/SKILL.md, CHANGELOG.md, history/, library.yaml
docs/                         reading notes and the v4 plan
conftest.py, pytest.ini       fixtures and test paths for all folders
```

Each version folder has a `workflow.py` (defines `NAME`, `DESCRIPTION`, `run(ctx)`), a README and its own tests.

## Versions

| | Workflow name | Who plans | Who verifies runs | Context |
|---|---|---|---|---|
| **A** [SingleAgent](SingleAgent/) | `single` | one ReAct agent, all tools | the evaluator, at the end | one |
| **B** [FixedPipeline](Multiagent/FixedPipeline/) | `fixed` | code: a fixed six-role pipeline | a Result Reviewer once, the evaluator at the end | one per role |
| **D** [PlannerWorkers](Multiagent/PlannerWorkers/) | `planner_workers` | one LLM Planner (task-DAG patches) | the runtime: plan check, smoke run, evidence check; only the runtime ends a run | Planner + a worker per agent task |

The comparison is between three whole designs: a ReAct harness (A), a code-routed role pipeline (B), and an LLM
planner over a verifying runtime with isolated workers (D). Versions C (D without workers) and C- (C without gates)
were run in the first development round and are kept only as ablation switches of D's code
(`PlannerRuntimeWorkflow(ctx, gates=..., workers=...)`); they are not part of the comparison. All three versions
read the same skill library through the same tool; `P2E_SKILLS=off` runs without it.

## Usage

```bash
uv venv --python 3.11.16 .venv                  # versions pinned in Base/uv.lock
(cd Base && uv export --frozen --extra dev --no-hashes --no-emit-project) | uv pip sync --python .venv/bin/python -
uv pip install --python .venv/bin/python -e "Base[dev]" --no-deps
.venv/bin/python -m pytest                      # offline tests of Base and every version (no API calls)
.venv/bin/p2e corebench run downloaded --split dev --workflow single fixed planner_workers --model haiku55 --update-skills
.venv/bin/p2e run --case <v4 case> --workflow single fixed planner_workers --model haiku55   # supplementary set
.venv/bin/p2e skills status | update <run dirs> | freeze "<reason>"
.venv/bin/p2e resume Base/runs/<run_dir>        # continue an interrupted paper run of B or D
.venv/bin/p2e table                             # all runs so far
.venv/bin/p2e serve                             # web UI (live view of any version; the comparison page still
                                                # compares single vs the fixed pipeline only)
```

API keys live in `Base/.env` (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`); see [Base/README.md](Base/README.md) for
settings, budgets, the evaluator and the sandbox.

## Status

The code and the offline tests are done; no version has been run on a real paper yet. The comparison will run on a
new held-out dataset of papers that is still to be assembled (the five papers of the v3 test set informed this design
and now count as development cases).
