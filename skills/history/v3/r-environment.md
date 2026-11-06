---
name: r-environment
description: Use when the code is in R (.R, .Rmd, an R project) and needs an R installation
  and packages.
version: 1
evidence: []
---

When: the entry point is an R script or R Markdown document.

Steps
1. Find the R version and packages: renv.lock, DESCRIPTION, sessionInfo() output in the repository, install
   scripts, and every library()/require()/pkg:: call (grep -rhoE "library\(([^)]+)\)|require\(([^)]+)\)|[a-zA-Z0-9.]+::" ).
2. Create the environment in the workspace (it is deleted with the workspace):
   `micromamba create -y -p ./.renv -c conda-forge r-base=<major.minor> r-<pkg> ...`
   Package names on conda-forge are `r-` + the CRAN name in lowercase (r-ggplot2, r-data.table).
   Bioconductor packages come from `-c bioconda` as `bioconductor-<name>`.
3. A package that micromamba cannot find: install it from CRAN inside the environment:
   `./.renv/bin/Rscript -e 'install.packages("<pkg>", repos="https://cloud.r-project.org")'`.
   An old pinned version: `remotes::install_version("<pkg>", "<version>", repos=...)` (install r-remotes first).
4. Run with the environment's interpreter: `./.renv/bin/Rscript <script>.R`; R Markdown:
   `./.renv/bin/Rscript -e 'rmarkdown::render("<file>.Rmd")'` (needs r-rmarkdown and pandoc from conda-forge).
5. Print results instead of only saving them: the log is the evidence. Plots go to files (png() / ggsave()),
   which view_image can open.
6. Setting the working directory: scripts that call setwd() or use relative paths must run from the folder the
   authors expect; read the first lines of each script.

Checks
- `./.renv/bin/Rscript -e 'sessionInfo()'` lists the packages the code loads.
- Each script runs to its end without "there is no package called" errors.
