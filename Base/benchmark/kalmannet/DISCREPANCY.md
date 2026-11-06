# KalmanNet Table VI: why it does not reproduce

Date: 2026-10-04 · Apple M4, CPU only, `OMP_NUM_THREADS=4`, shared machine · venv `envs/kalmannet` (torch 2.14.1) · total compute about 20 min (EKF runs 2–5 s each, KalmanNet training runs 57–64 s each).

## Question

Table VI of the paper (Lorenz attractor, spherical observations, T = 20, ν = 0 dB) reports, for 1/r² = −10, 0, 10, 20, 30 dB:

| | −10 | 0 | 10 | 20 | 30 |
|---|---|---|---|---|---|
| EKF (paper) | 26.38 | 21.78 | 14.50 | 4.84 | −4.02 |
| KalmanNet (paper) | 14.55 | 6.77 | −1.77 | −10.57 | −15.24 |

The official code (`main` @ 828a2cf, CPU-patched copy in `manual/KalmanNet_TSP`) gives EKF −25.04 and KalmanNet −26.00 dB at 30 dB (3 seeds; see `MANUAL_REPRO.md`). Both are 10–21 dB *better* than the paper. The EKF has no training, so its 21 dB gap must come from the experimental setup (data, initial state, filter tuning, noise definitions or metric), not from the network. What is it?

## Answer in one paragraph

**The paper's EKF row is the error of a filter that ignores the measurements.** An EKF whose Kalman gain is identically zero simply propagates the known initial state x₀ = (1,1,1) through f, so its error is the accumulated, chaotically amplified process noise. That filter reproduces all five paper values within 1.5 dB, in both the current and the old code, for every seed. This happens whenever the EKF is told Q = 0 while P₀ = 0 (P₀ = 0 is the repo default), or equivalently when it is told an enormous R. Q ≲ 10⁻⁴·Q_true still comes within 2 dB. No other single factor tested comes within 4 dB of the paper at both 30 and 10 dB. The full-information EKF that the paper describes, with the true Q and R, gives −25 dB at 30 dB in the released code and −21.7 dB in the old code. So the paper's EKF row is not the baseline it claims to be. **Confidence: confirmed** for the mechanism. The exact line in the authors' private code that zeroed the gain is not in any public commit. **KalmanNet's** gap (−15.24 in the paper vs −26.0 reproduced) is a separate problem. Retraining with the paper's loss gives the same −26.0 dB. The authors' own Dec-2021 checkpoint for exactly this setting, which is in the repo history, gives −23.4 dB at 30 dB, but 25.3 dB at −10 dB, where the paper says 14.55. The paper's KalmanNet row therefore matches neither the released code nor the authors' released checkpoints. The gap is not a constant shift: the paper is worse than the checkpoint at high SNR and better at low SNR. **Confidence: likely** that the row cannot be produced from the described setup. **The specific cause is unresolved.**

## Code archaeology (step 1)

Full clone: `repos/KalmanNet_TSP_full` (not shallow). Branches: `main` (batched refactor, Feb 2023 → 828a2cf, Feb 2024), `architecture-#2` (5bce6e8; code up to Jan 2022 plus a README), and `architecture-#1` (cc097e1; Dec 2021 code). There are no tags. arXiv v3 (the TSP version) is from 11 Mar 2022, so the code closest to the paper is `architecture-#2` (Jan 2022, the "new architecture" commit c9c2be5 of 2022-01-11). Table VI used setting C4, which is architecture #2.

| What | Old code (`architecture-#1` / `-#2`, Jul 2021 – Jan 2022) | Current `main` |
|---|---|---|
| Script for Table VI | **none** on any branch or commit. The H_NL experiment only shows up as commented-out lines (`EKFResultName = 'EKF_nonLinearh_rq00_T20'`) and as `sys_model_partialh = SystemModel(f, q, h_nonlinear, r, ...)` in `main_lorenz.py@fe71ad7` | `main_lor_DT_NLobs.py` (added 2023-02-20) |
| Data | `SystemModel.GenerateBatch(..., randomInit=False)`: every sequence starts at `m1x_0 = ones(3,1)`, no chopping | same: `DataGen`, `randomInit_*=False`, `chop=False`, T = T_test = 20 |
| EKF init | `m1x_0 = ones`, `m2x_0 = 0·I` (P₀ = 0) | same |
| EKF Q, R | taken from the `SystemModel` (true Q = q²I, R = r²I) | same |
| EKF observation Jacobian | `getJacobian(x, 'ObsAcc')` is hard-wired to the **linear** `h` (H = I), even when `SystemModel.h = h_nonlinear` (**bug**) | `getJacobian(x, h)` → `h(x, jacobian=True)`. Upstream `h_nonlinear` does not accept that flag, so **the released EKF crashes** (TypeError). Our patch adds the correct autograd Jacobian |
| Spherical h | `toSpherical`: (ρ, θ = acos(z/ρ), φ = atan2(y,x) wrapped to [0, 2π)) | same, batched |
| MSE | `nn.MSELoss(reduction='mean')` per sequence over all 3 states and T steps, then a linear mean over sequences, then 10·log10 | same |
| Saved artefacts | `KNet/.../obsmis/H_NL/model_KNetNew_DT_HNL_{r-10q-10,r20q20,r30q30}_T20.pt`: arch-#2 `KalmanNetNN` checkpoints that pickle `model.h_nonlinear`, added 2021-12-18 (a12248e). Also `EKF_nonLinearh_rq00_T20_NT1000`, the authors' saved EKF result on H_NL at 0 dB with N_T = 1000, which contains only `NaN` | none |

Two points matter for what follows. First, the released Table VI code cannot produce an EKF number at all, so the paper's EKF row was not produced by it. Second, the data generation, initialisation and metric are the same in the old and new code, so a "different data setup in the old code" is not visible in the history.

## Hypotheses

| ID | Hypothesis (EKF row) | Test |
|---|---|---|
| H1 | The old code reproduces the paper (the refactor changed something) | E1: run the old EKF as released |
| H2 | Old-code bug: EKF uses the Jacobian of the linear h | E1, E2 (`h_jac identity`) |
| H3 | Unknown/random initial state: test sequences start elsewhere, but the EKF starts at (1,1,1) with P₀ = 0 | E2 (attractor windows, uniform and normal random x₀) |
| H4 | P₀ too small / too large | E2 (P₀ = 1, 100) |
| H5 | Mis-tuned filter Q (as in Table V, where Q was grid-searched) | E2 (Q × 10⁻³ … 10³), E3 (Q = 0) |
| H6 | Longer test trajectories (T = 200, 2000) | E2 |
| H7 | Different noise definition (ν = +20 dB instead of 0 dB) | E2 |
| H8 | Different MSE averaging (mean of dB, median) | every run also logs the mean of per-sequence dB and the median |

## Experiments and results

Every run is logged in `results/logs/discrepancy_<name>.log`, one `RUN ...` header per run. All 230 runs are in `results/discrepancy_ablation.csv`. Values are 10·log10 of the mean per-sequence MSE (the repo metric), given as mean ± std over seeds 0, 1, 2, with N_T = 200 test sequences unless stated otherwise.

### E1: old code as released (`architecture-#2` @ 5bce6e8)

`manual/KalmanNet_TSP_old` is `git archive origin/architecture-#2` with one fix: `filing_paths.path_model` pointed to the toy model, so `discrepancy/old_code_fixes.patch` points it to the Lorenz model. Since the old code has no Table VI script, `discrepancy/eval_old.py` wires only old components (`KalmanNet_sysmdl.SystemModel`, `EKF_test.EKFTest`, `model.h_nonlinear`), following the pattern of the old `main_lorenz.py@fe71ad7`.

| 1/r² [dB] | −10 | 0 | 10 | 20 | 30 |
|---|---|---|---|---|---|
| Old EKF as released (H = I bug) | NaN (3–10 diverged seqs; median 25.4) | NaN (8–14 diverged; median 8.8) | −0.92 ± 0.45 | −11.06 ± 0.29 | **−21.71 ± 0.31** |
| Old EKF, correct Jacobian | 24.94 ± 0.26 | 13.80 ± 0.52 | −6.18 ± 0.36 | −15.89 ± 0.57 | −26.45 ± 0.34 |
| Paper EKF | 26.38 | 21.78 | 14.50 | 4.84 | −4.02 |

**H1 rejected.** The old code does not reproduce the paper. As released, it diverges to NaN at −10 and 0 dB. This matches the authors' own saved `EKF_nonLinearh_rq00_T20_NT1000`, which is all NaN. At 10–30 dB it is about 16–18 dB better than the paper. The Jacobian bug (H2) costs 4–5 dB and causes divergence, but it does not explain the paper.

### E2: single-factor ablations on the current code

`discrepancy/ekf_ablation_main.py` changes one thing at a time relative to `main_lor_DT_NLobs.py`. It uses only repo components: `SystemModel`, `Short_Traj_Split` and the batched `ExtendedKalmanFilter`. The baseline reproduces the earlier result (−25.08 / −4.90).

| Factor changed (everything else = repo default) | 30 dB | 10 dB | Δ vs paper (30 / 10) |
|---|---|---|---|
| none (baseline) | −25.08 ± 0.15 | −4.90 ± 0.10 | −21.1 / −19.4 |
| **EKF told Q = 0 (zero gain, open loop)** | **−5.46 ± 0.19** | **14.54 ± 0.42** | **−1.4 / +0.0** |
| EKF told R × 10⁶ (gain ≈ 0) | −5.51 ± 0.19 | 14.48 ± 0.42 | −1.5 / −0.0 |
| EKF Q × 10⁻³ | −16.13 ± 0.10 | 3.68 ± 0.12 | −12.1 / −10.8 |
| EKF Q × 10⁻² | −23.01 ± 0.15 | −3.01 ± 0.19 | −19.0 / −17.5 |
| EKF Q × 10² | −15.03 ± 0.14 | 13.18 ± 1.44 | −11.0 / −1.3 |
| EKF Q × 10³ | −8.46 ± 0.05 | 20.11 ± 1.04 | −4.4 / +5.6 |
| P₀ = 1·I | −24.83 ± 0.15 | −4.82 ± 0.09 | −20.8 / −19.3 |
| P₀ = 100·I | −24.83 ± 0.15 | −4.67 ± 0.09 | −20.8 / −19.2 |
| x₀ unknown: T-windows chopped from long trajectories, EKF at (1,1,1), P₀ = 0 | 22.54 ± 0.15 | 22.58 ± 0.14 | +26.6 / +8.1 |
| same, P₀ = 100·I | 22.25 ± 0.16 | 22.31 ± 0.16 | +26.3 / +7.8 |
| attractor windows, EKF given the true x₀ | −14.94 ± 2.68 | −1.27 ± 1.05 | −10.9 / −15.8 |
| x₀ ~ U[0,100)³ (repo `randomInit`, `variance=100`), EKF at (1,1,1) | 31.91 ± 0.74 | 31.88 ± 0.62 | +35.9 / +17.4 |
| x₀ ~ N((1,1,1), I), EKF at (1,1,1), P₀ = 0 | −9.22 ± 0.20 | −0.52 ± 4.28 | −5.2 / −15.0 |
| T = 200 | −6.65 ± 2.70 | 2.00 ± 1.03 | −2.6 / −12.5 |
| T = 2000 (N_T = 100) | −9.97 ± 0.90 | 1.98 ± 0.90 | −6.0 / −12.5 |
| old-code Jacobian bug (H = I) | −21.87 ± 0.24 | −1.27 ± 0.29 | −17.9 / −15.8 |
| ν = +20 dB (q² = 100 r²) | 3.70 ± 1.63 | 21.33 ± 0.53 | +7.7 / +6.8 |

Why only zero gain fits: the paper's EKF falls by about 9–10 dB per 10 dB of SNR at the high end and saturates near 27 dB at the low end. An unknown x₀ (H3) gives an error *floor* that is the same at every noise level, because with ν = 0 the gain is scale-invariant and the initial error decays at the same rate everywhere. Its 30 dB and 10 dB values are therefore equal, which is wrong at 30 dB by 26 dB. P₀ (H4) barely matters with a known x₀. Longer T (H6) and ν (H7) move the two columns by different amounts. Over-large Q moves the 10 dB column but not the 30 dB column. The metric (H8) is not the cause either: the mean of per-sequence dB and the median are 1–3 dB *lower* than the repo metric in every configuration (columns `ekf_mean_of_dB` and `ekf_median_dB` in the CSV), so a different averaging would widen the gap.

### E3: the zero-gain filter across the whole row (decisive)

| 1/r² [dB] | −10 | 0 | 10 | 20 | 30 | max \|Δ\| |
|---|---|---|---|---|---|---|
| Paper EKF | 26.38 | 21.78 | 14.50 | 4.84 | −4.02 | |
| Current code, EKF Q = 0 (3 seeds) | 27.29 ± 0.13 | 22.70 ± 0.36 | 14.54 ± 0.42 | 4.54 ± 0.26 | −5.46 ± 0.19 | 1.44 |
| Current code, EKF R × 10⁶ (3 seeds) | 27.27 ± 0.13 | 22.66 ± 0.36 | 14.48 ± 0.42 | 4.48 ± 0.25 | −5.51 ± 0.19 | 1.49 |
| Current code, EKF Q = 0, N_T = 1000 (seed 0) | 27.35 | 22.73 | 14.63 | 4.70 | −5.29 | 1.27 |
| Old code, EKF Q = 0 (3 seeds) | 27.27 ± 0.25 | 22.78 ± 0.13 | 14.96 ± 0.18 | 4.99 ± 0.13 | −5.03 ± 0.11 | 1.01 |
| Old code as released, EKF Q × 10⁻⁶ (seed 0) | 27.56 | 22.89 | 14.98 | 5.07 | −4.94 | 1.18 |
| Old code as released, EKF Q × 10⁻⁴ (seed 0) | 27.32 | 22.44 | 14.09 | 4.07 | −5.94 | 1.92 |
| Old code as released, EKF Q × 10⁻³ (seed 0) | 26.72 | 21.01 | 10.77 | 0.59 | −9.42 | 5.40 |
| Current code, true Q (baseline) | 25.09 ± 0.26 | 15.13 ± 0.55 | −4.90 ± 0.10 | −14.61 ± 0.15 | −25.08 ± 0.15 | 21.06 |

The runs print `max |K| = 0` for the Q = 0 filter, which confirms that it never uses an observation. All five paper values sit within 0.0–1.5 dB of this "ignore the measurements" filter. The fit holds in both code bases, with or without the Jacobian bug (with K = 0 the Jacobian is irrelevant), for 3 seeds and for N_T = 1000. The residual is about the seed-to-seed spread of a single 200-sequence run (std up to 0.4 dB), plus the paper's single unseeded run. The fit degrades smoothly once the filter's Q rises above about 10⁻⁴·Q_true.

A plausible story, which is not verifiable: the as-released old EKF produced NaN on this task (E1, and the authors' saved NaN file). The paper says that for Table V they "had to perform a grid search … to optimize the process noise Q used by the filter" to stabilise the EKF. Driving Q → 0 with P₀ = 0 does remove the NaNs, because the filter stops correcting, but it also turns the EKF into open-loop prediction. Note, however, that Q × 0.1 already removes the NaNs and is 10–20 dB better (E3 grid), so a min-MSE grid search would not have chosen Q ≈ 0. The exact way the authors' filter ended up with zero gain stays unknown.

### E4: the authors' own KalmanNet checkpoints (Dec 2021)

The three checkpoints `model_KNetNew_DT_HNL_{r30q30,r20q20,r-10q-10}_T20.pt` were extracted from the history (`manual/scratch_old/`) and evaluated with the old code's test loop (`Pipeline_EKF.NNTest` logic, init at m1x_0) on freshly generated old-code data, 3 seeds:

| 1/r² [dB] | 30 | 20 | −10 |
|---|---|---|---|
| Authors' checkpoint, fixed x₀ = (1,1,1) data (as in the code) | **−23.36 ± 0.25** | −14.23 ± 0.34 | 25.27 ± 0.35 |
| Same checkpoint, attractor windows with known x₀ | 11.73 ± 1.31 | 14.15 ± 0.61 | – |
| Paper KalmanNet | −15.24 | −10.57 | 14.55 |
| Reproduced KalmanNet, current code (`MANUAL_REPRO.md`; −10 dB: E5, seed 0) | −26.00 ± 0.23 | – | 22.84 |

The checkpoint works only on data that start at (1,1,1). On attractor windows it fails, at +12 to +14 dB. So the authors trained on the same fixed-x₀ data that the code generates. This rules out "the paper used random or chopped initial states" for KalmanNet as well. Its 30 dB error (−23.4) is 8 dB better than the paper, and its −10 dB error (25.3) is 10.7 dB *worse* than the paper. The paper's KalmanNet row is not a shifted version of either the released code or the authors' checkpoints.

### E5: KalmanNet training diagnostics (current code)

| Run | 1/r² [dB] | Seeds | KalmanNet [dB] | Paper |
|---|---|---|---|---|
| Repo default (CompositionLoss = True, α = 0.5), from `MANUAL_REPRO.md` | 30 | 0, 1, 2 | −26.00 ± 0.23 | −15.24 |
| Paper loss (pure state MSE, eqs. 10/13), `discrepancy/knet_train_main.py COMPOSITION_LOSS=0` | 30 | 0, 1, 2 | **−26.02 ± 0.22** (−25.85, −25.95, −26.27) | −15.24 |
| Repo default | 0 | 0 | 7.61 | 6.77 |
| Repo default | −10 | 0 | 22.84 | 14.55 |

The loss mismatch between paper and code (composition loss) is not the cause: the two losses give the same result. Across the noise levels, the reproduced KalmanNet is 22.84 / 7.61 / −5.93 / – / −26.00 dB against the paper's 14.55 / 6.77 / −1.77 / −10.57 / −15.24. The difference is +8.3, +0.8, −4.2 and −10.8 dB, so it changes sign: the paper's curve is much flatter (30 dB of change over 40 dB of SNR, against 49 dB here). That rules out any single shift in SNR, noise definition or metric for KalmanNet, and the authors' checkpoints show the same pattern (E4). Step 4 of the plan, "train KalmanNet under the identified paper-like setting", is the same as the baseline here. The identified factor only changes the EKF's tuning, not the data or KalmanNet, so the result under that setting is already −26.00 ± 0.23 dB.

## Conclusion

| Claim | Root cause | Confidence |
|---|---|---|
| `ekf_nlobs_30dB` (paper −4.02, reproduced −25.04) | The paper's EKF row equals, within 1.5 dB at all five noise levels, a zero-gain EKF: open-loop propagation of the known x₀ through f, which happens for Q_filter ≈ 0 with P₀ = 0 or R_filter → ∞. The full-information EKF with true Q and R that the paper describes gives −25 dB (released code, with the missing Jacobian added) or −21.7 dB (old code, Jacobian bug). The released code cannot run this EKF at all, and the old code has no Table VI script, so the configuration behind the paper's row was never published. | **confirmed** (mechanism); the exact private code path is unknown |
| `knet_nlobs_30dB` (paper −15.24, reproduced −26.00) | Not explained by any setup factor. Neither the paper's loss nor the authors' own released checkpoint (−23.4 dB at 30 dB; 25.3 dB vs the paper's 14.55 at −10 dB) reproduces the row. The data setup is the same as in the code (the checkpoint only works on fixed-x₀ data). The gap is not a constant shift, so the row probably comes from an unpublished run or checkpoint. The paper's headline result, KalmanNet beating the EKF by 11 dB at 30 dB, is an artefact of the zero-gain EKF baseline: against a working EKF the margin is about 1 dB (−26.0 vs −25.0). | **likely** (not producible from the described setup); specific cause **unresolved** |

## What an agent needs to notice to diagnose this

1. **The EKF has no training**, yet it is also about 20 dB off. Therefore the gap cannot come from network size, training budget, seeds or loss, and an honest reproduction should not "fix" KalmanNet hyperparameters to close it.
2. **The size of the EKF's gap is nearly constant at high SNR** (about 20 dB at 10, 20 and 30 dB), while the paper's EKF still falls about 9 dB per 10 dB and saturates near 27 dB. This is the signature of a filter that does not use the observations. Running the EKF with Q = 0, or with K forced to 0 (open-loop f(x₀)), and seeing all five paper values reappear is the decisive check. It costs seconds.
3. **The released script cannot produce the EKF number at all** (`h_nonlinear()` has no `jacobian` argument), so the paper's EKF row was produced by other code.
4. Optional, deeper: the old branches have no Table VI script, and their EKF hard-wires the linear-h Jacobian. The authors' saved EKF result for this task is NaN. Their Dec-2021 KalmanNet checkpoints give −23.4 dB at 30 dB, not −15.24.
5. Wrong diagnoses to penalise: "random initial states in the paper" (gives a flat +22 to +32 dB error), "CPU vs GPU / torch version", "too few training steps", "different MSE averaging" (alternative averages are *lower*, which widens the gap), and "our Jacobian fix is wrong" (the same numbers come out of the old code with the old Jacobian).

## Files and how to re-run

- `discrepancy/ekf_ablation_main.py`: single-factor EKF ablations on the current code. Run from `manual/KalmanNet_TSP`.
- `discrepancy/eval_old.py`: old-code (architecture-#2) EKF and checkpoint evaluation. Run from `manual/KalmanNet_TSP_old`, which is ignored by git; the re-create commands are in `.gitignore`. `discrepancy/old_code_fixes.patch` is the only change to the old code.
- `discrepancy/knet_train_main.py`: runs the patched `main_lor_DT_NLobs.py` with a `COMPOSITION_LOSS` override, without editing it.
- `discrepancy/run_ekf_ablations.sh` (`PART=main|old|qgrid|all`, about 10 min in total), `discrepancy/run_knet_diagnostics.sh` (about 5 min), and `discrepancy/summarize.py`, which writes the logs to `results/discrepancy_ablation.csv` and prints the mean ± std table. Run all of them from `benchmark/kalmannet/`.
- `manual/scratch_old/`: the authors' checkpoints, extracted with `git show 'origin/architecture-#1:KNet/Lorenz/DT case/model/obsmis/H_NL/model_KNetNew_DT_HNL_<r>_T20.pt'`.
