---
name: find-entry-point
description: Use first, when the code comes without instructions for reproducing its
  results, or the instructions do not say which command produces which result.
version: 2
evidence:
- 20261018-152647_cb-1854976_single_haiku55
- 20261018-154436_cb-2011424_single_haiku55
- 20261018-154555_cb-2011424_fixed_haiku55
- 20261018-122929_cb-0238624_single_haiku55
- 20261018-164335_cb-3137115_fixed_haiku55
---

Step 0 (always, macOS sandbox): 
- Never use `sed -i` (BSD sed fails: 'invalid command code'). Edit files with a python read/replace/write snippet that asserts the replacement count, and keep file.orig.
- Run `pwd` once and record the workspace root. Use absolute paths for the venv interpreter (<root>/.venv/bin/python) and for logs; `cd code` does not make `../.venv` safe in every command. Do not `cd ..` out of the workspace.
- Create the output directories the code writes to (mkdir -p results, and sub-folders it makes with a non-recursive mkdir) before the first run.
- Hardcoded /data, /code, /results paths: map them to workspace data/, code/, results/ (/ is read-only).

Steps
1. List the tree two levels deep. Note README/docs, run or main scripts, shell scripts, Makefile, notebooks, configs, environment files, and results/outputs folders.
2. Read the README fully, then every shell script and Makefile target: they hold the real commands and arguments.
3. Match each question to an output: grep the code for the printed strings, file names or column names in the question. The script that writes it is the entry point.
4. Read the entry point's argument parsing and main block: required arguments, data paths, output paths, seeds.
5. Write down per question: command, working directory, expected output, needed data. Check that the data path exists before running.

Checks
- Every question maps to one command and one output; prefer the script the authors' shell script or notebook calls.
- Do not invent a driver when the authors ship one.
