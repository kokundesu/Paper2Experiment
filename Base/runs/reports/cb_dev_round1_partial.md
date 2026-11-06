# Agent evaluation: CORE-Bench dev, runs since 20261017-2346

18 tasks, workflows: A (single), B (fixed), D (planner_workers); one run per task and workflow (latest).

## Pass rates

| Version | Runs | Full | 95% CI | Tolerance-only | HAL rule | Question acc. | Mean cost | Total cost | Median wall | Total wall |
|---|---|---|---|---|---|---|---|---|---|---|
Unscored tasks (every question too noisy to score; left out of the rates below): cb-3249574, cb-5286757

| A | 16 | 12/16 (75%) | 51%–90% | 12/16 | 9/16 | 33/39 (85%) | $0.007 | $0.11 | 1.4 min | 0.5 h |
| B | 16 | 12/16 (75%) | 51%–90% | 12/16 | 9/16 | 33/39 (85%) | $0.010 | $0.15 | 2.3 min | 0.7 h |
| D | 15 | 11/15 (73%) | 48%–89% | 11/15 | 8/15 | 32/38 (84%) | $0.016 | $0.24 | 2.6 min | 1.1 h |

## Paired comparisons (tasks both versions ran)

| Pair | Tasks | Both full | Only first | Only second | Neither | McNemar exact p |
|---|---|---|---|---|---|---|
| A vs B | 16 | 12 | 0 | 0 | 4 | 1.000 |
| A vs D | 15 | 11 | 0 | 0 | 4 | 1.000 |
| B vs D | 15 | 11 | 0 | 0 | 4 | 1.000 |

## Failure taxonomy (runs that are not full)

| Version | setup_failed | budget_or_turns | error | no_answers | provenance | partial | wrong_answers |
|---|---|---|---|---|---|---|---|
| A | 0 | 0 | 0 | 3 | 0 | 0 | 1 |
| B | 3 | 0 | 0 | 0 | 0 | 0 | 1 |
| D | 0 | 0 | 0 | 3 | 0 | 0 | 1 |

## Skill usage

| Version | Library versions | Runs reading any skill | Reads per skill |
|---|---|---|---|
| A | 3 | 10/18 | find-entry-point 5, data-acquisition 3, legacy-environment 1, run-protocol 1, r-environment 1, cpu-runtime 1 |
| B | 3 | 9/18 | find-entry-point 5, data-acquisition 2, cpu-runtime 1, notebook-execution 1 |
| D | 3 | 7/17 | legacy-environment 4, cpu-runtime 3, data-acquisition 2 |

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
| cb-7038571 | full | full | - |

## Errors

- B cb-0220918: BudgetExceeded: environment not ready: cd code && ../.venv/bin/python evaluate.py -> FAILS at restore setup, not a run. Sequence of failures: (1) ../results mis
- B cb-0238624: BudgetExceeded: environment not ready: FAILED at data loading. Original script: ModuleNotFoundError 'keras.layers.merge' (Keras 3 removed it). After patching th
- B cb-4645832: BudgetExceeded: environment not ready: FAILED at data loading. `python main_hyper.py --model-name GNNTARnet --dataset-name ihdp_a --tuner-name random` gets thro

Small samples: with about 20 tasks, a difference of a few tasks is within noise; read the intervals and the exact p-values before ranking versions.
