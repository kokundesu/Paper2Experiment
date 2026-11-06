# Agent evaluation: CORE-Bench test, runs since 20261103-2348, haiku55, skills on

30 tasks, workflows: A (single), B (fixed), D (planner_workers); one run per task and workflow (latest).

## Pass rates

| Version | Runs | Full | 95% CI | Tolerance-only | HAL rule | Question acc. | Mean cost | Total cost | Median wall | Total wall |
|---|---|---|---|---|---|---|---|---|---|---|
| A | 30 | 29/30 (97%) | 83%–99% | 29/30 | 24/30 | 44/46 (96%) | $0.013 | $0.38 | 2.4 min | 5.2 h |
| B | 30 | 28/30 (93%) | 79%–98% | 29/30 | 25/30 | 43/46 (93%) | $0.017 | $0.52 | 3.5 min | 6.1 h |
| D | 30 | 26/30 (87%) | 70%–95% | 26/30 | 22/30 | 40/46 (87%) | $0.025 | $0.75 | 3.0 min | 6.1 h |

## Paired comparisons (tasks both versions ran)

| Pair | Tasks | Both full | Only first | Only second | Neither | McNemar exact p |
|---|---|---|---|---|---|---|
| A vs B | 30 | 28 | 1 | 0 | 1 | 1.000 |
| A vs D | 30 | 26 | 3 | 0 | 1 | 0.250 |
| B vs D | 30 | 25 | 3 | 1 | 1 | 0.625 |

## Failure taxonomy (runs that are not full)

| Version | setup_failed | budget_or_turns | error | no_answers | provenance | partial | wrong_answers |
|---|---|---|---|---|---|---|---|
| A | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| B | 1 | 0 | 0 | 0 | 1 | 0 | 0 |
| D | 0 | 0 | 1 | 1 | 0 | 1 | 1 |

## Skill usage

| Version | Library versions | Runs reading any skill | Reads per skill |
|---|---|---|---|
| A | 5 | 21/30 | r-environment 17, find-entry-point 3, macos-shell-and-paths 2, run-protocol 1 |
| B | 5 | 20/30 | r-environment 14, macos-shell-and-paths 3, notebook-execution 2, find-entry-point 2, legacy-environment 1, report-answers 1 |
| D | 5 | 26/30 | r-environment 31, macos-shell-and-paths 12, cpu-runtime 4, find-entry-point 3, notebook-execution 2, legacy-environment 2, run-protocol 1 |

## Per task

| Task | A | B | D |
|---|---|---|---|
| cb-0152700 | full | partial (provenance) | full |
| cb-0504157 | full | full | full |
| cb-1175539 | full | full | full |
| cb-1394704 | full | full | full |
| cb-1624349 | full | full | full |
| cb-1724988 | full | full | full |
| cb-2242462 | full | full | full |
| cb-2345790 | full | full | full |
| cb-2708693 | full | full | full |
| cb-2804717 | full | full | full |
| cb-2816027 | full | full | full |
| cb-3418007 | full | full | fail (error) |
| cb-3593259 | full | full | full |
| cb-3639589 | full | full | full |
| cb-3762736 | full | full | full |
| cb-3821950 | fail (no_answers) | fail (setup_failed) | fail (no_answers) |
| cb-4252248 | full | full | full |
| cb-4299879 | full | full | full |
| cb-4671827 | full | full | full |
| cb-4933686 | full | full | partial |
| cb-5136217 | full | full | full |
| cb-6295990 | full | full | full |
| cb-7186268 | full | full | full |
| cb-7716865 | full | full | full |
| cb-8807709 | full | full | full |
| cb-9054015 | full | full | full |
| cb-9240688 | full | full | full |
| cb-9294029 | full | full | full |
| cb-9477017 | full | full | fail (wrong_answers) |
| cb-9832712 | full | full | full |

## Errors

- B cb-0504157: BudgetExceeded: env_agent: no submission after 50 turns
- B cb-3821950: BudgetExceeded: environment not ready: FAILED. Rscript -e 'rmarkdown::render("ktc_11_paper.Rmd", output_dir="../results", clean=TRUE)' stops at chunk [setup] (l
- D cb-3418007: KeyError: 'setup_env'

Small samples: with about 20 tasks, a difference of a few tasks is within noise; read the intervals and the exact p-values before ranking versions.
