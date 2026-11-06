# Agent evaluation: CORE-Bench dev, runs since 20261017-2346

20 tasks, workflows: A (single), B (fixed), D (planner_workers); one run per task and workflow (latest).

Unscored tasks (every question too noisy to score; left out of the rates below): cb-3249574, cb-5286757, cb-9370340

## Pass rates

| Version | Runs | Full | 95% CI | Tolerance-only | HAL rule | Question acc. | Mean cost | Total cost | Median wall | Total wall |
|---|---|---|---|---|---|---|---|---|---|---|
| A | 17 | 13/17 (76%) | 53%–90% | 13/17 | 10/17 | 39/45 (87%) | $0.008 | $0.13 | 1.4 min | 0.6 h |
| B | 17 | 12/17 (71%) | 47%–87% | 12/17 | 9/17 | 33/45 (73%) | $0.011 | $0.18 | 2.5 min | 0.8 h |
| D | 17 | 13/17 (76%) | 53%–90% | 13/17 | 10/17 | 39/45 (87%) | $0.018 | $0.31 | 2.6 min | 1.3 h |

## Paired comparisons (tasks both versions ran)

| Pair | Tasks | Both full | Only first | Only second | Neither | McNemar exact p |
|---|---|---|---|---|---|---|
| A vs B | 17 | 12 | 1 | 0 | 4 | 1.000 |
| A vs D | 17 | 13 | 0 | 0 | 4 | 1.000 |
| B vs D | 17 | 12 | 0 | 1 | 4 | 1.000 |

## Failure taxonomy (runs that are not full)

| Version | setup_failed | budget_or_turns | error | no_answers | provenance | partial | wrong_answers |
|---|---|---|---|---|---|---|---|
| A | 0 | 0 | 0 | 3 | 0 | 0 | 1 |
| B | 3 | 0 | 0 | 0 | 0 | 0 | 2 |
| D | 0 | 0 | 0 | 3 | 0 | 0 | 1 |

## Skill usage

| Version | Library versions | Runs reading any skill | Reads per skill |
|---|---|---|---|
| A | 3 | 12/20 | find-entry-point 6, data-acquisition 3, legacy-environment 1, run-protocol 1, r-environment 1, cpu-runtime 1, notebook-execution 1 |
| B | 3 | 9/20 | find-entry-point 5, data-acquisition 2, cpu-runtime 1, notebook-execution 1 |
| D | 3 | 8/20 | legacy-environment 5, cpu-runtime 3, data-acquisition 2 |

## Per task

| Task | A | B | D |
|---|---|---|---|
| cb-0201225 | full | full | full |
| cb-0220918 | fail (no_answers) | fail (setup_failed) | fail (no_answers) |
| cb-0238624 | fail (no_answers) | fail (setup_failed) | fail (no_answers) |
| cb-0396930 | full | full | full |
| cb-0940461 | full | full | full |
| cb-1854976 | full | full | full |
| cb-2011424 | full | full | full |
| cb-3249574 | unscored | unscored | unscored |
| cb-3272782 | full | full | full |
| cb-3894632 | full | full | full |
| cb-4098236 | full | full | full |
| cb-4645832 | fail (no_answers) | fail (setup_failed) | fail (no_answers) |
| cb-4884085 | fail (wrong_answers) | fail (wrong_answers) | fail (wrong_answers) |
| cb-5286757 | unscored | unscored | unscored |
| cb-5367566 | full | full | full |
| cb-5975162 | full | full | full |
| cb-6460826 | full | full | full |
| cb-7038571 | full | full | full |
| cb-9166182 | full | fail (wrong_answers) | full |
| cb-9370340 | unscored | unscored | unscored |

## Errors

- B cb-0220918: BudgetExceeded: environment not ready: cd code && ../.venv/bin/python evaluate.py -> FAILS at restore setup, not a run. Sequence of failures: (1) ../results mis
- B cb-0238624: BudgetExceeded: environment not ready: FAILED at data loading. Original script: ModuleNotFoundError 'keras.layers.merge' (Keras 3 removed it). After patching th
- B cb-4645832: BudgetExceeded: environment not ready: FAILED at data loading. `python main_hyper.py --model-name GNNTARnet --dataset-name ihdp_a --tuner-name random` gets thro

Small samples: with about 20 tasks, a difference of a few tasks is within noise; read the intervals and the exact p-values before ranking versions.
