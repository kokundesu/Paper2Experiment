# Skill library changelog

## v1 (2026-10-17 22:58)

Seed library written by the benchmark builder from the round-1 development runs (v4 dev papers; no test-split run used).

- create `find-entry-point`: Hard-level tasks remove the reproduction instructions; round-1 agents lost turns locating the entry point and its arguments. (runs: 20261017-124142_v4-ecod_fixed_haiku55)
- create `legacy-environment`: Two runs patched an old loss call to silence a shape error but changed what it computed; the results were wrong. (runs: 20261017-121553_v4-fairbatch_planner_nogates_haiku55, 20261017-122308_v4-fairbatch_planner_workers_haiku55)
- create `data-acquisition`: A run lost all its re-plans on a failed archive download and on download steps submitted as experiment runs. (runs: 20261017-142851_v4-itransformer_planner_nogates_haiku55)
- create `run-protocol`: Runs used the script default of a single split where the protocol averages ten, and one submitted identical values for three seeds. (runs: 20261017-124142_v4-ecod_fixed_haiku55, 20261017-125946_v4-ecod_planner_workers_haiku55, 20261017-123210_v4-ecod_single_haiku55)
- create `report-answers`: Answers must be traceable to this run's output; round-1 runs showed transcription and unit slips. (runs: 20261017-123210_v4-ecod_single_haiku55)
- create `notebook-execution`: Several development tasks deliver their results through notebooks whose stored outputs must not be reused. (runs: 20261017-121553_v4-fairbatch_planner_nogates_haiku55)

## v2 (2026-10-17 23:13)

Builder edit: R support added to the sandbox (micromamba in the user directory).

- create `r-environment`: CORE-Bench has many R capsules; R now runs through micromamba in the workspace (builder edit, no run evidence yet). (runs: -)

## v3 (2026-10-17 23:50)

Builder edit from the round-1 development runs' timing analysis (the other session's findings).

- revise `run-protocol`: A run executed the identical command twice, once per metric it printed, doubling the time. (runs: 20261017-143741_v4-itransformer_planner_workers_haiku55)
- create `cpu-runtime`: A run took about 14 min per training run instead of about 1 min because data-loader workers were left on, on a CPU-only Mac. (runs: 20261017-143741_v4-itransformer_planner_workers_haiku55)

## v4 (2026-10-18 06:41)

Many runs lost steps to the same mistakes: macOS BSD `sed -i` without a suffix failed in at least 10 runs; relative `../` paths after `cd code` pointed at the wrong venv or results folder; hardcoded absolute /data, /results and /code paths had to be patched in many tasks. Several runs failed because data or checkpoints were not in the workspace. Binary incompatibility and removed-API errors recurred.

- create `macos-shell-and-paths`: BSD sed -i failures and cwd/relative-path mistakes recurred across many runs; hardcoded absolute paths needed patching in many tasks. (runs: 20261018-013250_cb-0201225_single_haiku55, 20261018-022528_cb-1854976_fixed_haiku55, 20261018-044645_cb-3272782_fixed_haiku55, 20261018-055828_cb-5367566_planner_workers_haiku55, 20261018-060151_cb-6460826_single_haiku55)
- revise `data-acquisition`: Runs with missing training files or checkpoints and no named source spent long before stopping; a dead loader index URL needed a replacement load. (runs: 20261018-014758_cb-0220918_fixed_haiku55, 20261018-020340_cb-0238624_single_haiku55, 20261018-052446_cb-4645832_fixed_haiku55, 20261018-050744_cb-4098236_fixed_haiku55)
- revise `legacy-environment`: Recurring binary-incompatibility and removed-API failures cost many commands. (runs: 20261018-021453_cb-0396930_single_haiku55, 20261018-021549_cb-0396930_fixed_haiku55, 20261018-055523_cb-5367566_single_haiku55, 20261018-055828_cb-5367566_planner_workers_haiku55, 20261018-023448_cb-3249574_single_haiku55)

## v5 (2026-10-19 10:59)

Runs mostly pass. Recurring costs: BSD `sed -i` still fails in many runs, even ones that read nothing (macos-shell-and-paths was read in only 1 of ~75 runs). Other recurring issues: the workspace-root venv is wrongly addressed after `cd code` or `cd ..`. Output dirs the code expects (../results/...) are missing. Removed stdlib/API names (collections.Iterable, keras.engine) are patched with sed. One fail came from an unpatched sed plus a venv on Python 3.11 against old code. Skills are read rarely, so the key rules need to be in skills agents open early: find-entry-point is read most often, and r-environment is read in 42 runs.

- revise `find-entry-point`: It is the most-read skill (17 runs) and is read first, while macos-shell-and-paths was read in only 1 run. The sed -i, cwd and venv-path failures recur in ~15 runs, so add a short macOS preamble here. (runs: 20261018-152647_cb-1854976_single_haiku55, 20261018-154436_cb-2011424_single_haiku55, 20261018-154555_cb-2011424_fixed_haiku55, 20261018-122929_cb-0238624_single_haiku55, 20261018-164335_cb-3137115_fixed_haiku55)
- revise `legacy-environment`: Old code failing on removed stdlib names (collections.Iterable) led to a failed run and wasted venvs; old spaCy/pydantic stacks cost many commands; the R-version solver failed repeatedly. (runs: 20261018-154555_cb-2011424_fixed_haiku55, 20261018-154747_cb-2011424_planner_workers_haiku55, 20261018-145552_cb-0396930_single_haiku55, 20261018-150628_cb-1324693_single_haiku55)
- revise `r-environment`: R runs hit relative-path and cwd mistakes (micromamba created in parent dir, log redirects failing, ./.renv missing), missing recursive deps (lme4), and long PDF/LaTeX detours. (runs: 20261018-152458_cb-1683542_planner_workers_haiku55, 20261018-154919_cb-2061060_single_haiku55, 20261018-155922_cb-2061060_planner_workers_haiku55, 20261018-161651_cb-2916503_single_haiku55, 20261018-143003_cb-0325493_fixed_haiku55)
- revise `macos-shell-and-paths`: Read in only 1 run while the same sed/cwd failures appear in ~15; make it triggered earlier via description and add venv and mkdir rules. (runs: 20261018-102133_cb-0201225_planner_workers_haiku55, 20261018-110454_cb-0220918_fixed_haiku55, 20261018-114802_cb-0220918_planner_workers_haiku55, 20261018-164042_cb-3137115_single_haiku55)
