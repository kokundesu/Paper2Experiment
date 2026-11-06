# Agent evaluation: CORE-Bench dev, runs since 20261027-1050, sonnet55, skills on

45 tasks, workflows: A (single), B (fixed), D (planner_workers); one run per task and workflow (latest).

Unscored tasks (every question too noisy to score; left out of the rates below). Under the HAL rule they still count, so their HAL result is listed here:

| Task | A | B | D |
|---|---|---|---|
| cb-3249574 | HAL pass | HAL pass | HAL pass |
| cb-5286757 | HAL pass | HAL pass | HAL fail |
| cb-9370340 | HAL pass | HAL pass | HAL pass |

## Pass rates

| Version | Runs | Full | 95% CI | Tolerance-only | HAL rule | Question acc. | Mean cost | Total cost | Median wall | Total wall |
|---|---|---|---|---|---|---|---|---|---|---|
| A | 42 | 31/42 (74%) | 59%–85% | 34/42 | 28/42 | 86/97 (89%) | $0.081 | $3.41 | 1.6 min | 3.3 h |
| B | 42 | 33/42 (79%) | 64%–88% | 35/42 | 29/42 | 86/97 (89%) | $0.150 | $6.29 | 2.6 min | 5.8 h |
| D | 42 | 36/42 (86%) | 72%–93% | 36/42 | 26/42 | 90/97 (93%) | $0.167 | $7.02 | 2.4 min | 4.9 h |

## Paired comparisons (tasks both versions ran)

| Pair | Tasks | Both full | Only first | Only second | Neither | McNemar exact p |
|---|---|---|---|---|---|---|
| A vs B | 42 | 29 | 2 | 4 | 7 | 0.688 |
| A vs D | 42 | 30 | 1 | 6 | 5 | 0.125 |
| B vs D | 42 | 32 | 1 | 4 | 5 | 0.375 |

## Failure taxonomy (runs that are not full)

| Version | setup_failed | budget_or_turns | error | no_answers | provenance | partial | wrong_answers |
|---|---|---|---|---|---|---|---|
| A | 0 | 0 | 0 | 0 | 3 | 4 | 4 |
| B | 0 | 0 | 1 | 0 | 2 | 3 | 3 |
| D | 0 | 0 | 0 | 0 | 0 | 2 | 4 |

## Skill usage

| Version | Library versions | Runs reading any skill | Reads per skill |
|---|---|---|---|
| A | 5 | 17/45 | r-environment 14, find-entry-point 1, cpu-runtime 1, data-acquisition 1 |
| B | 5 | 12/45 | r-environment 10, data-acquisition 1, find-entry-point 1 |
| D | 5 | 15/45 | r-environment 16, data-acquisition 1, find-entry-point 1 |

## Per task

| Task | A | B | D |
|---|---|---|---|
| cb-0201225 | full | full | full |
| cb-0220918 | full | full | full |
| cb-0238624 | full | full | full |
| cb-0325493 | full | full | full |
| cb-0396930 | full | full | full |
| cb-0940461 | full | full | fail (wrong_answers) |
| cb-1108125 | full | full | full |
| cb-1324693 | partial (provenance) | full | full |
| cb-1683542 | full | full | full |
| cb-1854976 | full | full | full |
| cb-1906954 | full | full | full |
| cb-2011424 | fail (wrong_answers) | full | full |
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
| cb-4645832 | full | full | full |
| cb-4807644 | partial | partial | partial |
| cb-4884085 | fail (wrong_answers) | fail (wrong_answers) | fail (wrong_answers) |
| cb-5286757 | unscored | unscored | unscored |
| cb-5367566 | full | full | full |
| cb-5496369 | partial | full | full |
| cb-5777882 | full | fail (wrong_answers) | full |
| cb-5975162 | full | full | full |
| cb-6133093 | fail (wrong_answers) | fail (wrong_answers) | fail (wrong_answers) |
| cb-6460826 | full | full | full |
| cb-6746514 | full | partial | full |
| cb-7038571 | full | full | full |
| cb-7156696 | full | full | full |
| cb-7935517 | full | full | full |
| cb-7981862 | fail (wrong_answers) | fail (error) | fail (wrong_answers) |
| cb-8197429 | partial (provenance) | fail (provenance) | full |
| cb-8912293 | partial | full | full |
| cb-9022937 | full | full | full |
| cb-9070543 | full | full | full |
| cb-9166182 | full | full | full |
| cb-9168639 | full | full | full |
| cb-9348218 | partial (provenance) | partial (provenance) | full |
| cb-9370340 | unscored | unscored | unscored |

## Errors

- B cb-7935517: BudgetExceeded: env_agent: no submission after 50 turns
- B cb-8912293: BudgetExceeded: environment not ready: Ran from code/run. Scripts 02, 03 and 04 finished in seconds and wrote Figure_1, 2, 3, A11, A2, A3 and Table_A2 to result
- B cb-7981862: OSError: [Errno 28] No space left on device

Small samples: with about 20 tasks, a difference of a few tasks is within noise; read the intervals and the exact p-values before ranking versions.
