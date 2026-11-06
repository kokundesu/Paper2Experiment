---
name: report-answers
description: 'Use when writing the final answers or metrics: matching each question
  exactly, taking values from run output, units and formats.'
version: 1
evidence:
- 20261017-123210_v4-ecod_single_haiku55
---

When: the runs are done and you are about to submit.

Steps
1. Re-read each question word by word: which dataset, split, model, metric, and which statistic (mean, best,
   final epoch, test vs validation).
2. Find the value in a log or output file of a run you made. Copy it exactly as printed: no rounding, no unit
   change unless the question asks for a unit (then convert and say so in notes).
3. Percent vs fraction: answer in the form the question implies; if unclear, use the form the program prints.
4. Lists: keep the order the question gives. Booleans and labels: use the program's spelling.
5. Questions about a figure: find the image file the run wrote and open it; read the value from the figure only
   when no printed number exists.
6. Cite the exact log or file for every answer. Never compute, estimate or retype a number by hand, and never
   take one from a file that existed before your runs.
7. A question you cannot answer: leave it out and explain why in notes.

Checks
- Every question id is answered once, or explained.
- Each answer string appears verbatim in the cited log or file.
