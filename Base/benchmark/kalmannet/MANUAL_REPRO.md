# KalmanNet: manual reproduction (case 4)

Date: 2026-10-04 · Machine: Apple M4, 16 GB, CPU only (fanless; another job was running in parallel) · Python 3.11.16, torch 2.14.1 (CPU), numpy 2.4.6, scipy 1.17.1, matplotlib 3.11.2, seaborn 0.13.2 (uv venv `envs/kalmannet`)

## Result

The official code is `KalmanNet/KalmanNet_TSP`, branch `main`, commit 828a2cf. That branch is the batched refactor from Feb 2023 of **architecture #2**. In the paper, architecture #2 is setting **C4**, which the paper uses for Tables III/IV (sinusoidal toy model, not in this repo), Table VI (Lorenz, non-linear observations), Table VII (Lorenz, J=2) and Table IX (Lorenz decimation). The linear experiments (Fig. 5, Table I) used C1 (architecture #1), which exists only on the old `architecture-#1` branch. The paper is arXiv 2107.10043 **v3** (11 Mar 2022), which is the TSP version. All values are test MSE in dB. Each seed draws new train/CV/test data, a new initialisation and a new batch order.

| Claim (id) | Paper value (location) | Reproduced mean ± std (3 seeds) | Per seed (0, 1, 2) | Diff | Tol. | Pass |
|---|---|---|---|---|---|---|
| `knet_lin_T20` | −21.92 (Table I, row Test T=20, KalmanNet) | **−21.887 ± 0.031** | −21.854, −21.891, −21.916 | +0.03 | ±0.3 | yes |
| `kf_lin_T20` | −21.97 (Table I, row Test T=20, KF) | **−21.988 ± 0.092** | −21.891, −22.000, −22.074 | −0.02 | ±0.3 | yes |
| `knet_nlobs_30dB` | −15.24 (Table VI, KalmanNet, 1/r²=30 dB) | **−25.995 ± 0.233** | −25.829, −25.894, −26.262 | −10.8 | ±1.0 | **no** |
| `ekf_nlobs_30dB` | −4.02 (Table VI, EKF, 1/r²=30 dB) | **−25.043 ± 0.374** | −24.769, −24.890, −25.469 | −21.0 | ±1.0 | **no** |

Verbatim sources in the PDF:

- **Table I** ("Test MSE in [dB] when trained using T = 20."), row `20`: `-20.98 -21.53 -21.92 -21.92 -21.97`. The columns are Vanilla RNN, MB RNN, MB RNN diff., KalmanNet and KF.
- **Table VI** ("MSE [dB] – Lorenz attractor with non-linear observations"), column `30`: KalmanNet `-15.24`, EKF `-4.02`. Column `10`: KalmanNet `-1.77`, EKF `14.50`.

**Verdict: partial.** Table I reproduces closely with the architecture-#2 code. KalmanNet sits 0.04–0.16 dB above the KF (mean gap 0.10 ± 0.06 dB; the paper reports 0.05 dB), and both values land within 0.03 dB of the paper. Table VI does not reproduce. The official script with its own defaults, which match the paper's stated setting (T=20, ν=0 dB, 1/r²=30 dB), gives MSEs 10–21 dB lower than the paper for both KalmanNet and the EKF. The qualitative claim holds only weakly: KalmanNet beats the EKF by 0.95 ± 0.14 dB, while the paper reports 11.2 dB. Raw numbers: `results/linear_T20.csv` and `results/lorenz_nlobs.csv`. Logs: `results/logs/<claim>_s<seed>.log`.

### Diagnostic (not a claim): Table VI, 1/r² = 10 dB

| | Paper | Reproduced (3 seeds) |
|---|---|---|
| KalmanNet | −1.77 | −5.931 ± 0.280 (−5.794, −5.745, −6.253) |
| EKF | 14.50 | −4.766 ± 0.413 (−4.533, −4.523, −5.243) |

The 10 dB column shows the same pattern: our EKF is about 19 dB better than the paper's, and KalmanNet is about 4 dB better. The paper's EKF row (26.38, 21.78, 14.50, 4.84, −4.02) looks like a filter that does not converge. One possible explanation is a different initial-state setup in the paper's run, for example random initial states while the filter starts from x0 = 1 with P0 = 0. This could not be verified: the main-branch script has no such option enabled, and the old `architecture-#2` branch has no script for this experiment.

### Root cause of the Table VI gap (follow-up, see `DISCREPANCY.md`)

A follow-up study ran about 230 EKF and KalmanNet runs (logs: `results/logs/discrepancy_*.log`; table: `results/discrepancy_ablation.csv`). It replaces the guess in the paragraph above. The initial-state hypothesis was tested and rejected: an unknown x0 gives a flat +22 to +32 dB at every noise level.

- **EKF, confirmed.** The paper's EKF row (26.38 … −4.02) equals an EKF with **zero Kalman gain**, for example one told Q = 0 while P0 = 0, so that it propagates x0 = (1,1,1) open-loop and ignores the measurements. That filter gives 27.3 / 22.7 / 14.5 / 4.5 / −5.5 dB in the current code and 27.3 / 22.8 / 15.0 / 5.0 / −5.0 dB in the old architecture-#2 code: within 1.5 dB of all five paper values. No other single factor fits. The old code as released (its EKF uses the Jacobian of the linear h) does not reproduce the paper: it gives NaN at −10/0 dB and −21.7 dB at 30 dB.
- **KalmanNet, likely, cause unresolved.** Retraining with the paper's pure state-MSE loss gives −26.02 ± 0.22 dB, and the authors' own Dec-2021 checkpoint for this setting (`model_KNetNew_DT_HNL_r30q30_T20.pt`, recovered from the git history) gives −23.4 dB. Neither is near −15.24. The gap changes sign across noise levels, so the paper's KalmanNet row does not follow from the released code or checkpoints.

### Infeasible on CPU: Table IX (decimation, T = 3000)

`main_lor_decimation.py` took about **3.5 s per training step** (2-step timing run, `results/logs/timing_decimation_2steps.log`). The 2000 steps would therefore take about 2 h, far over the 5-min budget. The cost comes from the sequential Python loop over 3000 time steps, forward and backward, for each batch of 8, plus a 10 × 3000 CV pass every step. The training and CV MSE were also `nan` from step 0 in that run, so the line was stopped there. The EKF baseline is cheap and close: −6.27 dB vs the paper's −6.432 (Table IX).

## Steps and fixes

The upstream clone `repos/KalmanNet_TSP` is untouched. Fixes are applied in the copy `manual/KalmanNet_TSP/`, and the diff is `manual/kalmannet_cpu_fixes.patch` (it applies cleanly with `git apply` from the clone root):

1. `Exception: No GPU found, please set args.use_cuda = False`. All five `main_*.py` hard-code `args.use_cuda = True` after parsing the CLI. Fix: set it to `False`.
2. torch ≥ 2.6: `torch.load(path_results+'best-model.pt')` in `Pipeline_EKF.NNTest` loads a pickled `nn.Module`, which fails under the new `weights_only=True` default. Fix: pass `weights_only=False`.
3. `main_lor_DT_NLobs.py`: `TypeError: h_nonlinear() got an unexpected keyword argument 'jacobian'`. The batched EKF calls `getJacobian(x, h)` → `h(x, jacobian=True)`, and `h_nonlinear` did not accept the flag. Fix: return `(y, J)` with J computed by `torch.autograd.functional.jacobian` of `toSpherical(z).sum(0)`, a per-sample Jacobian of shape [B, n, m]. `parameters.py` has CRLF line endings, and the patch keeps them.
4. `main_lor_DT_NLobs.py`: `TypeError: unsqueeze() missing 1 required positional arguments: "dim"` in the CompositionLoss branch of `Pipeline_EKF.NNTrain`. Fix: `torch.unsqueeze(x_out_training_batch[:,:,t], 2)`.
5. No seed is set anywhere. Fix: `config.general_settings()` reads `SEED` and seeds `random`, `numpy` and `torch`. It also calls `torch.set_num_threads($OMP_NUM_THREADS)`.
6. Fixed output files: every run overwrites its dataset file and `KNet/best-model.pt`. Fix: a `RUN_TAG` env prefix on both, so runs cannot clash.
7. Setting overrides through env vars. The defaults stay as in upstream.
   - `main_linear_canonical.py`: `T`, `T_TEST`, `INV_R2_DB`, `NU_DB`, `N_STEPS`.
   - `main_lor_DT_NLobs.py`: `INV_R2_DB`, `N_STEPS`.
   - `main_lor_decimation.py`: `N_STEPS`. `N_STEPS` was used only for timing runs.

Fixes 1–4 are needed just to get a number. Fixes 5–7 are for multi-seed bookkeeping.

Environment:

```bash
uv venv --python 3.11 envs/kalmannet
VIRTUAL_ENV=envs/kalmannet uv pip install torch numpy matplotlib seaborn scipy
```

(`requirements.txt` pins torch 1.10.1, numpy 1.20.1 and pyParticleEst. Modern versions work after the fixes above, and pyParticleEst is not imported on main.)

Commands, run from `benchmark/kalmannet/`. `manual/run_seeds.sh` cds into the patched copy and runs one seed after another:

```bash
manual/run_seeds.sh lin_T20    0 1 2   # Table I:  T=20 INV_R2_DB=20 NU_DB=0 python main_linear_canonical.py
manual/run_seeds.sh nlobs_30dB 0 1 2   # Table VI: INV_R2_DB=30 python main_lor_DT_NLobs.py (= repo default)
manual/run_seeds.sh nlobs_10dB 0 1 2   # diagnostic, Table VI 10 dB column
```

All other settings are the repo defaults:

| Script | N_E / N_CV / N_T | Steps | Batch | lr | wd | Other |
|---|---|---|---|---|---|---|
| Linear | 1000 / 100 / 200 | 4000 | 30 | 1e-4 | 1e-3 | x0 = 0, P0 = 0 |
| NLobs | 1000 / 100 / 200 | 2000 | 100 | 1e-4 | 1e-4 | in_mult 40, out_mult 5, composition loss α = 0.5, x0 = 1, P0 = 0 |

In both scripts, the test model is the checkpoint with the best CV MSE. One "step" is a single random mini-batch followed by a full CV pass, not an epoch.

### Metric parsing

Each log contains exactly one of each line, and the evaluator uses the last match.

| Value | Regex |
|---|---|
| KalmanNet | `KalmanNet-MSE Test: tensor\((-?[0-9.]+)\) \[dB\]` |
| KF (linear) | `(?<!Extended )Kalman Filter - MSE LOSS: tensor\((-?[0-9.]+)\) \[dB\]` |
| EKF (Lorenz) | `Extended Kalman Filter - MSE LOSS: tensor\((-?[0-9.]+)\) \[dB\]` |

The negative lookbehind matters: without it, the KF regex also matches the EKF line. Evidence that training ran (set in `case.yaml` for the KalmanNet claims): `(?s)MSE Training : tensor.*KalmanNet-MSE Test:`. All 9 logs were checked with these regexes when building the CSVs.

## Paper vs code mismatches (traps)

- **Unstated noise level for Table I.** The paper only says "a 2×2 setup (similar to the previous one)". We inferred 1/r² = 20 dB, ν = 0 dB, H = I from the Riccati recursion. With F = [[1,1],[0,1]], H = I and Q = R = 0.01·I, the analytic KF MSE is −21.968 dB at T=20 and −21.916 dB at T=200. The table gives −21.97 and −21.91. The repo default for `main_linear_canonical.py` is a different setting (ν = −20 dB, 1/r² = 0 dB, T = 100; KF −7.24 dB on seed 0) that appears in no table. An agent that runs the script as shipped and reports its number compares the wrong setting.
- **H for the 2×2 case.** The paper text says H takes the inverse canonical form. The code uses H = I whenever m = 2, and only H = I reproduces Table I's KF value: with the inverse-canonical H the analytic KF would be −22.35 dB.
- **Architecture.** Table I was produced with C1 (architecture #1). The main branch only has architecture #2. Here it does not matter, since both reach the KF. The README's "this branch simulates architecture #2" is the only hint, and the paper's Section IV-A1 is needed to map C1–C4 to tables.
- **Loss.** The paper defines a pure state MSE with weight decay (eqs. 10, 13). `main_lor_DT_NLobs.py` instead trains with `CompositionLoss=True, alpha=0.5`, adding an observation-space term.
- **Hyperparameters exist only in code.** The paper gives no steps, batch size, lr, wd or dataset sizes; footnote 1 points to the repo. The older `architecture-#1` branch uses different values (500 epochs, lr 1e-3, wd 1e-5 for the linear case), so the choice of branch changes the protocol.
- **`type=bool` argparse flags.** Arguments such as `--use_cuda False` or `--randomInit_train False` parse as `True`. The scripts also overwrite most args after parsing, so CLI flags are mostly ignored. Change the settings in the `main_*.py` files instead.
- **Table VI is not reproducible from main.** Both KalmanNet and the EKF come out far better than the paper's numbers. An agent that "fixes" this by changing the setup until −15.24 / −4.02 appear, without saying so, is overfitting to the target.
- **Untrained or short runs.** At T=100 with repo defaults, KalmanNet's test MSE is +176 to +200 dB after 1–100 steps, a diverged filter. At T=20 it is −13.2 dB after 50 steps and −17.0 dB after 200. Cutting the 4000/2000 steps to save time gives clearly wrong numbers. The best CV step was 3975–3999 of 4000 (linear) and 1654–1999 of 2000 (Lorenz), so training had not fully plateaued even at the repo's budget.
- **Concurrent runs** clash on the dataset file and `KNet/best-model.pt` unless the file names are made unique.
- **Threads do not help.** With 1, 2 or 4 threads, 100 steps at T=100 took the same time (13.5–14.3 s): the small GRUs are bound by Python overhead.

## Runtimes

| Run | Wall time per run (M4 CPU, 2 threads, shared machine) | Dominated by |
|---|---|---|
| `lin_T20` (4000 steps) | 76–82 s | 20-step sequential loop × (batch 30 fwd+bwd + 100-seq CV pass) |
| `nlobs_30dB` / `nlobs_10dB` (2000 steps) | 63–72 s | the same, with T=20 and batch 100, plus composition loss |
| repo-default linear, T=100 (not run in full) | about 6 min, extrapolated from 80–90 ms/step | 100-step loop; over the 5-min budget, so not run |
| decimation, T=3000 (not run) | about 2 h, extrapolated from 3.5 s/step | 3000-step loop per step; NaN from step 0 |

Total compute was about 15 min: 9 claim/diagnostic runs of about 1.2 min each, plus timing runs.

## Deviations from the original

- CPU instead of GPU (Colab P100). Torch 2.14 instead of 1.10.
- Seeds 0, 1, 2 were added. Upstream is unseeded, and the paper reports single runs.
- The Table I numbers come from architecture #2 (main branch), not C1. The data, the KF and the noise setting follow the paper with the inferred r².
- The EKF Jacobian of the spherical observation uses autograd. This is mathematically identical to the analytic Jacobian, which upstream had lost in the batched refactor.
- Table I's T=200 row (generalisation to longer trajectories with different initial conditions) was not attempted.

## Human effort (baseline for agent comparison)

There were 4 real fixes (CUDA hard-code, `weights_only`, `h_nonlinear` Jacobian, `unsqueeze` dim) plus seeding. Inferring Table I's unstated noise level from the Riccati equation was the main thinking step. The session took about 35 min wall-clock (14:50–15:25): reading the paper and code (about 10 min), fixes and timing runs (about 8 min), 9 full runs (about 11 min of compute), and write-up. A minimal 3-seed reproduction of the Table I claims would take about 15 min.
