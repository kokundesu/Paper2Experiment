---
name: legacy-environment
description: Use when setting up an environment for code written for older library
  versions, or when a library raises an error or warning about removed or changed
  behaviour.
version: 3
evidence:
- 20261018-154555_cb-2011424_fixed_haiku55
- 20261018-154747_cb-2011424_planner_workers_haiku55
- 20261018-145552_cb-0396930_single_haiku55
- 20261018-150628_cb-1324693_single_haiku55
---

When: the code predates its libraries' current versions, or a run fails inside a library call.

Steps
1. Date the code (commit/file dates, pins, imports, README Python version). Create the venv with a matching Python (`uv venv --python 3.x`); the default Python here is very new, so old code often needs 3.8-3.10.
2. Install pinned versions first; otherwise the closest in the same major release. For numpy-1-era code pin numpy<2 and install everything (including scipy, packaging, pandas) in ONE uv command. Import-test: `python -c 'import pkg'`.
3. 'numpy.dtype size changed' or dlopen failure of a compiled extension: install numpy<2 or older package builds; do not patch code. Also for a system Python (CommandLineTools) use a uv-managed Python instead.
4. Pydantic/typing errors: choose the pydantic major the framework supports; check typing-extensions too; confirm with `uv pip list`.
5. Removed API (keras.engine.*, collections.Iterable/Mapping, numpy.int, DataFrame.append, removed keyword): prefer an older Python/library that still has it (for removed stdlib names, choose Python <=3.9 up front) instead of patching; else patch to exactly the old behaviour with a python snippet (not sed -i) and test on a tiny input.
6. Keras 2 HDF5 models failing under Keras 3: tf-keras with TF_USE_LEGACY_KERAS=1. TF1 code needs a TF1 env; if it does not install, report it rather than porting.
7. Old R package version not installable via micromamba (solver says r-base does not exist): do not loop over r-base versions; keep the current R and make a minimal compat fix of the code.
8. Record every patch: file, line, old behaviour, evidence.

Checks
- All imports succeed in one command before the first run.
- First printed numbers look sane.
- A patch that changes what is computed is a bug, not a fix.
