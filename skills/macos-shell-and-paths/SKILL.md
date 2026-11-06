---
name: macos-shell-and-paths
description: 'Use before editing any file or running any shell command on macOS: sed
  -i, cwd after cd, venv paths, hardcoded absolute paths, missing output directories.'
version: 2
evidence:
- 20261018-102133_cb-0201225_planner_workers_haiku55
- 20261018-110454_cb-0220918_fixed_haiku55
- 20261018-114802_cb-0220918_planner_workers_haiku55
- 20261018-164042_cb-3137115_single_haiku55
---

Situation: BSD sed, cwd drift, hardcoded absolute paths, workspace-only filesystem.

Steps
1. Edit files with a python snippet (read/replace/write) asserting the replacement count. NEVER `sed -i` (fails with 'invalid command code', even in quick one-liners; `-i ''` is the only form that works). Keep `cp f f.orig`; show `diff f.orig f`.
2. Run `pwd` once; use that absolute root for the interpreter (<root>/.venv/bin/python) and for logs. Never `cd ..` above the root or `cd` to /tmp or /dev/null; paths outside the workspace are rejected and / is read-only (no symlink at /data).
3. Create every directory the code or a log redirect writes to (mkdir -p logs results; also sub-folders such as results/classification when the code uses non-recursive mkdir) BEFORE the run.
4. Hardcoded /data, /code, /results: replace with paths relative to the script file (os.path.dirname(os.path.abspath(__file__))) or run from the folder where ../data resolves (usually code/).
5. Pipe through tail only together with a full log file.
6. Run a patched script to completion once; do not rerun to check stability.

Checks
- Diff shows only intended lines; first run reaches data loading without path errors.
