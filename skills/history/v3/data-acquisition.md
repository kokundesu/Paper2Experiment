---
name: data-acquisition
description: Use when the code needs data that is not in the workspace, or a download
  fails.
version: 1
evidence:
- 20261017-142851_v4-itransformer_planner_nogates_haiku55
---

When: a script expects a data file that does not exist, or the README points to a download.

Steps
1. Look in the workspace first (data/, the code folder, paths in configs). Use what is there.
2. Take the source the authors name (README, download script, code comment). Do not substitute other data.
3. By host:
   - Google Drive: `uv pip install gdown`, then `gdown <file id>` or `gdown --folder <url>`; a plain curl of a
     Drive link returns an html page, not the file.
   - Direct links: `curl -L --retry 3 --fail -o <file> <url>`; check the file type afterwards (`file <name>`).
   - Packaged datasets (library loaders): call the loader once on its own to see where it stores the files.
4. A network error (curl exit 6, 7, 28, 35, 56): retry with `--retry 3`; then try the other official mirror
   the authors or the loader name. Do not retry the identical command more than twice.
5. Unpack, then check: the expected file names exist, sizes are plausible, a checksum matches when one is
   given, and the first lines parse.
6. Setup steps (install, download, patch) are setup work, not experiment runs: finish them before planning the
   runs that need them.

Checks
- The path the code reads now exists and the program gets past data loading in a short run.
