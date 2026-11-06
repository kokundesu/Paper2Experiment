# FITS — manual reproduction

Date: 2026-10-04/05 · Machine: Apple M4, 16 GB, CPU only, 4 threads (`OMP_NUM_THREADS=MKL_NUM_THREADS=4`, `torch.set_num_threads(4)`), shared with two other jobs · Python 3.11.16, torch 2.14.1 (CPU), numpy 2.4.6, pandas 3.0.6, scikit-learn 1.9.1, matplotlib 3.11.2, thop 0.1.1, einops 0.8.2 (uv venv `envs/fits`)

## Result

Official code `VEWOXIC/FITS` (commit d040bb0, 2025-06-04). Since `3583ec5` (2024-01-09), which fixed the model dispatch, the FITS training path has had only cosmetic changes. Entry point `run_longExp_F.py`, model `FITS`, multivariate (`--features M`). Hyperparameters come from `scripts/FITS/{etth1,etth2,ettm1}_best.sh`, which the README describes as the multi-run scripts on the chosen parameters:

| Claim | Look-back `seq_len` | `H_order` | `base_T` | → `cut_freq` | `train_mode` | Complex linear layer | Params |
|---|---|---|---|---|---|---|---|
| ETTh1-96  | 360 | 6  | 24 | 106 | 1 | 106 → 134 | 14,338 |
| ETTh1-720 | 360 | 6  | 24 | 106 | 1 | 106 → 318 | 34,026 |
| ETTh2-96  | 720 | 6  | 24 | 196 | 2 | 196 → 222 | 43,734 |
| ETTm1-96  | 360 | 14 | 96 | 66  | 1 | 66 → 83   | 5,561  |

Shared settings: lr 5e-4 (Adam, MSE loss), `--batch_size 64` (which `run_longExp_F.py` doubles to an effective 128, the README's "batch size 128"), patience 20 on the validation loss, `lradj type3` (LR × 0.95 every epoch), a shared (non-individual) layer for all 7 channels, and `train_epochs` 50 (the released default). `cut_freq = (seq_len // base_T + 1) · H_order + 10`. `train_mode` 1 trains on the forecast horizon only. `train_mode` 2 first trains on look-back+horizon reconstruction and then fine-tunes on the horizon; it runs two training phases.

The metric is test MSE on z-score-normalised data (scaler fitted on the train split, 12/4/4-month split), over all test windows (`drop_last=False`, the bug fix) and all 7 variates. Seeds: the five official seeds 514, 1919, 810, 0, 114 (the seeds of the official logs), plus 2021, 1, 2 for the ETTh claims.

Target values are copied from arXiv v3 (5 Jan 2024), Table 1, FITS row:

> `FITS 0.372 0.404 0.427 0.424 0.271 0.331 0.354 0.377 0.303 0.337 0.366 0.415 ...` (ETTh1 96/192/336/720, ETTh2 96/.../720, ETTm1 96/...)

The ICLR 2024 proceedings Table 1 and the README "Result Update" table give the same numbers.

| Claim (id) | Paper | Reproduced mean ± std | Median | Min–max | n | Median dev. | Tolerance (median) | Pass |
|---|---|---|---|---|---|---|---|---|
| `etth1_96_mse`  | 0.372 | 0.37208 ± 0.00006 | 0.37209 | 0.37197–0.37216 | 8 | +0.02% | rel 1% | yes |
| `etth1_720_mse` | 0.424 | 0.42444 ± 0.00012 | 0.42438 | 0.42429–0.42461 | 8 | +0.09% | rel 1% | yes |
| `etth2_96_mse`  | 0.271 | 0.27102 ± 0.00010 | 0.27098 | 0.27092–0.27125 | 8 | −0.01% | rel 1% | yes |
| `ettm1_96_mse`  | 0.303 | 0.30294 ± 0.00015 | 0.30294 | 0.30276–0.30315 | 5 | −0.02% | rel 1% | yes |

**Verdict: full reproduction, essentially exact.** Every run lies within 0.15% of the paper value. The seed std (0.6–1.5e-4) matches the paper's "most STD < 5e-4". No claim needs a discrepancy entry, so there is no `DISCREPANCY.md`.

**Our CPU runs match the official GPU logs.** The repo ships the authors' training logs for every claim run (`logs/fixFITS/<data>_abl/`, five seeds each). Their 5-seed means are 0.37207 / 0.42457 / 0.27109 / 0.30294, printed in Table 1 as 0.372 / 0.424 / 0.271 / 0.303. The table seems to truncate rather than round: 15 of the 16 ETT cells equal the truncated mean, ETTh1-720 included. ETTm1-96 is the exception. Our runs match them seed by seed to 1e-6 whenever the official best epoch is ≤ 50. The rest differ by at most 4e-4. The reason is a hidden setting: the Namespace printed in every official log shows `train_epochs=100`, but the released `run_longExp_F.py` defaults to 50 and the scripts do not pass it. With `--train_epochs 100` our runs match those logs too (`results/official_vs_repro.csv`):

| Claim, seed | Official log (GPU) | Official epochs / best epoch | Ours, released code (50 ep.) | Ours, `--train_epochs 100` |
|---|---|---|---|---|
| ETTh1-96, 514  | 0.3721308 | 63 / 43 | 0.3721309 | — |
| ETTh1-96, 1919 | 0.3720629 | 84 / 64 | 0.3720300 | **0.3720630** |
| ETTh2-96, 514  | 0.2709610 | 100/87 + 66/46 | 0.2709761 | **0.2709610** |
| ETTh2-96, 1919 | 0.2710795 | 100/98 + 49/29 | 0.2709787 | **0.2710795** |
| ETTh2-96, 810  | 0.2713997 | 100/99 + 37/17 | 0.2709868 | **0.2713996** |
| ETTm1-96, 1919 | 0.3028378 | 46 / 26 | 0.3028378 | — |

The 50-epoch cap changes the claims by at most 0.1%, sometimes in the favourable direction, so the faithful runs use the released default.

Raw numbers: `results/fits_runs.csv`, one row per run (mse, mae, drop_last variant, test windows, epochs run, wall time). Diagnostics: `results/fits_diagnostics.csv`. Summary: `results/summary.txt` (`python3 manual/summarize.py`). Logs: `results/logs/<claim>_s<seed>.log`.

## Tolerance argument

The rubric uses the **median** over at least 3 seeds with **rel 1%** for every claim. Faithful runs are almost deterministic, so the tolerance is chosen to catch wrong setups rather than to absorb seed noise:

- **Seed noise.** Every C(8,3) and C(5,3) three-seed subset passes. The largest median deviation is 0.09% and the largest single-run deviation is 0.15%, a margin of about 7×.
- **Paper precision.** The three printed decimals plus STD < 5e-4 amount to about 0.1–0.3%. Because the values look truncated, the true mean can sit up to 0.001 above the printed value; this is why ETTh1-720 is +0.09%.
- **Platform numerics.** CPU vs GPU agree to 1e-6, so they do not matter.

Wrong setups and whether the tolerance catches them:

| Wrong setup | Source | Result | Caught at rel 1%? |
|---|---|---|---|
| `--batch_size 128` (struck-out README note; effective 256), ETTh1-720 | ours, seed 514 | 0.4524 (+6.7%) | yes |
| Same, ETTh1-96 | ours, seed 514 | 0.3727 (+0.2%) | no |
| Paper-era test loader `drop_last=True`, ETTh1-720 | ours, 8 seeds (`droplast_mse`) | 0.4160 (−1.9%) | yes |
| Same, ETTh1-96 / ETTh2-96 / ETTm1-96 | ours | −0.8% / −0.3% / +0.2% | no |
| Paper's stated protocol (validation selection) → ETTh2-96 look-back 180, H6, mode 2 | ours, 3 seeds | 0.2855 (+5.4%) | yes |
| Look-back 720 (grid scripts) for ETTh1-96 / ETTh1-720 / ETTm1-96 | official seed-114 logs | +1.9% / +1.5% / +2.0% | yes |
| Look-back 90 | official logs | +4% (ETTh1-96) to +20% (ETTm1-96) | yes |
| Default `H_order 2`, ETTh1-96 at look-back 360 | official log | 0.3965 (+6.6%) | yes |
| Too few epochs, ETTh1-720 (per-epoch test loss) | ours, seed 514 | ≈0.470 after 10 epochs, ≈0.432 after 20 | yes / yes |
| `train_mode 1` instead of 2 on ETTh2-96 | official log | 0.2713 (+0.1%) | no (acceptable) |
| `H_order 5` on ETTh1-96 | official log | 0.3746 (+0.7%) | no (acceptable) |
| 50-epoch cap (released) vs 100 epochs (official logs) | ours | ≤ 0.1% | no (both legitimate) |

A rel 2% tolerance would let the drop_last and two of the look-back-720 cases through, while 1% costs nothing for faithful runs.

Limitation: `etth1_96_mse` alone detects almost nothing (even batch 256 passes). `etth1_720_mse` and `etth2_96_mse` carry most of the discrimination, and `ettm1_96_mse` catches the wrong look-back.

## Steps and fixes

The upstream clone `repos/FITS` (full history, 61 commits) is untouched. The patched copy is `manual/FITS/` (code only: no `.git`, `logs/`, `AD/` or notebooks), with `dataset -> ../../data` as a symlink. The diff is `manual/fits_cpu_modern.patch`; it applies cleanly to upstream with `git apply`. After the runs, the regenerable outputs of the patched copy (`checkpoints/`, and `results/` with about 400 MB of prediction `.npy` files) were deleted; `result.txt` and `test_results/` were kept.

1. **Data.** ETTh1/ETTh2/ETTm1 CSVs are copied from `benchmark/dlinear/data/`, i.e. the official ETDataset `ETT-small` files. The FITS README names no data source, and the scripts just read `./dataset/<name>.csv`. The DLinear case showed these files are byte-identical to the Autoformer Google Drive copy. Files: 17,421 / 17,421 / 69,681 lines (incl. header), with sha256 values:
   - ETTh1 `f18de3ad269cef59bb07b5438d79bb3042d3be49bdeecf01c1cd6d29695ee066`
   - ETTh2 `a3dc2c597b9218c7ce1cd55eb77b283fd459a1d09d753063f944967dd6b9218b`
   - ETTm1 `6ce1759b1a18e3328421d5d75fadcb316c449fcd7cec32820c8dafda71986c9e`

   The split sizes in the logs (train 8185 / val 2785 / test 2785 for ETTh1-96) equal the official logs.
2. **`ModuleNotFoundError: No module named 'einops'`.** `exp_main_F.py` imports every model, and `models/Film.py` needs einops. `thop` is needed for the FLOP count printed before training. Both are installed; no code change was needed.
3. **`AttributeError: np.Inf was removed in the NumPy 2.0 release`** (`utils/tools.py`, EarlyStopping) → `np.inf` (`results/logs/fail_unpatched_smoke.log`).
4. **macOS hang with the default `--num_workers 10`.** The DataLoader workers use the spawn start method, and `run_longExp_F.py` has no `__main__` guard. Each worker re-imports the script and raises the "bootstrapping phase" `RuntimeError`, and the run hangs (`results/logs/fail_num_workers10_macos_spawn.log`). Fix: pass `--num_workers 0`. This does not change results: the official logs are still reproduced to 1e-6.
5. **Crash after the metric.** `test()` ends with `np.save(folder_path + 'x.npy', inputx)`. `inputx` is a ragged list of batches, because since the drop_last fix the last test batch is partial. NumPy ≥ 1.24, including the repo's pinned 1.26.4, raises `ValueError: ... inhomogeneous shape`. The `mse:` line and `result.txt` are already written at that point, but the process exits with status 1. Fixed with `np.concatenate(inputx, axis=0)`.
6. **Threads.** `torch.set_num_threads(TORCH_NUM_THREADS, default 4)` was added. The seed is already a CLI flag (`--seed`, default 2021), so no seed patch is needed.
7. **Extra report lines, not a fix.** `test()` also prints `test_windows:N` and `droplast_mse:..., droplast_mae:..., droplast_windows:M`. The `droplast_` values are computed on the first ⌊N/bs⌋·bs windows. This equals the pre-fix `drop_last=True` behaviour, because the test loader is not shuffled. The claims use the upstream `mse:` line.
8. **GPU/MPS.** No change needed: `use_gpu` is forced off without CUDA, and MPS is never used. Note that `--use_gpu False` would be parsed as True. Each run uses its own `--checkpoints ./checkpoints/<claim>_s<seed>/`, because the default checkpoint path is keyed by a setting string without the seed.

Environment:

```bash
uv venv --python 3.11 envs/fits
VIRTUAL_ENV=envs/fits uv pip install torch numpy pandas scikit-learn matplotlib thop einops
```

Commands (from `benchmark/fits/`). `manual/run_seeds.sh` runs the seeds sequentially, writes one log per seed and appends to the CSV. `manual/run_all_claims.sh` runs all four claims, and `manual/run_diagnostics.sh` runs the diagnostics:

```bash
manual/run_seeds.sh etth1_96_mse  ETTh1 360 96  6  1 24 514 1919 810 0 114 2021 1 2
manual/run_seeds.sh etth1_720_mse ETTh1 360 720 6  1 24 514 1919 810 0 114 2021 1 2
manual/run_seeds.sh etth2_96_mse  ETTh2 720 96  6  2 24 514 1919 810 0 114 2021 1 2
manual/run_seeds.sh ettm1_96_mse  ETTm1 360 96  14 1 96 514 1919 810 0 114
python3 manual/summarize.py; python3 manual/compare_official.py
# single run by hand (inside manual/FITS), = scripts/FITS/etth1_best.sh first command + --num_workers 0:
OMP_NUM_THREADS=4 ../../../../envs/fits/bin/python -u run_longExp_F.py --is_training 1 --root_path ./dataset/ \
  --data_path ETTh1.csv --model_id ETTh1_360_96 --model FITS --data ETTh1 --features M --seq_len 360 \
  --pred_len 96 --enc_in 7 --des Exp --train_mode 1 --H_order 6 --gpu 0 --seed 514 --patience 20 \
  --itr 1 --batch_size 64 --learning_rate 0.0005 --num_workers 0
```

## Metric parsing

The final metric line is printed once per run by `Exp_Main.test()`, for example `mse:0.3721308708190918, mae:0.39454764127731323, rse:0.579..., corr:[...]`. Parse it with:

```
(?m)^mse:([0-9.eE+-]+), mae:
```

Use the value as-is (scale 1). We checked this regex against all 38 run logs: exactly one match per log, equal to the CSV. It also matches the official logs. Avoid these alternatives:

- **Unanchored `mse:([0-9.]+)`.** Its last match is our extra `droplast_mse:` line.
- **Per-epoch `Test Loss:` lines.** They are an unweighted mean of per-batch losses (e.g. 0.37309 at the best epoch vs the reported 0.37213 for seed 514).

The case's `evidence_pattern` also requires that training actually ran: `(?s)Epoch: 1, Steps: \d+ \| Train Loss.*\nmse:[0-9.]+, mae:`. None of the three `fail_*` logs matches it.

## Side finding: the configurations were selected on the test set

This finding does not affect the verdict, because the `_best` scripts reproduce the claims. It does matter for an agent that follows the paper text instead of the scripts.

The paper (Sec. 4.2) says: "We conduct grid search on the look-back window of 90, 180, 360, 720 and cutoff frequency ... We choose the hyper-parameter based on the performance of the validation set." The official grid logs (seed 114, look-back 90/180/360/720 × `H_order` 2–6 (ETTm1: 4–14) × `train_mode` 1/2, 40–48 runs per cell) show something else. In all four claim cells, the `_best` configuration is the one with the lowest **test** MSE. The configuration with the lowest **validation** loss is a different one in every cell. The validation targets are the same windows for every look-back, so the validation losses are comparable.

| Cell | `_best` config (test arg-min) | Test MSE | Validation arg-min | Its test MSE (seed 114) |
|---|---|---|---|---|
| ETTh1-96  | 360, H6, mode 1 | 0.3721 | 360, H6, mode 2 | 0.3727 (+0.2%) |
| ETTh1-720 | 360, H6, mode 1 | 0.4247 | 360, H6, mode 2 | 0.4260 (+0.5%) |
| ETTh2-96  | 720, H6, mode 2 | 0.2710 | **180**, H6, mode 2 | **0.2854 (+5.3%)**; ours 3 seeds 0.2855 |
| ETTm1-96  | 360, H14, mode 1 | 0.3032 | 360, H14, mode 2 | 0.3034 (+0.1%) |

The paper's Table 4 (ETTh2 grid) lists the test MSE of exactly these seed-114 runs: for example, the 720/6th-harmonic "F" cell is 0.271312 and the "B+F" cell is 0.271028, equal to the `train_mode` 1/2 logs. The best cell is highlighted there. The FITS README's own updates include an "information leakage" paragraph about the anomaly-detection baselines, and this selection procedure has the same issue. We report it as a paper-vs-code observation. It is not a reproduction failure.

## Traps an agent could fall into

**Configuration**

- **Wrong code version.** The commits matching the v3 date (`41fe48b`/`1f552f8`, 2024-01-05, which add the logs and the `_best` scripts) cannot run FITS. Their `exp_main_F.py` dispatches on `'Linear' in args.model`, so FITS falls through to the Transformer call `self.model(batch_x, batch_x_mark, dec_inp, batch_y_mark, batch_y)`, which raises `TypeError: Model.forward() takes 2 positional arguments but 6 were given` (verified: `results/logs/fail_commit_1f552f8_dispatch.log`). This was fixed in `3583ec5` (2024-01-09). The authors evidently ran a local version that differed from the commit, and it also used `train_epochs=100`. Use HEAD.
- **Wrong scripts.** `scripts/FITS/etth1.sh` and the other scripts without `_best` are grid scripts. For example, ETTh1 loops look-back 720 with H_order 2–6 and seed 114 only; look-back 720 gives +1.9% on ETTh1-96. The `_fin` scripts in the struck-out README note no longer exist: they were renamed in `1f552f8`.
- **Batch size doubling.** `run_longExp_F.py` multiplies `--batch_size` by 2 when no augmentation is used. Passing the README's "128" gives 256, and ETTh1-720 becomes 0.452 (+6.7%).
- **ETTm1 needs `--base_T 96`.** `cut_freq` is derived from `base_T`. With the default 24, H_order 14 at look-back 360 gives cut_freq 234, more than the 181 rFFT bins, and the forward pass crashes (`mat1 and mat2 shapes cannot be multiplied`).
- **ETTh2-96 uses `train_mode 2`** (two training phases), while the other claims use 1. Using 1 costs only +0.1%.
- **Hidden epoch count.** The official logs used `train_epochs=100`; the released default is 50. The effect is ≤ 0.1%, and `--patience 20` must be passed (the default is 3).
- **Following the paper's validation-selection text** instead of the `_best` scripts gives ETTh2-96 = 0.2855 (+5.4%). See the side finding above.

**Paper versions and reading**

- **Paper versions.** arXiv v1/v2 (Jul/Sep 2023) Table 2 has the pre-fix FITS numbers 0.375 / 0.427 / 0.274 / 0.305. v1/v2 also says look-back 720 for every horizon, which no longer holds. v3/ICLR Appendix Table 8 (comparison with Transformers) still lists 0.368 / 0.425 / 0.255 / 0.305. The targets are v3/ICLR Table 1.
- **"10k parameters".** The claim configs have 5.6k–43.7k parameters (Table 5 of the paper agrees: 14,338 for ETTh1 360/H6/96). A model with ~10k parameters is not a check of correctness.

**Evaluation and runtime**

- **drop_last.** Table 1 uses the fixed test loader (all windows). The pre-fix loader would give −0.8% / −1.9% / −0.3% / +0.2%, and ETTh1-720 fails the tolerance.
- **Process exit status.** With NumPy ≥ 1.24, the unpatched `test()` crashes after printing the metric (ragged `np.save`). An executor that discards non-zero exits would lose valid results.
- **Concurrent runs** of the same setting overwrite `checkpoints/<setting>/checkpoint.pth`, because the setting string has no seed. Run seeds sequentially or pass `--checkpoints` per seed.

## Runtimes

Wall-clock on the M4 CPU with 4 threads, while two other jobs ran in parallel:

| Work | Runs | Wall time per run | Total |
|---|---|---|---|
| ETTh1-96 (63 steps/epoch, 50 epochs) | 8 | 36–43 s | 313 s |
| ETTh1-720 | 8 | 46–58 s | 410 s |
| ETTh2-96 (two phases, ≤ 2 × 50 epochs) | 8 | 70–91 s | 632 s |
| ETTm1-96 (266 steps/epoch) | 5 | 84–110 s | 475 s |
| Diagnostics (epochs 100, validation-selected config, batch 256) | 9 | 36–150 s | 678 s |
| Smoke and failure runs (incl. the 2024-01-05 commit) | 4 | — | ≈ 100 s |
| **Whole case** | **42** | — | **≈ 43 min** |

The model itself is tiny: one complex linear layer, about 0.4 s of training per ETTh1 epoch. The time goes to the Python data pipeline and to the full validation and test passes after every epoch (the code evaluates the test set each epoch for logging). A minimal 3-seed reproduction of the four claims takes about 13 min of compute.

## Human effort (baseline for agent comparison)

The first correct number came at 23:17, about 9 min after starting (23:08). It came from the fourth run attempt: the first failed on the missing `einops`, the second on `np.Inf`, the third hung on worker spawn with the default `--num_workers`, and the fourth succeeded. That run already matched the official log for seed 514 to 1e-7.

The whole session took about 1 h of wall-clock (23:08–00:10), including:

- reading the scripts, the batch-doubling and `cut_freq` logic, and the git history around the bug fix (`6ebc362`, `41fe48b`, `1f552f8`);
- comparing arXiv v1/v2/v3 and the ICLR proceedings PDF;
- parsing all 1,211 official logs;
- 42 runs;
- the write-up.
