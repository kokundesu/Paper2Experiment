# Agent evaluation: CORE-Bench dev, runs since 20261018-1000

45 tasks, workflows: A (single), B (fixed), D (planner_workers); one run per task and workflow (latest).

Unscored tasks (every question too noisy to score; left out of the rates below): cb-3249574, cb-5286757, cb-9370340

## Pass rates

| Version | Runs | Full | 95% CI | Tolerance-only | HAL rule | Question acc. | Mean cost | Total cost | Median wall | Total wall |
|---|---|---|---|---|---|---|---|---|---|---|
| A | 42 | 32/42 (76%) | 61%–87% | 33/42 | 27/42 | 84/97 (87%) | $0.012 | $0.52 | 2.7 min | 6.1 h |
| B | 42 | 34/42 (81%) | 67%–90% | 34/42 | 27/42 | 88/97 (91%) | $0.018 | $0.75 | 3.7 min | 6.3 h |
| D | 42 | 34/42 (81%) | 67%–90% | 34/42 | 27/42 | 87/97 (90%) | $0.026 | $1.10 | 4.8 min | 7.8 h |

## Paired comparisons (tasks both versions ran)

| Pair | Tasks | Both full | Only first | Only second | Neither | McNemar exact p |
|---|---|---|---|---|---|---|
| A vs B | 42 | 30 | 2 | 4 | 6 | 0.688 |
| A vs D | 42 | 31 | 1 | 3 | 7 | 0.625 |
| B vs D | 42 | 32 | 2 | 2 | 6 | 1.000 |

## Failure taxonomy (runs that are not full)

| Version | setup_failed | budget_or_turns | error | no_answers | provenance | partial | wrong_answers |
|---|---|---|---|---|---|---|---|
| A | 0 | 1 | 0 | 1 | 1 | 3 | 4 |
| B | 0 | 1 | 0 | 0 | 0 | 2 | 5 |
| D | 0 | 1 | 0 | 0 | 0 | 3 | 4 |

## Skill usage

| Version | Library versions | Runs reading any skill | Reads per skill |
|---|---|---|---|
| A | 4 | 32/45 | r-environment 14, find-entry-point 13, legacy-environment 4, data-acquisition 3, notebook-execution 2, run-protocol 2 |
| B | 4 | 18/45 | r-environment 10, find-entry-point 3, notebook-execution 3, legacy-environment 2, data-acquisition 2, cpu-runtime 1, run-protocol 1 |
| D | 4 | 28/45 | r-environment 24, legacy-environment 8, cpu-runtime 5, macos-shell-and-paths 1, data-acquisition 1, find-entry-point 1, notebook-execution 1 |

## Per task

| Task | A | B | D |
|---|---|---|---|
| cb-0201225 | full | full | full |
| cb-0220918 | partial | full | partial |
| cb-0238624 | full | full | full |
| cb-0325493 | full | full | partial |
| cb-0396930 | full | full | full |
| cb-0940461 | full | full | full |
| cb-1108125 | full | full | full |
| cb-1324693 | full | full | full |
| cb-1683542 | full | full | full |
| cb-1854976 | full | full | full |
| cb-1906954 | full | full | full |
| cb-2011424 | full | fail (wrong_answers) | full |
| cb-2061060 | full | full | full |
| cb-2916503 | full | full | full |
| cb-3137115 | full | full | full |
| cb-3249574 | unscored | unscored | unscored |
| cb-3269870 | partial | partial | partial |
| cb-3272782 | full | full | full |
| cb-3497606 | full | full | full |
| cb-3894632 | full | full | full |
| cb-4098236 | full | full | full |
| cb-4600160 | full | full | full |
| cb-4645832 | full | fail (budget_or_turns) | full |
| cb-4807644 | partial | partial | fail (wrong_answers) |
| cb-4884085 | fail (wrong_answers) | fail (wrong_answers) | fail (wrong_answers) |
| cb-5286757 | unscored | unscored | unscored |
| cb-5367566 | full | full | full |
| cb-5496369 | full | full | full |
| cb-5777882 | fail (wrong_answers) | fail (wrong_answers) | fail (wrong_answers) |
| cb-5975162 | full | full | full |
| cb-6133093 | fail (wrong_answers) | fail (wrong_answers) | fail (wrong_answers) |
| cb-6460826 | full | full | full |
| cb-6746514 | full | full | full |
| cb-7038571 | full | full | full |
| cb-7156696 | full | full | full |
| cb-7935517 | fail (no_answers) | full | full |
| cb-7981862 | fail (wrong_answers) | fail (wrong_answers) | fail (budget_or_turns) |
| cb-8197429 | full | full | full |
| cb-8912293 | partial (provenance) | full | full |
| cb-9022937 | full | full | full |
| cb-9070543 | full | full | full |
| cb-9166182 | full | full | full |
| cb-9168639 | full | full | full |
| cb-9348218 | fail (budget_or_turns) | full | full |
| cb-9370340 | unscored | unscored | unscored |

## Errors

- A cb-9348218: BudgetExceeded: single_agent: no submission after 80 turns
- B cb-4645832: BudgetExceeded: env_agent: no submission after 50 turns
- B cb-9070543: BudgetExceeded: environment not ready: Dose_Response_Script.Rmd rendered fully (exit 0, ~31 s; log dose.log); outputs in results/Dose_Response_Script_Output (7 
- B cb-9348218: BudgetExceeded: env_agent: no submission after 50 turns
- D cb-7981862: BudgetExceeded: planner: no submission after 16 turns

Small samples: with about 20 tasks, a difference of a few tasks is within noise; read the intervals and the exact p-values before ranking versions.
