---
name: legacy-environment
description: Use when setting up an environment for code written for older library
  versions, or when a library raises an error or warning about removed or changed
  behaviour.
version: 2
evidence:
- 20261018-021453_cb-0396930_single_haiku55
- 20261018-021549_cb-0396930_fixed_haiku55
- 20261018-055523_cb-5367566_single_haiku55
- 20261018-055828_cb-5367566_planner_workers_haiku55
- 20261018-023448_cb-3249574_single_haiku55
---

When: the code predates its libraries' current versions, or a run fails inside a library call.

Steps
1. Date the code (commit/file dates, pins, imports). Create the venv with a matching Python (`uv venv --python 3.x`).
2. Install pinned versions first; otherwise the closest version in the same major release. For numpy-1-era code pin numpy<2 and install everything in ONE uv command so the resolver picks compatible binaries.
3. 'numpy.dtype size changed', binary incompatibility or dlopen failure of a compiled extension: numpy and the compiled package disagree. Install numpy<2 or a package version built for it (older scipy/pandas); verify with a bare `python -c 'import pkg'` before running code. Do not patch code for this.
4. Pydantic/typing errors in old frameworks: choose the pydantic major the framework supports and that works on your Python; confirm the installed version with `uv pip list` since an upgrade may not have applied.
5. Removed API (keras.engine.*, numpy.int/float aliases, DataFrame.append, a removed keyword): first try an older library that keeps it; else patch to exactly the old behaviour and check on a tiny input. Check the installed signature (inspect.signature) before dropping a keyword and confirm its default equals the old option.
6. TensorFlow 1.x code (tf.placeholder, Session) needs a TF1 environment; if none installs here, report that rather than porting the model. Old Keras HDF5 models: tf-keras with TF_USE_LEGACY_KERAS=1.
7. Record every patch: file, line, old behaviour, evidence.

Checks
- All needed imports succeed in one command before the first run.
- First printed numbers look sane (no NaN, constant loss).
- A patch that changes what is computed is a bug, not a fix.
