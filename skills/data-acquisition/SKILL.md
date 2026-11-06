---
name: data-acquisition
description: Use when the code needs data or checkpoints that are not in the workspace,
  or a download fails.
version: 2
evidence:
- 20261018-014758_cb-0220918_fixed_haiku55
- 20261018-020340_cb-0238624_single_haiku55
- 20261018-052446_cb-4645832_fixed_haiku55
- 20261018-050744_cb-4098236_fixed_haiku55
---

When: a script expects a data file or model checkpoint that does not exist, or the README points to a download.

Steps
1. Look in the workspace first (data/, the code folder, config paths; map absolute paths like /data to workspace data/). Search by pattern (find . -name '*.ckpt' -o -name '*train*').
2. Take the source the authors name (README, download script, code comment, loader library). Do not substitute other data unless the authors' loader fetches from it.
3. By host:
   - Google Drive: `uv pip install gdown`, then `gdown <id>` or `gdown --folder <url>`; plain curl returns html.
   - Direct links: `curl -L --retry 3 --fail -o <file> <url>`; check with `file <name>`.
   - A library dataset loader whose index URL is dead: fetch the same dataset from another public mirror, verify shape and column counts against the code's expectations, then replace only the loading line.
4. Network error (curl 6, 7, 28, 35, 56): retry with --retry 3, then try one other mirror. Never repeat an identical command more than twice.
5. Unpack and verify: expected names exist, sizes plausible, first lines parse (quotes or header quirks may need cleaning).
6. Downloads and installs are setup, not experiment runs.
7. If an essential input (training split, pretrained weights) is absent, no source is named, and a short search of code and README finds none, stop after two attempts. State which file is missing; do not fabricate or train a substitute. Leave the answer out.

Checks
- The path the code reads exists and a short run gets past data loading.
