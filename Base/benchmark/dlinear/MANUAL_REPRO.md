# DLinear (LTSF-Linear) — manual reproduction

Date: 2026-10-04 · Machine: Apple M4, 16 GB, CPU only, 4 threads (`OMP_NUM_THREADS=MKL_NUM_THREADS=4`, `torch.set_num_threads(4)`) · Python 3.11, torch 2.14.1 (CPU), numpy 2.x, pandas, scikit-learn 1.9.1 (uv venv `envs/dlinear`)

## Result

Official code `cure-lab/LTSF-Linear` (commit 0c11366, 2024-01-28), model `DLinear`, multivariate (`--features M`), look-back `seq_len=336`, hyperparameters from `scripts/EXP-LongForecasting/Linear/{etth1,etth2,ettm1}.sh`: ETTh1 batch 32 / lr 0.005, ETTh2 batch 32 / lr 0.05, ETTm1 batch 8 / lr 1e-4; all other settings are the defaults (Adam, MSE loss, 10 epochs max, early stopping patience 3 on validation loss, LR halved every epoch, moving-average kernel 25, shared (non-individual) linear layers). The metric is test MSE on z-score-normalised data (scaler fitted on the train split, 12/4/4-month split), averaged over all 7 variates. Ten seeds per claim: 2021 (upstream default) and 0-8.

Target values are copied from arXiv v3 (17 Aug 2022), Table 2, column DLinear*, MSE:

> ETTh1 `96 0.80% 0.375 0.397 0.374 0.394 0.375 0.399 ...` / `336 6.54% 0.479 0.476 0.429 0.427 0.439 0.443 ...` / `720 13.04% 0.624 0.592 0.440 0.453 0.472 0.490 ...`
> ETTh2 `96 19.94% 0.288 0.352 0.277 0.338 0.289 0.353 ...` · ETTm1 `96 21.10% 0.308 0.352 0.306 0.348 0.299 0.343 ...`

Row format: horizon, IMP., Linear MSE/MAE, NLinear MSE/MAE, **DLinear MSE**/MAE, ... These cells are identical in the AAAI 2023 proceedings Table 2 and in arXiv v1/v2 Table 2 (column "DLinear-S"). The README notes that "some results of DLinear are slightly different" after the Aug 2022 script update, but none of the cells used here changed.

| Claim (id) | Paper | Reproduced mean ± std (10 seeds) | Median | Min–max | Seed 2021 | Median dev. | Tolerance (median) | Pass |
|---|---|---|---|---|---|---|---|---|
| `etth1_96_mse`  | 0.375 | 0.3793 ± 0.0106 | 0.3740 | 0.3713–0.4038 | 0.3841 | −0.3% | rel 5%  | yes |
| `etth1_336_mse` | 0.439 | 0.4594 ± 0.0279 | 0.4473 | 0.4373–0.5210 | 0.4469 | +1.9% | rel 10% | yes |
| `etth2_96_mse`  | 0.289 | 0.2936 ± 0.0083 | 0.2935 | 0.2750–0.3046 | 0.2901 | +1.6% | rel 7%  | yes |
| `ettm1_96_mse`  | 0.299 | 0.3013 ± 0.0012 | 0.3010 | 0.3002–0.3044 | 0.3012 | +0.7% | rel 3%  | yes |
| (diagnostic) ETTh1 T=720 | 0.472 | 0.5167 ± 0.0485 | 0.4993 | 0.4781–0.6150 | 0.5042 | +5.8% | not a claim | — |

**Verdict: full reproduction** of the four claims (median of 10 seeds, and also median of seeds 0-2, within tolerance). The values are not exact: the medians sit within 2% of the paper, but individual seeds scatter by up to +19% (ETTh1-336). The upstream default seed 2021 alone gives 0.384 on ETTh1-96, +2.4% above the paper.

ETTh1 T=720 was run as well and left out of the claims. All 10 seeds are above the paper's 0.472 (best 0.478), and the median is +5.8%. The paper's number first looked like a favourable single GPU run. It is not: the number comes from an earlier code version, see "ETTh1 T=720 discrepancy" below. A faithful 3-seed run would pass a 10% tolerance only about 82% of the time, which is too unreliable for a ground-truth claim.

Why the seed spread is large: with LR halving every epoch and patience 3, some seeds stop after 4-6 epochs, and these are exactly the bad seeds. Examples are ETTh1-336 seed 6 (5 epochs, 0.521) and ETTh1-720 seed 0 (5 epochs, 0.615). Seeds that run all 10 epochs land near the paper value. On CPU the code is bit-for-bit deterministic for a given seed (seed 2021 was re-run and gave an identical MSE).

Raw numbers: `results/dlinear_runs.csv`, one row per run (mse, mae, drop_last variant, number of test windows, epochs run, wall time). Logs: `results/logs/<claim>_s<seed>.log`.

## ETTh1 T=720 discrepancy (resolved)

The T=720 gap is explained in [`DISCREPANCY.md`](DISCREPANCY.md); the cause is confirmed. Table 2's DLinear numbers come from the code as it was before the 2022-08-15 update (upstream `721ab58`). That version initialises the linear weights to 1/L, and its ETTh1 script uses batch 8 with lr 1e-4. Run with seed 2021, it gives **0.4719 / 0.4902** at T=720, which matches the paper's 0.472 / 0.490 exactly. It also matches T=96/192/336, ETTh2-96 and ETTm1-96 to 3 decimals. The current scripts (random init, batch 32, lr 0.005) are less stable at T=720, because patience-3 early stopping picks under-trained checkpoints. With 10 paper-era-config seeds the median is 0.475 (std 0.004). The earlier guess that the paper's number was "a favourable single GPU run" is therefore wrong. Runs: `results/discrepancy_etth1_720.csv`, logs `results/logs/discrepancy_*.log`, scripts in `discrepancy/`. DISCREPANCY.md also contains a proposed `etth1_720_mse` claim and root-cause entry, which have not been applied to `case.yaml`.

## Tolerance argument

The rubric uses the **median** over at least 3 seeds, because the early-stopping failures make the error distribution heavy-tailed on the upper side. To set the tolerances, we took all C(10,3) = 120 three-seed subsets of our faithful runs and checked how often their median falls within tolerance:

| Claim | Max dev. of median-of-3 | Pass rate @3% / 5% / 7% / 10% | Chosen |
|---|---|---|---|
| etth1_96  | 3.9% | 0.93 / 1.00 / 1.00 / 1.00 | 5%  |
| etth1_336 | 11.9% | 0.67 / 0.82 / 0.82 / 0.93 | 10% |
| etth2_96  | 5.0% | 0.93 / 0.93 / 1.00 / 1.00 | 7%  |
| ettm1_96  | 0.9% | 1.00 / 1.00 / 1.00 / 1.00 | 3%  |

So a faithful 3-seed run gets "full" with roughly 93% probability; the residual risk comes from etth1_336.

We also checked whether the tolerances reject wrong setups:

| Wrong setup | Result | Caught? |
|---|---|---|
| Transformer-default look-back L=96 instead of 336 (`diag_*_L96` logs, 3 seeds) | ETTm1-96 0.345 (+15%) | yes, ettm1_96 fails |
| Same, ETTh1-96 | 0.391 (+4.3%) | no, still inside 5% |
| MSE on inverse-transformed (raw-unit) data | ETTh1-96 ≈ 8.56 | yes |
| Univariate setting (S, target OT) | paper's own univariate table gives 0.056 for ETTh1-96 (not run here) | yes |

The L=96 case shows the limit of this case: ettm1_96 is the claim that detects a wrong look-back window, because etth1_96 alone would not.

## Steps and fixes

The upstream clone `repos/LTSF-Linear` is untouched. The patched copy is `manual/LTSF-Linear/`, with `dataset -> ../../data` as a symlink. The diff is `manual/ltsf_linear_cpu_modern.patch`; it applies cleanly to upstream with `git apply`.

1. **Data.** ETTh1/ETTh2/ETTm1 CSVs come from the official ETDataset repo, `https://raw.githubusercontent.com/zhouhaoyi/ETDataset/main/ETT-small/<name>.csv` (repo HEAD 1d16c8f). The paper's footnote 2 cites this repo. The README instead points to the Autoformer Google Drive copy, which was not downloaded, so byte-equality with it is unverified. Files: 17,421 / 17,421 / 69,681 lines (incl. header), with sha256 values:
   - ETTh1 `f18de3ad269cef59bb07b5438d79bb3042d3be49bdeecf01c1cd6d29695ee066`
   - ETTh2 `a3dc2c597b9218c7ce1cd55eb77b283fd459a1d09d753063f944967dd6b9218b`
   - ETTm1 `6ce1759b1a18e3328421d5d75fadcb316c449fcd7cec32820c8dafda71986c9e`
2. **`AttributeError: np.Inf was removed in the NumPy 2.0 release`** (utils/tools.py, EarlyStopping) → `np.inf`.
3. **macOS hang with the default `--num_workers 10`.** DataLoader workers use the spawn start method, and `run_longExp.py` has no `if __name__ == '__main__'` guard. Each worker re-imports the script and raises the multiprocessing "bootstrapping phase" `RuntimeError`; the run hung and had to be killed (`results/logs/fail_num_workers10_macos_spawn.log`). Fix: pass `--num_workers 0` on the command line. This does not change results, because the shuffling sampler runs in the main process. No code change was needed.
4. **Seed hard-coded** (`fix_seed = 2021`) → read from the `SEED` env var, default 2021. Also `torch.set_num_threads(TORCH_NUM_THREADS, default 4)`.
5. **Extra report line, not a fix.** The test loader had `drop_last=True` when the paper was written; upstream changed it to `False` on 2023-03-15 (commit 6fe4c28). The patched `test()` therefore also prints `droplast_mse:` computed on the first floor(N/bs)·bs windows. This is equivalent to the old behaviour, because the test loader is not shuffled. The difference is at most 0.0001 MSE for the four claims and 0.0013 for ETTh1-720. The claims use the upstream `mse:` line.
6. **GPU/MPS.** No change needed: `use_gpu` is forced to False when CUDA is unavailable, and MPS is never used. Note that `--use_gpu False` would be parsed as True (`type=bool`).

Environment:

```bash
uv venv --python 3.11 envs/dlinear
VIRTUAL_ENV=envs/dlinear uv pip install torch numpy pandas scikit-learn matplotlib
```

Commands (from `benchmark/dlinear/`). `manual/run_seeds.sh` runs the seeds sequentially, writes one log per seed and appends to the CSV:

```bash
manual/run_seeds.sh etth1_96_mse  ETTh1 96  32 0.005  2021 0 1 2 3 4 5 6 7 8
manual/run_seeds.sh etth1_336_mse ETTh1 336 32 0.005  2021 0 1 2 3 4 5 6 7 8
manual/run_seeds.sh etth2_96_mse  ETTh2 96  32 0.05   2021 0 1 2 3 4 5 6 7 8
manual/run_seeds.sh ettm1_96_mse  ETTm1 96  8  0.0001 2021 0 1 2 3 4 5 6 7 8
manual/run_seeds.sh etth1_720_mse ETTh1 720 32 0.005  2021 0 1 2 3 4 5 6 7 8   # diagnostic
SEQ_LEN=96 manual/run_seeds.sh diag_ettm1_96_L96 ETTm1 96 8 0.0001 0 1 2       # wrong-look-back diagnostic
# single run by hand (inside manual/LTSF-Linear):
SEED=0 OMP_NUM_THREADS=4 ../../../../envs/dlinear/bin/python -u run_longExp.py --is_training 1 \
  --root_path ./dataset/ --data_path ETTh1.csv --model_id ETTh1_336_96 --model DLinear --data ETTh1 \
  --features M --seq_len 336 --pred_len 96 --enc_in 7 --des Exp --itr 1 --batch_size 32 \
  --learning_rate 0.005 --num_workers 0
```

## Metric parsing

The final metric line is printed once per run by `Exp_Main.test()`, e.g. `mse:0.3841443657875061, mae:0.404712975025177`. Parse it with:

```
(?m)^mse:([0-9.eE+-]+), mae:
```

The value is used as-is (scale 1). This regex was checked against all 56 run logs and matches the CSV exactly. Do not use the unanchored `mse:([0-9.]+)`: its last match is our extra `droplast_mse:` line. Do not use the per-epoch `Test Loss:` lines either: they are an unweighted mean of per-batch losses, logged during training. The case's `evidence_pattern` additionally requires that training actually ran: `(?s)Epoch: 1, Steps: \d+ \| Train Loss.*\nmse:[0-9.]+, mae:`.

## Traps an agent could fall into

**Data and setting**

- **Wrong look-back.** The repo's `run_longExp.py` default is `seq_len 96`, and the Transformers in the paper use 96. LTSF-Linear uses 336 (Appendix B.2 and the scripts). On ETTm1 this costs +15% MSE.
- **Wrong per-dataset hyperparameters.** ETTh2 uses lr 0.05 and ETTm1 uses batch 8 / lr 1e-4. Copying the ETTh1 settings, or the `run_longExp.py` defaults (lr 1e-4, batch 32), is wrong.
- **Univariate vs multivariate.** Table 2 is `--features M`. Appendix Table 9 (univariate, `--features S`) has values around 0.05-0.1.
- **Normalisation.** Table 2 MSE is on standardised data. Inverse-transforming gives about 8.6 on ETTh1-96. Reporting only the OT channel gives 0.10.
- **Dataset version.** The ETT CSVs must be the ETDataset `ETT-small` files. Splits are hard-coded by row count (12/4/4 months for ETTh, ×4 for ETTm), so a different file length silently shifts the splits. For ETTm1, the script does not pass `--freq t`; this is irrelevant for DLinear, which ignores time features.

**Evaluation and logging**

- **drop_last.** The current upstream test loader keeps all windows; the paper-era code dropped the last partial batch. The difference is negligible here (≤ 0.0013) but is a legitimate source of tiny discrepancies.
- **Concurrent runs of the same setting** overwrite each other's `checkpoints/<setting>/checkpoint.pth`, because the setting string does not contain the seed, and the run reloads the "best" checkpoint before testing.
- **Single seed.** The paper reports one run (`--itr 1`, seed 2021). On CPU, seed 2021 gives 0.384 on ETTh1-96, so one-seed comparisons are noisy. Use ≥3 seeds and the median.
- **Table extraction.** pypdf mangles the Table 2 header (`Linear* NLinear* DLinear* ... MSE MSE MAE`). DLinear MSE is the 6th value after the horizon. Linear/NLinear/DLinear values are close to each other (0.375 / 0.374 / 0.375 on ETTh1-96), so reading the wrong column is easy and partly hidden.

## Runtimes

Each run takes 7-13 s for ETTh1/ETTh2 and 19-40 s for ETTm1 (batch 8, about 4,280 steps per epoch), wall-clock on the M4 CPU with 4 threads, with another job running in parallel.

| Work | Runs | Wall time |
|---|---|---|
| 5 settings × 10 seeds | 50 | 690 s |
| Diagnostics | 6 | 90 s |
| Whole case incl. 4 smoke/determinism runs | ≈ 60 | ≈ 14 min |

A minimal 3-seed reproduction of the four claims takes about 3 min of compute.

## Human effort (baseline for agent comparison)

The first number took 2 real fixes (`np.Inf`; `--num_workers 0` on macOS) plus the seed patch for multi-seed runs. It came from the third run (the first crashed on `np.Inf`, the second hung on worker spawn). The session took about 30 min wall-clock, 14:50-15:20. That covers paper/version checks (arXiv v1/v2/v3 and AAAI), git history of the scripts and the drop_last change, data download, and 56 runs.
