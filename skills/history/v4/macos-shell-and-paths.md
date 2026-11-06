---
name: macos-shell-and-paths
description: Use when patching source files or running multi-step shell commands on
  macOS, especially with hardcoded absolute paths or after cd into a subfolder.
version: 1
evidence:
- 20261018-013250_cb-0201225_single_haiku55
- 20261018-022528_cb-1854976_fixed_haiku55
- 20261018-044645_cb-3272782_fixed_haiku55
- 20261018-055828_cb-5367566_planner_workers_haiku55
- 20261018-060151_cb-6460826_single_haiku55
---

Situation: BSD sed on macOS, cwd drift after `cd`, and code with hardcoded absolute paths (/data, /results, /code, Windows-style separators).

Steps
1. Edit files with a short python snippet (read/replace/write) and assert the replacement count is what you expect. Do NOT use `sed -i` (BSD sed needs a suffix argument and fails with 'invalid command code'). If you must, use `sed -i '' -e ...`.
2. Keep a copy of the original (`cp f f.orig`) and print `diff f.orig f`; the diff must show exactly the intended lines.
3. Use the workspace root as the single reference. Record its absolute path once and call the interpreter by absolute path. A `cd code` may not persist between commands, so `../.venv` may be wrong; check with `ls` before running.
4. Hardcoded absolute data/output paths: replace them with paths relative to the script file, or run from the folder where the relative path resolves. Create output directories the code writes to (`mkdir -p results`) first. Replace backslash path joins with os.path.join.
5. When piping a run through tail/head, also write the full log to a file so answers can cite it.
6. Run a patched script once to completion; do not rerun it only to check stability unless the protocol asks for repetitions.

Checks
- The diff shows only intended edits; the first run reaches data loading without path errors.
