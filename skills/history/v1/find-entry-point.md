---
name: find-entry-point
description: Use first, when the code comes without instructions for reproducing its
  results, or the instructions do not say which command produces which result.
version: 1
evidence:
- 20261017-124142_v4-ecod_fixed_haiku55
---

When: you must find how the authors produced their results before you can run anything.

Steps
1. List the tree two levels deep. Note: README/docs, run or main scripts, shell scripts, Makefile, notebooks
   (.ipynb, .Rmd), config folders, environment files (requirements, setup.py, pyproject, environment.yml,
   Dockerfile, DESCRIPTION), and folders named results/outputs/figures (what the code is expected to write).
2. Read the README fully, then every shell script and Makefile target: they usually hold the real commands and
   arguments, which beat code defaults.
3. Match each question to an output: search the code for the printed strings, file names or column names the
   question mentions (grep -rn for a distinctive word). The script that writes it is the entry point for that
   question.
4. Read the entry point's argument parsing and its `__main__` block: required arguments, data paths, output
   paths, random seeds.
5. Write down, per question: command, working directory, expected output (printed line or file), and the data it
   needs. Check that the data path exists before running.

Checks
- Every question maps to one command and one output; if two scripts could produce it, prefer the one a shell
  script or notebook of the authors calls.
- Do not invent a driver when the authors ship one; write one only to call their code with their arguments.
