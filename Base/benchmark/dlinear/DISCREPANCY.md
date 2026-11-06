# DLinear ETTh1 T=720: why the paper number does not reproduce

Date: 2026-10-04 · Same machine and environment as `MANUAL_REPRO.md` (Apple M4 CPU, 4 threads, Python 3.11, torch 2.14.1 CPU, uv venv `envs/dlinear`). 68 new runs, about 16 min of compute.

## Verdict

**Root cause: confirmed. Category: `paper_code_mismatch`.**

The DLinear numbers in Table 2 were produced by an **older version of the official code** than the one now on GitHub. That older version is the May-2022 code, upstream commit `721ab58`, from before the 2022-08-15 commit `7f7a25b` "Update scripts and models !!!". It differs from the current code in two ways:

- **Weight init.** The linear layers start with every weight set to 1/L. The current code uses PyTorch's default random init; the 1/L lines are still in the file but commented out, under the note "if you want to visualize the weights".
- **ETTh1 hyperparameters.** The old script uses batch 8 and the default learning rate 1e-4. The current script uses batch 32 and lr 0.005.

When the old code is run with seed 2021, which is the repo's hard-coded seed, it reproduces the paper **to all three printed decimals**. This holds for MSE and MAE at all four ETTh1 horizons, and also for ETTh2-96 and ETTm1-96: 12 of 12 cells match. At T=720 the old code gives **0.4719 / 0.4902**; the paper reports **0.472 / 0.490**.

The current code is less stable at T=720. Early stopping uses patience 3 on a noisy validation loss, and in this setup it often stops after 4-6 epochs. As a result, all 10 seeds land above the paper value (median 0.499, +5.8%).

## Question

Paper Table 2 reports DLinear on ETTh1, multivariate, T=720, MSE = 0.472. This value is the same in arXiv v1/v2 ("DLinear-S"), v3 and the AAAI 2023 version. Our faithful reproduction (`MANUAL_REPRO.md`) uses the official current code at commit `0c11366` with `scripts/EXP-LongForecasting/Linear/etth1.sh`. Over 10 seeds it gives 0.5167 ± 0.0485 (median 0.4993, best 0.4781). Every seed is above the paper value. The shorter horizons do reproduce (T=96 median 0.374, T=336 median 0.447). Why does T=720 not?

## Hypotheses and how each was tested

| # | Hypothesis | Test | Outcome |
|---|---|---|---|
| H1 | Official training logs show a different command or setting | Searched the full upstream history (58 commits) for `logs/`, `result*.txt`, CSVs | **No logs were ever committed.** `.gitignore` excludes `logs/` since 2023-02-13. The scripts' log paths (`logs/LongForecasting/...`) never existed in the repo. This evidence is not available. |
| H2 | The paper's numbers come from an older code version (paper ↔ code mismatch) | Ran upstream `721ab58` (last commit before the Aug-2022 update) with its own scripts | **Confirmed.** Seed 2021 matches 12/12 cells exactly (table below). |
| H3 | Hyperparameters at T=720 differ from what the paper states | Read paper v1/v2/v3/AAAI and the script history | The paper never states lr or batch size: "For more hyper-parameters ... please refer to our code". The ETTh1 script changed from batch 8 / lr 1e-4 to batch 32 / lr 0.005 in `7f7a25b`. Kernel size 25, shared layers and the other defaults did not change. |
| H4 | Early stopping is too aggressive at T=720 | Current config with `--patience 10` (10 and 30 max epochs) | **Contributing factor.** It removes the bad tail and lowers the median from 0.499 to 0.480. It does not explain the exact value. |
| H5 | Data version (ETDataset vs the Autoformer Google Drive copy) | Downloaded the Drive `ETT-small/ETTh1.csv` with gdown | **Ruled out.** The two files are byte-identical (sha256 `f18de3ad…ee066`, 17,421 lines). The split borders are unchanged in `data_loader.py` since the first upload. |
| H6 | Paper version: v1/v2/v3/AAAI report different T=720 values | Extracted Table 2 / Table 7 from all four PDFs | **Ruled out.** 0.472 / 0.490 appears in all of them. v3/AAAI copied every DLinear cell from v1 "DLinear-S" except ILI (2.108 → 2.215). |
| H7 | drop_last on the test loader | Already measured in `MANUAL_REPRO.md` | **Ruled out.** Effect ≤ 0.0013. |
| H8 | Randomness: the paper got a lucky single run | Compared the seed spread under both configs | **Ruled out as the main cause.** Under the paper-era config, 0.472 is a typical value (10 seeds 0.471-0.484, std 0.004). Under the current config, no seed out of 10 reaches it. |
| H9 | CPU vs GPU numerics | Not tested (no GPU; MPS not tried) | Not needed: the CPU run already matches the GPU-era paper numbers to 3 decimals. |

## Experiments

All runs are DLinear, ETTh1, `--features M`, `seq_len 336`, at most 10 epochs, patience 3 and `lradj type1` unless a row says otherwise. Every value is test MSE on the z-scored test split. The table gives n seeds (2021 and 0..n-2), and the median deviation is measured against the paper's value for that horizon.

| Experiment (CSV `experiment`) | Code | Init | bs / lr | T | n | Median | Dev. | Min–max | Std | Seed 2021 |
|---|---|---|---|---|---|---|---|---|---|---|
| `baseline_current_cfg` (= MANUAL_REPRO runs) | 0c11366 | random | 32 / 0.005 | 720 | 10 | 0.4993 | +5.8% | 0.478–0.615 | 0.049 | 0.5042 |
| **`may2022_paper_cfg`** | **721ab58** | **1/L** | **8 / 1e-4** | **720** | 10 | **0.4754** | **+0.7%** | 0.471–0.484 | 0.004 | **0.4719** |
| `may2022_paper_cfg_T336` | 721ab58 | 1/L | 8 / 1e-4 | 336 | 4 | 0.4385 | −0.1% | 0.434–0.439 | 0.002 | 0.4385 |
| `may2022_paper_cfg_T192` | 721ab58 | 1/L | 8 / 1e-4 | 192 | 4 | 0.4066 | +0.4% | 0.406–0.410 | 0.002 | 0.4055 |
| `may2022_paper_cfg_T96` | 721ab58 | 1/L | 8 / 1e-4 | 96 | 4 | 0.3712 | −1.0% | 0.371–0.375 | 0.002 | 0.3748 |
| `xcheck_ETTh2_96_may2022_cfg` | 721ab58 | 1/L | 32 / 0.05 | 96 (ETTh2) | 1 | — | — | — | — | 0.2889 |
| `xcheck_ETTm1_96_may2022_cfg` | 721ab58 | 1/L | 8 / 1e-4 | 96 (ETTm1) | 1 | — | — | — | — | 0.2994 |
| `ablate_current_code_old_hparams` | 0c11366 | random | 8 / 1e-4 | 720 | 10 | 0.4897 | +3.8% | 0.483–0.509 | 0.009 | 0.5014 |
| `current_code_init1L_new_hparams` | 0c11366 + 1/L | 1/L | 32 / 0.005 | 720 | 5 | 0.4979 | +5.5% | 0.479–0.618 | 0.058 | 0.5038 |
| `current_code_init1L_old_hparams` | 0c11366 + 1/L | 1/L | 8 / 1e-4 | 720 | 10 | 0.4769 | +1.0% | 0.470–0.491 | 0.007 | 0.4869 |
| `ablate_may2022_code_new_hparams` | 721ab58 | 1/L | 32 / 0.005 | 720 | 5 | 0.4793 | +1.5% | 0.474–0.526 | 0.022 | 0.4793 |
| `current_cfg_patience10_ep10` | 0c11366 | random | 32 / 0.005, patience 10 | 720 | 4¹ | 0.4750 | +0.6% | 0.472–0.480 | 0.004 | 0.4717 |
| `current_cfg_patience10_ep30` | 0c11366 | random | 32 / 0.005, patience 10, 30 ep. | 720 | 10 | 0.4796 | +1.6% | 0.472–0.501 | 0.010 | 0.4716 |

¹ Seeds 2021, 0, 5 and 6 only. These are the four seeds that early-stopped at ≤ 6 epochs in the baseline; the other seeds already ran 7-10 epochs, so for them patience 10 with a 10-epoch cap changes little. The row is therefore biased toward seeds that benefit from the change.

**Exact match of the paper-era code, seed 2021, against the paper (MSE / MAE):**

| Cell | Paper | 721ab58, seed 2021 |
|---|---|---|
| ETTh1-96 | 0.375 / 0.399 | 0.3748 / 0.3995 |
| ETTh1-192 | 0.405 / 0.416 | 0.4055 / 0.4159 |
| ETTh1-336 | 0.439 / 0.443 | 0.4385 / 0.4427 |
| **ETTh1-720** | **0.472 / 0.490** | **0.4719 / 0.4902** |
| ETTh2-96 | 0.289 / 0.353 | 0.2889 / 0.3532 |
| ETTm1-96 | 0.299 / 0.343 | 0.2994 / 0.3433 |

Raw data: `results/discrepancy_etth1_720.csv`, one row per run (MSE, MAE, drop_last MSE, epochs run, best epoch, best validation loss, wall time). Per-group statistics: `results/discrepancy_etth1_720_summary.txt` (`python3 discrepancy/summarize.py`). Logs: `results/logs/discrepancy_<experiment>_s<seed>.log`. The baseline logs are the existing `results/logs/etth1_720_mse_s<seed>.log`.

## Interpretation

**Where the exact number comes from.** The paper-era code reproduces 12 printed cells to the last decimal with the repo's default seed. This is not a coincidence that tuning could produce. It identifies the code version and configuration behind Table 2. The document trail agrees:

- The v3 and AAAI Table 2 "DLinear*" column copies arXiv v1's "DLinear-S" column (May 2022) cell for cell, except ILI.
- The README entry of 2022-08-25 says: "We update some scripts of LTSF-Linear ... Some results of DLinear are slightly different now."
- v1/v2 Appendix A.2 says DLinear's linear weights are initialised to 1/L. v3 moves that sentence into the weight-visualisation section ("To obtain a smooth weight with a clear pattern in visualization ..."). The current `models/DLinear.py` keeps the init lines commented out, with the note "Use this two lines if you want to visualize the weights".

A reader of the current paper and code would therefore conclude that random init plus the current script is the method, but the table was not produced that way.

**Why only T=720 shows the gap.** The ablations separate the two factors:

- With the current hyperparameters (lr 0.005), the init makes no difference: 1/L init gives median 0.498 vs 0.499.
- With the old hyperparameters (lr 1e-4, batch 8), 1/L init matters: median 0.477 vs 0.490 with random init.
- With both old settings, the result is stable and on target: std 0.004-0.007 vs 0.049.

Under the current config the failure mode is early stopping. Seed 0 is an example. Its validation loss is lowest at epoch 2, where the model is still far from converged (train loss 0.574, test 0.616), and patience 3 then stops the run at epoch 5. With patience 10 the same seed reaches 0.480. At T=720 the validation loss is noisy, and the 720-step output has many parameters starting from random. The combination makes early stopping pick under-trained checkpoints in about half the seeds. At T=96 the problem is small (median −0.3%). At T=336 it shows up as a heavy tail (seed 6: 0.521), but the median survives.

**Why not "randomness".** Under the paper-era config, 0.472 sits in the middle of a narrow distribution (0.471-0.484). Under the current config, 0 of 10 seeds reach it. The gap is a systematic change of configuration, not a lucky draw. Longer patience alone closes most of the gap (median +1.6%), and so does the old config run on the current code (+1.0%). Only the old code itself reproduces the exact number.

## What an agent needs to notice to diagnose it

1. **The paper's numbers predate the code.** Compare paper versions (v1 May 2022 vs v3 Aug 2022). The DLinear column did not change, but the README says the scripts changed after v1 and that "some results of DLinear are slightly different now".
2. **Read the git history, not just HEAD.** `git log -- scripts/EXP-LongForecasting/` shows `7f7a25b` (2022-08-15). There, `scripts/EXP-LongForecasting/DLinear/etth1.sh` (batch 8, no lr flag, so lr 1e-4) became `Linear/etth1.sh` (batch 32, lr 0.005), and `models/DLinear.py` lost the 1/L init. Note that the benchmark's `repos/LTSF-Linear` is a depth-1 clone, so an agent has to fetch the full history itself.
3. **The 1/L init sentence in v1/v2 Appendix A.2** together with the commented-out lines in `models/DLinear.py`.
4. **Check the claim, ideally by experiment.** Run `721ab58` with its own script (seed 2021) and get 0.4719. Alternatively, uncomment the 1/L lines and use batch 8 / lr 1e-4 (median 0.477).
5. **Secondary.** Under the current config, T=720 runs that early-stop at epoch 4-6 are the bad ones; patience 10 reduces the median to 0.480.

Grading guidance:

| Diagnosis | Credit |
|---|---|
| Code/script version changed after the paper (init and/or ETTh1 lr/batch) | Correct |
| "The paper does not specify lr/batch/init; the released script differs" | Acceptable (`underspecified_paper`) |
| "Early stopping / training instability at T=720" with no version or config link | Partial: a real contributing mechanism, but not the source of the paper's value |
| "Random seed / single lucky run" | Incorrect: refuted by the seed spreads above |
| drop_last, dataset version, metric/normalisation, CPU vs GPU | Incorrect: each ruled out or negligible |

## Reproducing the experiments

```bash
# from benchmark/dlinear/
git clone https://github.com/cure-lab/LTSF-Linear.git /tmp/ltsf-full          # full history (repos/ is depth 1)
mkdir -p discrepancy/LTSF-Linear-721ab58
git -C /tmp/ltsf-full archive 721ab58 run_longExp.py exp models layers utils data_provider \
  | tar -x -C discrepancy/LTSF-Linear-721ab58
(cd discrepancy/LTSF-Linear-721ab58 && patch -p1 < ../may2022_cpu_modern.patch && ln -s ../../data dataset)
# current code + 1/L init: copy manual/LTSF-Linear/{run_longExp.py,exp,models,layers,utils,data_provider}
# to discrepancy/LTSF-Linear-0c11366-init1L, apply discrepancy/init1L.diff to models/DLinear.py
# (patch models/DLinear.py ../init1L.diff), and symlink dataset -> ../../data

discrepancy/run_variant.sh may2022_paper_cfg may2022 720 8 0.0001 2021 0 1 2 3 4 5 6 7 8
for T in 96 192 336; do discrepancy/run_variant.sh may2022_paper_cfg_T$T may2022 $T 8 0.0001 2021 0 1 2; done
discrepancy/run_variant.sh ablate_current_code_old_hparams current 720 8 0.0001 2021 0 1 2 3 4 5 6 7 8
discrepancy/run_variant.sh ablate_may2022_code_new_hparams may2022 720 32 0.005 2021 0 1 2 3
discrepancy/run_variant.sh current_code_init1L_old_hparams current_init1L 720 8 0.0001 2021 0 1 2 3 4 5 6 7 8
discrepancy/run_variant.sh current_code_init1L_new_hparams current_init1L 720 32 0.005 2021 0 1 2 3
EXTRA="--patience 10 --train_epochs 30" discrepancy/run_variant.sh current_cfg_patience10_ep30 current 720 32 0.005 2021 0 1 5 6 2 3 4 7 8
EXTRA="--patience 10" discrepancy/run_variant.sh current_cfg_patience10_ep10 current 720 32 0.005 2021 0 5 6
DATA=ETTh2 discrepancy/run_variant.sh xcheck_ETTh2_96_may2022_cfg may2022 96 32 0.05 2021
DATA=ETTm1 discrepancy/run_variant.sh xcheck_ETTm1_96_may2022_cfg may2022 96 8 0.0001 2021
python3 discrepancy/summarize.py
```

`may2022_cpu_modern.patch` makes three changes: the seed is read from the `SEED` env var, the thread count is set with `torch.set_num_threads`, and `np.Inf` becomes `np.inf`. Runs use `--num_workers 0` on macOS. The 721ab58 test loader still has `drop_last=True`, as in the paper era, so its `mse:` line is the paper-era metric. Each run of the old config takes 12-20 s; ETTm1 takes 26 s.

## Proposal (not applied to case.yaml)

### (a) Candidate claim

```yaml
  - {id: etth1_720_mse, metric: test_mse, setting: "Table 2, DLinear, ETTh1, multivariate, horizon T=720", unit: "", value: 0.472, tolerance: {rel: 0.03}, evidence_pattern: "(?s)Epoch: 1, Steps: \\d+ \\| Train Loss.*\\nmse:[0-9.]+, mae:"}
```

Tolerance rationale. We took all C(10,3) = 120 three-seed subsets and computed how often their median falls within the tolerance:

| Population (10 seeds) | rel 2% | **rel 3%** | rel 5% | rel 10% |
|---|---|---|---|---|
| Faithful current scripts (`baseline_current_cfg`) | 0.07 | **0.18** | 0.33 | 0.82 |
| Paper-era code and config (`may2022_paper_cfg`) | 1.00 | **1.00** | 1.00 | 1.00 |
| Current scripts + patience 10 (`current_cfg_patience10_ep30`) | 0.67 | 0.82 | 0.93 | 1.00 |

At 3%, a faithful run of the current official scripts fails in 82% of 3-seed runs, which leaves a discrepancy to diagnose. The paper-era configuration always passes. An agent that only raises the patience (a deviation from the official scripts) passes 82% of the time. A 10% tolerance would hide the discrepancy.

### (b) Root cause entry

```yaml
discrepancies:
  - claim_id: etth1_720_mse
    category: paper_code_mismatch
    also_acceptable: [underspecified_paper]
    summary: "Table 2's DLinear numbers were produced by the pre-August-2022 version of the official code (linear weights initialised to 1/L, ETTh1 script with batch 8 and default lr 1e-4); the released code uses random init with batch 32 / lr 0.005, which at T=720 early-stops on a noisy validation loss and lands ~6% higher (median of 10 seeds 0.499 vs 0.472)."
    key_evidence:
      - "Upstream commit 721ab58 (before 7f7a25b, 2022-08-15 'Update scripts and models') with its own ETTh1 script reproduces T=720 exactly with seed 2021: MSE 0.4719 / MAE 0.4902 vs paper 0.472 / 0.490 (also T=96/192/336, ETTh2-96 and ETTm1-96 to 3 decimals)."
      - "7f7a25b changed the ETTh1 script from batch 8 / lr 1e-4 to batch 32 / lr 0.005 and commented out the 1/L weight init in models/DLinear.py; README: 'Some results of DLinear are slightly different now'."
      - "The DLinear column of Table 2 in v3/AAAI is copied from arXiv v1 (May 2022) 'DLinear-S'; v1/v2 Appendix A.2 states the 1/L init, v3 moves it to the visualisation section; the paper gives no lr/batch size ('refer to our code')."
      - "Current scripts: 10 seeds 0.478-0.615, median 0.499, all above 0.472; paper-era config: 10 seeds 0.471-0.484 (std 0.004), so it is not a lucky seed."
      - "Contributing mechanism: patience-3 early stopping at T=720 stops bad seeds after 4-6 epochs; patience 10 lowers the median to 0.480. Data (Autoformer Drive copy byte-identical) and drop_last (<=0.0013) ruled out."
    confirmed_by: "results/discrepancy_etth1_720.csv, DISCREPANCY.md"
    confidence: confirmed
```

### Recommendation

**Yes, add the claim, as a discrepancy-diagnosis claim.** Its root cause is confirmed by an exact reproduction rather than inferred, and the cause can be checked from public material: paper versions, README, git history and a 20-second run. That makes it a good test of diagnosis.

Three caveats:

1. **Grading weight.** With `rel: 0.03`, about 1 in 5 faithful 3-seed runs will pass by chance, which leaves nothing to diagnose. The rubric should treat this claim as diagnosis-graded and not count it toward "full/partial", or the case's overall pass rate will drop.
2. **Agent-facing task.** To include it, `task.yaml` would need a fifth claim. Doing that is outside this investigation's scope.
3. **Diagnosis depth.** A diagnosis that stops at "early stopping / instability" is a plausible partial answer. The grader should require the code-version or configuration link for full credit.

## Addendum 2026-10-05: the unused `Linear_Decoder` (raised by an agent's diagnosis)

The paper-era `models/DLinear.py` also builds a `Linear_Decoder` that `forward` never uses. Its initialisation consumes
PyTorch RNG draws, so for a fixed seed it changes the shuffled minibatch order. A system run (formal rerun, DLinear
multi r2) restored only this layer, saw the 3-seed median drop to 0.4805 and named it the cause.

10-seed check (current code and hyperparameters, seeds 2021 and 0-8, `discrepancy/run_variant.sh current_decoder ...`,
copy in `discrepancy/LTSF-Linear-0c11366-decoder/`):

| Variant | Median | Range | Seeds within 3% | P(3-seed median within 3%) |
|---|---|---|---|---|
| current code | 0.4993 | 0.478-0.615 | 3/10 | 0.18 |
| current + unused decoder | 0.4824 | 0.475-0.525 | 6/10 | 0.67 |
| paper-era code 721ab58 | 0.4754 | 0.471-0.484 | 10/10 | 1.00 |

The agent's seed-2021 value reproduces exactly (0.4804). The median shift has a one-sided permutation p = 0.028, but an
unused layer only re-maps which random stream each seed gets; over seeds the outcome distribution is the same, so the
shift is best read as sampling variation in a heavy-tailed, seed-sensitive setting (direction chosen after the fact).
Only the full paper-era code (smaller lr and batch) reproduces the paper reliably and with a narrow spread.

Grading consequence: the diagnosis has the right category and direction (the code version changed) but not the
mechanism; the automatic strict-attribution hit was adjudicated as partially correct. Lesson for the diagnosis rules:
in a setting whose seed spread is as large as the effect, a 3-seed diagnostic experiment can produce a convincing but
spurious mechanism.
