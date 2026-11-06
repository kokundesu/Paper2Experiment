---
name: r-environment
description: Use when the code is in R (.R, .Rmd, an R project) and needs an R installation
  and packages.
version: 2
evidence:
- 20261018-152458_cb-1683542_planner_workers_haiku55
- 20261018-154919_cb-2061060_single_haiku55
- 20261018-155922_cb-2061060_planner_workers_haiku55
- 20261018-161651_cb-2916503_single_haiku55
- 20261018-143003_cb-0325493_fixed_haiku55
---

When: the entry point is an R script or R Markdown document.

Steps
1. Find R version and packages: renv.lock, DESCRIPTION, install scripts, and every library()/require()/pkg:: call (grep).
2. From the workspace root (run `pwd` first; mkdir -p logs results before redirecting any log there): `micromamba create -y -p $PWD/.renv -c conda-forge r-base r-<pkg> ...` (names: r- + lowercase CRAN name; Bioconductor: bioconductor-<name> from bioconda). Check afterwards that .renv/bin/Rscript exists; if the command exit was nonzero read the log tail.
3. Also install packages that are suggested at runtime (e.g. r-lme4 for glmm fits, r-rmarkdown, r-knitr). A missing package: install via micromamba, else CRAN `install.packages`. For source builds that need a compiler, put .renv/bin on PATH.
4. Run with absolute interpreter path: `$ROOT/.renv/bin/Rscript <script>.R` from the folder the authors expect (read setwd/relative paths; ../data usually means run from code/).
5. PDF output needs LaTeX: if pdflatex is absent, do not spend more than a few commands; render to HTML/markdown (output_format override) or md_document, and note it. Optional packages unused on the answer's path (plotting extras): skip or guard the call and record it.
6. Print values: the log is evidence. Figures to png() and open with view_image; when a figure's numbers are not printed, re-use the authors' plotting code in a script FILE (not `-e`) and print its data.
7. Old package behaviour changed (e.g. a returned object is now a list): make the minimal compat edit with python, not sed -i.

Checks
- `$ROOT/.renv/bin/Rscript -e 'sessionInfo()'` lists the needed packages.
- Each script runs to its end without 'there is no package called'.
