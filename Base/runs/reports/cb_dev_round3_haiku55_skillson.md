# Agent evaluation: CORE-Bench dev, runs since 20261027-1050, haiku55, skills on

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
| A | 42 | 32/42 (76%) | 61%–87% | 32/42 | 26/42 | 81/97 (84%) | $0.011 | $0.46 | 2.3 min | 5.6 h |
| B | 42 | 33/42 (79%) | 64%–88% | 33/42 | 27/42 | 81/97 (84%) | $0.016 | $0.67 | 2.8 min | 4.9 h |
| D | 42 | 35/42 (83%) | 69%–92% | 35/42 | 27/42 | 89/97 (92%) | $0.025 | $1.06 | 3.5 min | 6.0 h |

## Paired comparisons (tasks both versions ran)

| Pair | Tasks | Both full | Only first | Only second | Neither | McNemar exact p |
|---|---|---|---|---|---|---|
| A vs B | 42 | 28 | 4 | 5 | 5 | 1.000 |
| A vs D | 42 | 31 | 1 | 4 | 6 | 0.375 |
| B vs D | 42 | 31 | 2 | 4 | 5 | 0.688 |

## Failure taxonomy (runs that are not full)

| Version | setup_failed | budget_or_turns | error | no_answers | provenance | partial | wrong_answers |
|---|---|---|---|---|---|---|---|
| A | 0 | 0 | 0 | 2 | 0 | 2 | 6 |
| B | 0 | 0 | 0 | 0 | 0 | 4 | 5 |
| D | 0 | 0 | 0 | 0 | 0 | 3 | 4 |

## Skill usage

| Version | Library versions | Runs reading any skill | Reads per skill |
|---|---|---|---|
| A | 5 | 35/45 | r-environment 17, find-entry-point 13, notebook-execution 2, run-protocol 2, macos-shell-and-paths 2, legacy-environment 1 |
| B | 5 | 29/45 | r-environment 12, find-entry-point 9, macos-shell-and-paths 8, notebook-execution 5, cpu-runtime 4, run-protocol 2, legacy-environment 2, data-acquisition 1 |
| D | 5 | 34/45 | r-environment 30, macos-shell-and-paths 18, legacy-environment 5, cpu-runtime 4, find-entry-point 3, data-acquisition 2, notebook-execution 2, run-protocol 1 |

## Per task

| Task | A | B | D |
|---|---|---|---|
| cb-0201225 | full | partial | full |
| cb-0220918 | partial | full | full |
| cb-0238624 | full | full | full |
| cb-0325493 | full | full | full |
| cb-0396930 | full | full | partial |
| cb-0940461 | full | fail (wrong_answers) | full |
| cb-1108125 | full | full | full |
| cb-1324693 | full | full | full |
| cb-1683542 | full | full | full |
| cb-1854976 | fail (wrong_answers) | full | full |
| cb-1906954 | full | full | full |
| cb-2011424 | full | full | full |
| cb-2061060 | full | full | full |
| cb-2916503 | full | full | full |
| cb-3137115 | full | full | full |
| cb-3249574 | unscored | unscored | unscored |
| cb-3269870 | partial | partial | partial |
| cb-3272782 | full | full | full |
| cb-3497606 | full | fail (wrong_answers) | full |
| cb-3894632 | full | full | full |
| cb-4098236 | full | full | full |
| cb-4600160 | full | full | full |
| cb-4645832 | full | full | full |
| cb-4807644 | fail (wrong_answers) | partial | partial |
| cb-4884085 | fail (wrong_answers) | fail (wrong_answers) | fail (wrong_answers) |
| cb-5286757 | unscored | unscored | unscored |
| cb-5367566 | full | full | full |
| cb-5496369 | full | partial | full |
| cb-5777882 | fail (wrong_answers) | full | fail (wrong_answers) |
| cb-5975162 | full | full | full |
| cb-6133093 | fail (wrong_answers) | fail (wrong_answers) | fail (wrong_answers) |
| cb-6460826 | full | full | full |
| cb-6746514 | full | full | full |
| cb-7038571 | full | full | full |
| cb-7156696 | full | full | full |
| cb-7935517 | fail (no_answers) | full | full |
| cb-7981862 | fail (wrong_answers) | fail (wrong_answers) | fail (wrong_answers) |
| cb-8197429 | full | full | full |
| cb-8912293 | full | full | full |
| cb-9022937 | full | full | full |
| cb-9070543 | full | full | full |
| cb-9166182 | full | full | full |
| cb-9168639 | full | full | full |
| cb-9348218 | fail (no_answers) | full | full |
| cb-9370340 | unscored | unscored | unscored |

## Errors

- B cb-2061060: BudgetExceeded: env_agent: no submission after 50 turns
- B cb-7935517: BudgetExceeded: environment not ready: run_plots.R ran end-to-end in about 18 s (exit 0). It printed the Plot_sampling_rho group/colour/linetype table (group 1 
- B cb-9348218: BudgetExceeded: env_agent: no submission after 50 turns

Small samples: with about 20 tasks, a difference of a few tasks is within noise; read the intervals and the exact p-values before ranking versions.
