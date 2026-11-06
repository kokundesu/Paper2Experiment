---
name: notebook-execution
description: Use when results come from Jupyter notebooks or other literate documents
  that must be executed headless.
version: 1
evidence:
- 20261017-121553_v4-fairbatch_planner_nogates_haiku55
---

When: the entry point is a .ipynb (or a similar document) rather than a script.

Steps
1. Install the runner in the same environment as the code: `uv pip install jupyter nbconvert ipykernel`, then
   `python -m ipykernel install --user --name repro` and use `--ExecutePreprocessor.kernel_name=repro`.
2. Clear stored outputs first so old results cannot be mistaken for yours:
   `jupyter nbconvert --clear-output --inplace <nb>` on a copy if you must keep the original.
3. Execute with a timeout per cell and keep the executed copy:
   `jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=1800 --output executed.ipynb <nb>`
   (or `--to html`). Print what you need afterwards by reading the executed copy's outputs.
4. Notebooks with interactive or GPU-only cells: run the cells that produce the asked results; if you must skip
   or edit cells, convert to a script (`jupyter nbconvert --to script`) and record each change.
5. Relative paths in notebooks resolve from the notebook's folder: run from there.

Checks
- The executed copy has fresh outputs for the cells that hold the answers.
