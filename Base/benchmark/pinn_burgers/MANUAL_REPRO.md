# PINN Burgers (continuous-time inference): manual reproduction (case 2)

Date: 2026-10-01 · Machine: Apple M4, 16 GB, CPU only · Python 3.11.16, TF 2.21.0 (compat.v1), SciPy 1.17.1, numpy 2.4.6, pyDOE 0.3.8 (uv venv `envs/pinn`)

## Result

Official code `maziarraissi/PINNs` (commit 932f50a), `appendix/continuous_time_inference (Burgers)/Burgers.py`. Settings are the script defaults: nu = 0.01/pi, Latin hypercube collocation points, tanh MLP, L-BFGS-B with maxiter = maxfun = 50000, maxcor = 50, maxls = 50, ftol = eps, float32. The iteration count was **not** capped. The metric is the relative L2 error of u(t,x) on the full 256 x 100 grid of `burgers_shock.mat`. The ground truth comes from arXiv 1711.10561v1, Section 2.1 (text p.7, Figure 1 caption, Tables 1 and 2).

| Claim (id) | Setting | Paper | Reproduced median | Seeds (per-seed errors) | median / paper |
|---|---|---|---|---|---|
| `burgers_main_l2` | N_u=100, N_f=10000, 8x20 | 6.7e-4 (text, Fig. 1, Table 1) | **2.58e-3** (11 seeds); 2.15e-3 (seeds 0-2) | 1234: 1.10e-2; 0-9: 2.15e-3, 1.46e-3, 2.94e-3, 3.70e-3, 2.58e-3, 2.39e-3, 5.00e-3, 7.75e-4, 4.15e-3, 2.09e-3 | 3.9 (3.2) |
| `burgers_nu200_l2` | N_u=200, N_f=10000, 8x20 | 4.9e-4 (Table 1) | **1.12e-3** (4 seeds) | 1234: 1.01e-3; 0-2: 1.09e-3, 1.14e-3, 2.20e-3 | 2.3 |
| `burgers_l4n20_l2` | 4x20, N_u=100, N_f=10000 | 9.4e-4 (Table 2) | **5.11e-3** (4 seeds); 5.02e-3 (seeds 0-2) | 1234: 4.82e-2; 0-2: 5.20e-3, 5.02e-3, 1.17e-3 | 5.4 |

Over all 11 seeds, the main claim has a mean of 3.47e-3 ± 2.63e-3, a geometric mean of 2.78e-3, a minimum of 7.75e-4 and a maximum of 1.10e-2.

**Verdict: full under the case rubric** (median of at least 3 seeds within a factor of 10 of the paper; see `case.yaml`). The values are not reproduced exactly. Our typical error is 2-5x higher than the paper's single-run numbers, and the paper's 6.7e-4 sits at the lower tail of our seed distribution (1 of 11 seeds is below 1e-3). **Under a strict factor-3 criterion the verdict would be partial**: only `burgers_nu200_l2` passes, and the main claim misses narrowly (3.2x to 3.9x). The qualitative claims all hold. PINN errors are around 1e-3, which is far below the authors' earlier GP-based results. More boundary data (N_u=200) helps, and 4x20 is worse than 8x20.

Each run takes 0.5-3 min of CPU (train time 32-191 s, in `results/*.csv`). L-BFGS-B always stops on its own after 3.2k-7.0k iterations (3.6k-7.8k evaluations), so the 20-min budget was never binding.

Raw results: `results/burgers_{main,nu200,l4n20}.csv` hold one row per run (error, final loss, nit, nfev, status, train time), with logs in `results/logs/`.

## Diagnostics (not claims)

| Run | Change vs faithful run | Seeds 0-2 errors | Median | Finding |
|---|---|---|---|---|
| `diag_ftol0` | ftol = 0 | 2.15e-3, 1.46e-3, 2.94e-3 | 2.15e-3 | Bit-identical to the faithful run. The early stop is caused by zero float32 loss decrease, so the ftol setting does not matter. |
| `diag_scipy1.11` | SciPy 1.11.4 (Fortran L-BFGS-B), scratch venv | 5.62e-3, 1.32e-3, 2.34e-2 | 5.62e-3 | Different trajectories with the same seeds, and no improvement. The SciPy version is not the cause of the gap. |
| `diag_l8n40` | 8 hidden x 40 (what `Burgers_systematic.py` actually used for Table 1) | 1.96e-3, 1.55e-3, 1.48e-3 | 1.55e-3 | Lower and tighter than 8x20, but still 2.3x the paper. This does not fully explain the gap. |

The likely explanation for the remaining gap is that the paper reports a single favourable run per cell, on TF1/GPU float32. The paper itself reports the same 8x20, N_u=100, N_f=10000 network once as 6.7e-4 (Table 1) and once as 9.6e-4 (Table 2). Table 1 also contains failed runs, such as 2.7e-1 at N_u=100, N_f=4000. We cannot reproduce the authors' original TF1 + GPU numerics on this machine.

## Steps and fixes

The upstream clone `repos/PINNs` is untouched. The needed files are copied into `manual/PINNs/` with the original relative layout: `Utilities/plotting.py` (unchanged, no longer imported), `appendix/Data/burgers_shock.mat`, and `appendix/continuous_time_inference (Burgers)/Burgers.py` (patched). The diff is `manual/burgers_tf2_compat.patch`; apply it with `git apply` from the repo root.

1. Locating the files: the Burgers continuous inference script and its data are in `appendix/`, not `main/`. `main/Data` has no `burgers_shock.mat`.
2. `ModuleNotFoundError: No module named 'pyDOE'`: `pip install pyDOE` installs pydoe 1.5.0, whose module is the lowercase `pydoe`. Fix: pin `pyDOE==0.3.8`.
3. `ValueError: Key pgf.preamble: Could not convert ['\\usepackage[utf8x]{inputenc}', ...] to str`, raised from `Utilities/plotting.py` on matplotlib 3.11. Fix: removed the `from plotting import ...` line. The plotting block now only runs with `PLOT=1`, and it would still need that import plus LaTeX, so it stays disabled.
4. `AttributeError: module 'tensorflow' has no attribute 'set_random_seed'`. Fix: `import tensorflow.compat.v1 as tf; tf.disable_v2_behavior()`.
5. `AttributeError: module 'tensorflow.compat.v1' has no attribute 'contrib'` (ScipyOptimizerInterface). Fix: a roughly 40-line drop-in class in the script with the same mechanics. It packs the trainable variables into one float64 vector and calls `scipy.optimize.minimize(fun, x0, jac=True, method='L-BFGS-B', options=<original options>)`. `fun` assigns the vector to the variables and returns the float32 graph loss and gradient, cast to float64. The final vector is written back afterwards.
6. Cosmetic changes: `log_device_placement=False`, and the loss callback prints every 1000th evaluation instead of every one.
7. Configuration through environment variables, with the original values as defaults: `SEED` (1234), `N_U` (100), `N_F` (10000), `LAYERS` (8 hidden), `NEURONS` (20), `MAXITER` (50000), `FTOL` (eps, diagnostics only). `RESULTS_CSV` appends one row per run, and the script prints nit, nfev and the termination message.

Environment:

```bash
uv venv --python 3.11 envs/pinn
VIRTUAL_ENV=envs/pinn uv pip install tensorflow scipy numpy matplotlib 'pyDOE==0.3.8'
```

Commands (from `benchmark/pinn_burgers/`). `manual/run_seeds.sh` cds into the script folder and calls the patched `Burgers.py` once per seed:

```bash
manual/run_seeds.sh main  100 10000 8 20 1234 0 1 2 3 4 5 6 7 8 9   # burgers_main_l2
manual/run_seeds.sh nu200 200 10000 8 20 1234 0 1 2                 # burgers_nu200_l2
manual/run_seeds.sh l4n20 100 10000 4 20 1234 0 1 2                 # burgers_l4n20_l2
# single run by hand:
cd "manual/PINNs/appendix/continuous_time_inference (Burgers)" && SEED=0 ../../../../../../envs/pinn/bin/python Burgers.py
```

Up to two runs were executed concurrently. Four concurrent runs oversubscribed the CPU (each run uses about 2 cores), slowed every run 3-5x, and were aborted and restarted.

## Deviations from the original

- The optimizer wrapper was re-implemented, since TF2 has no tf.contrib. The algorithm and options are the same, but SciPy 1.17 uses the C port of L-BFGS-B instead of the Fortran code from 2017.
- The run used TF 2.21 in compat.v1 graph mode on CPU, not TF1 on a Titan X GPU. With the same seed, the random initialisation and LHS samples differ from the authors' run, so seed 1234 does not reproduce their exact network.
- Plotting (Figure 1) is disabled. It does not affect the metric.
- No iteration cap. maxiter = 50000 is kept, and L-BFGS stops by itself after at most 7.0k iterations.
- Multiple seeds were run. The paper reports single runs.

## Human effort (baseline for agent comparison)

There were 5 real fixes (pyDOE, plotting, compat.v1, ScipyOptimizerInterface, locating script and data) and 2 runs to the first number. The first number was not a good one: seed 1234 gave 1.1e-2, and multi-seed runs were needed to get the picture. The session took about 45 min wall-clock, from 16:40 to 17:25. That covers reading the paper and code, about 20 min of compute for 19 claim runs, and 9 diagnostic runs. A minimal 3-seed reproduction of the main claim would take about 20 min.
