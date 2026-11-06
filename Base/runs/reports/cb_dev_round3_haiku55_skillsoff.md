# Agent evaluation: CORE-Bench dev, runs since 20261027-1050, haiku55, skills off

45 tasks, workflows: A (single), B (fixed), D (planner_workers); one run per task and workflow (latest).

Unscored tasks (every question too noisy to score; left out of the rates below). Under the HAL rule they still count, so their HAL result is listed here:

| Task | A | B | D |
|---|---|---|---|
| cb-3249574 | HAL pass | HAL pass | HAL pass |
| cb-5286757 | HAL pass | HAL pass | HAL pass |
| cb-9370340 | HAL pass | HAL pass | HAL pass |

## Pass rates

| Version | Runs | Full | 95% CI | Tolerance-only | HAL rule | Question acc. | Mean cost | Total cost | Median wall | Total wall |
|---|---|---|---|---|---|---|---|---|---|---|
| A | 42 | 31/42 (74%) | 59%–85% | 33/42 | 28/42 | 76/97 (78%) | $0.014 | $0.58 | 2.2 min | 7.2 h |
| B | 42 | 33/42 (79%) | 64%–88% | 34/42 | 27/42 | 85/97 (88%) | $0.019 | $0.81 | 4.0 min | 8.7 h |
| D | 42 | 31/42 (74%) | 59%–85% | 31/42 | 26/42 | 83/97 (86%) | $0.024 | $1.00 | 2.9 min | 6.4 h |

## Paired comparisons (tasks both versions ran)

| Pair | Tasks | Both full | Only first | Only second | Neither | McNemar exact p |
|---|---|---|---|---|---|---|
| A vs B | 42 | 29 | 2 | 4 | 7 | 0.688 |
| A vs D | 42 | 27 | 4 | 4 | 7 | 1.000 |
| B vs D | 42 | 29 | 4 | 2 | 7 | 0.688 |

## Failure taxonomy (runs that are not full)

| Version | setup_failed | budget_or_turns | error | no_answers | provenance | partial | wrong_answers |
|---|---|---|---|---|---|---|---|
| A | 0 | 2 | 0 | 0 | 2 | 1 | 6 |
| B | 0 | 2 | 0 | 0 | 0 | 2 | 5 |
| D | 0 | 0 | 1 | 0 | 0 | 3 | 7 |

## Skill usage

| Version | Library versions | Runs reading any skill | Reads per skill |
|---|---|---|---|
| A | None | 0/45 | - |
| B | None | 0/45 | - |
| D | None | 0/45 | - |

## Per task

| Task | A | B | D |
|---|---|---|---|
| cb-0201225 | full | full | full |
| cb-0220918 | full | full | partial |
| cb-0238624 | full | full | full |
| cb-0325493 | full | full | full |
| cb-0396930 | full | full | full |
| cb-0940461 | full | fail (wrong_answers) | fail (wrong_answers) |
| cb-1108125 | full | full | full |
| cb-1324693 | full | full | full |
| cb-1683542 | full | full | full |
| cb-1854976 | full | full | full |
| cb-1906954 | full | full | full |
| cb-2011424 | full | full | full |
| cb-2061060 | full | full | full |
| cb-2916503 | full | full | full |
| cb-3137115 | full | full | full |
| cb-3249574 | unscored | unscored | unscored |
| cb-3269870 | partial | partial | partial |
| cb-3272782 | full | full | full |
| cb-3497606 | full | full | fail (wrong_answers) |
| cb-3894632 | full | full | full |
| cb-4098236 | full | full | full |
| cb-4600160 | full | full | full |
| cb-4645832 | fail (wrong_answers) | full | fail (wrong_answers) |
| cb-4807644 | fail (wrong_answers) | partial | fail (error) |
| cb-4884085 | fail (wrong_answers) | fail (wrong_answers) | fail (wrong_answers) |
| cb-5286757 | unscored | unscored | unscored |
| cb-5367566 | full | full | full |
| cb-5496369 | full | full | full |
| cb-5777882 | full | fail (wrong_answers) | fail (wrong_answers) |
| cb-5975162 | full | full | full |
| cb-6133093 | fail (wrong_answers) | fail (wrong_answers) | fail (wrong_answers) |
| cb-6460826 | full | full | full |
| cb-6746514 | partial (provenance) | full | full |
| cb-7038571 | full | full | full |
| cb-7156696 | full | full | full |
| cb-7935517 | fail (budget_or_turns) | fail (budget_or_turns) | full |
| cb-7981862 | fail (wrong_answers) | fail (wrong_answers) | fail (wrong_answers) |
| cb-8197429 | fail (provenance) | full | partial |
| cb-8912293 | full | full | full |
| cb-9022937 | full | full | full |
| cb-9070543 | full | full | full |
| cb-9166182 | fail (wrong_answers) | full | full |
| cb-9168639 | full | full | full |
| cb-9348218 | fail (budget_or_turns) | partial (budget_or_turns) | full |
| cb-9370340 | unscored | unscored | unscored |

## Errors

- A cb-7935517: BudgetExceeded: single_agent: no submission after 80 turns
- A cb-9348218: BudgetExceeded: single_agent: no submission after 80 turns
- B cb-4645832: BudgetExceeded: env_agent: no submission after 50 turns
- B cb-7935517: BudgetExceeded: env_agent: no submission after 50 turns
- B cb-8912293: BudgetExceeded: env_agent: no submission after 50 turns
- B cb-9070543: BudgetExceeded: environment not ready: Dose_Response_Script.Rmd rendered fully (exit 0, ~30 s full run; outputs in results/Dose_Response_Script_Output: html, ep
- B cb-9348218: BudgetExceeded: env_agent: no submission after 50 turns
- D cb-4807644: KeyError: 'setup_env'

Small samples: with about 20 tasks, a difference of a few tasks is within noise; read the intervals and the exact p-values before ranking versions.
