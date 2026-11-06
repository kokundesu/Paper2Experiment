---
name: legacy-environment
description: Use when setting up an environment for code written for older library
  versions, or when a library raises an error or warning about removed or changed
  behaviour.
version: 1
evidence:
- 20261017-121553_v4-fairbatch_planner_nogates_haiku55
- 20261017-122308_v4-fairbatch_planner_workers_haiku55
---

When: the code predates the current versions of its libraries, or a run fails inside a library call.

Steps
1. Date the code: last commit or file dates, pinned versions in environment files, imports that no longer
   exist. Pick a Python version from that era that this machine can install (`uv venv --python 3.x`).
2. Install the pinned versions first. If a pin cannot be installed here, take the closest version that can,
   in the same major release, before moving to a newer major release.
3. When a newer library rejects old code (an error, or a warning that a default or behaviour changed):
   a. Read the full message and the library's changelog or deprecation note for that call: what did the old
      version do?
   b. Prefer installing an older version that still behaves the old way.
   c. Otherwise patch the call so it does exactly what the old version did, not something that merely runs:
      same shapes and broadcasting, same dtypes, same reduction, same defaults, same order of operations.
   d. If unsure what the old behaviour was, run the call both ways on a tiny input and compare.
4. Record every patch: file, line, what the old library did, and the evidence (message, changelog, comparison).

Checks
- After the environment works, the program's first printed numbers look sane (no NaN, no constant losses).
- A patch that changes what is computed (shape of a target, sign, averaging axis) is a bug, not a fix.
