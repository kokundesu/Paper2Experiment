# Learning to Optimize (DNN ≈ WMMSE): manual reproduction (case 2)

Date: 2026-10-01 · Machine: Apple M4, 16 GB, CPU only · Python 3.11, TF 2.21 (`tensorflow.compat.v1`), NumPy 2.4, uv venv `envs/l2o`

Paper: Sun et al., "Learning to Optimize: Training Deep Neural Networks for Interference Management", IEEE TSP 2018, arXiv 1705.09412 (PDF in `paper/`, arXiv v-dated 27 Oct 2017). Code: `Haoran-S/TSP-DNN` @ `674df88` (`Haoran-S/SPAWC2017` redirects here).

## Result

Ground truth is Table I of the paper ("Sum-Rate and Computational Performance for Gaussian IC", 10,000 test samples):

| K | DNN sum-rate | WMMSE sum-rate | DNN/WMMSE | DNN CPU (s) | WMMSE Python CPU (s) | WMMSE C CPU (s) |
|---|---|---|---|---|---|---|
| 10 | 2.770 | 2.817 | 98.33 % | 0.047 | 17.98 | 0.355 |
| 20 | 3.363 | 3.654 | 92.04 % | 0.093 | 59.41 | 1.937 |
| 30 | 3.498 | 4.150 | 84.29 % | 0.149 | 122.91 | 5.103 |

Reproduction: the DNN is trained from scratch with the official `df.train`, on 1e6 training samples, batch 1000, lr 0.001, RMSprop(0.9). The test set is 10,000 samples (seed 7), and outputs are binarised at 0.5. 3 seeds per K (TF init and minibatch order; training data fixed, seed 0). Mean ± std over the seeds:

| Claim id | Setting | Paper | Reproduced (from scratch) | Diff | Tolerance | OK |
|---|---|---|---|---|---|---|
| k10_dnn_pct | K=10, 200 epochs | 98.33 % | 97.88 ± 0.06 % | −0.45 | ±2.0 pp | yes |
| k20_dnn_pct | K=20, 200 epochs | 92.04 % | 90.61 ± 0.02 % | −1.43 | ±2.0 pp | yes (near the edge) |
| k30_dnn_pct | K=30, 120 epochs | 84.29 % | 84.86 ± 0.13 % | +0.57 | ±2.0 pp | yes |
| k10_speedup_py | K=10, WMMSE-Python time / DNN time | 382.6× (17.98/0.047) | 446 ± 173× (645, 346, 345) | ×1.17 | factor 3 | yes |

Average sum-rates, DNN / WMMSE: K=10 2.780 / 2.840, K=20 3.291 / 3.633, K=30 3.516 / 4.143. The paper reports 2.770 / 2.817, 3.363 / 3.654 and 3.498 / 4.150. Baselines match the paper's qualitative picture. As % of WMMSE, max power gives 50.5 / 39.5 / 34.8 and random power gives 46.2 / 38.0 / 33.9.

**Verdict: full reproduction** (all 4 claims within tolerance). K=20 is the weakest: it sits 1.43 pp under the paper with 200 epochs. One extra seed-0 run with 300 epochs gave 90.93 % (`results/sensitivity_K20.csv`). So the gap shrinks slowly with more training, and the paper's unspecified LR-decay schedule probably accounts for the rest.

Reference point, the authors' shipped checkpoints (`DNNmodel/model_{10,20,30}.ckpt`, 200-80-80) evaluated with the same pipeline on test seeds 7/8/9, 10k samples each:
K=10 97.82 ± 0.09 %, K=20 92.66 ± 0.11 %, K=30 85.63 ± 0.03 %. The speed-up at K=10 is 315 ± 7×. Even the authors' own weights miss Table I by −0.5 / +0.6 / +1.3 pp, which is why the tolerance is 2 pp.

Raw numbers:
- `results/train_from_scratch.csv` (9 runs)
- `results/pretrained_checkpoints.csv` (9 evaluations)
- `results/sensitivity_K20.csv` (1 run)
- `results/logs/` (training curves)

Wall time per training run, including data generation and testing: K=10 7–12 min, K=20 10.5 min, K=30 10–17 min (the first K=30 run spent 5.7 min on data generation before the chunk-size fix).

## Steps and fixes

The official repo is already wrapped in `tensorflow.compat.v1` with `disable_v2_behavior()` (a 2021 community PR), so TF itself needed no fix. Fixes went into a copy (`manual/TSP-DNN/`), and the diff is in `manual/tsp_dnn_repro.patch` (`patch -p1` applies it to a clean clone).

Crashes on the modern stack:
1. `TypeError: only 0-dimensional arrays can be converted to Python scalars` in `perf_eval`, which passes `np.random.rand(K,1)` to `math.log2` under NumPy 2.x → fixed by changing it to `np.random.rand(K)`.
2. `OSError: 'seaborn-deep' is not a valid package style` (Matplotlib ≥ 3.6) → fixed with `'seaborn-v0_8-deep'`. `perf_eval` also gained `plot=False` and now returns its metrics.

After these two fixes, the unmodified `test.py` runs. It evaluates the shipped checkpoints on only 1,000 samples: 98.19 / 92.14 / 86.05 %.

There is no script for training the Table I models, so I wrote `repro.py`, a driver around the official `wf.*`/`df.*` functions. It adds a CLI, `tf.set_random_seed` and `np.random.seed`, a 10k-sample test, and a CSV row per run. Engineering fixes needed to fit the paper's 1e6-sample setup on a 16 GB CPU machine:

3. **Data generation is too slow.** The official per-sample Python WMMSE needs ~0.35 / 1.1 / 2.2 ms per sample, up to ~40 min for 1e6 samples at K=30. Fix: `generate_Gaussian_fast` and `WMMSE_sum_rate_batch` vectorise over samples. They use the same RNG stream, the same update and the same per-sample stopping rule. On 2,000 samples Y matches the loop version to 6e-14, and X is identical up to float32 rounding (see fix 4). It produces 1e6 samples in 15 s (K=10) to about 1.5 min (K=30). The test set still uses the official loop version, so the WMMSE CPU time is the paper's "Python" column.
4. **Memory.** At K=30, 1e6×900 float64 inputs take 7.2 GB, and `df.train` copies them. Fix: store X float32 and sample-major (the network is fed float32 anyway).
5. **Slow minibatch gather.** `df.train` indexes rows of a transposed, non-contiguous array, which made K=30 about 5× slower (22 ms vs 4.7 ms per step). Fix: `np.ascontiguousarray(..., dtype=float32)`. A smoke test gave the same results.
6. **Crash below 10 epochs.** `df.train` raises `ZeroDivisionError` when `training_epochs < 10`. Avoided by never using fewer than 10 epochs; no patch.

Commands, run inside `manual/TSP-DNN`:

```bash
export TF_CPP_MIN_LOG_LEVEL=2 MPLBACKEND=Agg
PY=../../../../envs/l2o/bin/python
# from scratch (claims), seeds 0 1 2
$PY -u repro.py --mode train --K 10 --seed 0 --num_train 1000000 --epochs 200 --out ../../scratch/train --csv ../../results/train_from_scratch.csv
$PY -u repro.py --mode train --K 20 --seed 0 --num_train 1000000 --epochs 200 --out ../../scratch/train --csv ../../results/train_from_scratch.csv
$PY -u repro.py --mode train --K 30 --seed 0 --num_train 1000000 --epochs 120 --out ../../scratch/train --csv ../../results/train_from_scratch.csv
# shipped checkpoints (reference)
$PY repro.py --mode pretrained --K 10 --test_seed 7 --out ../../scratch/pre --csv ../../results/pretrained_checkpoints.csv
```

Environment: `uv venv --python 3.11 envs/l2o && VIRTUAL_ENV=envs/l2o uv pip install tensorflow numpy scipy matplotlib`. This gave TF 2.21.0, Keras 3.15.1, NumPy 2.4.6, SciPy 1.17.1 and Matplotlib 3.11.2. PyYAML was added later only to validate the YAML files.

## Deviations from the paper

- **Architecture: 200-80-80 (code and checkpoints) instead of 200-200-200 (paper Sec. V-B).** I followed the code, because the released checkpoints use it too. A 200-200-200 run was planned but cancelled for time.
- **Epochs: 200 (K=10, 20) and 120 (K=30) at a constant lr of 0.001.** This keeps each run under 20 min. The paper gives no epoch count (code default 300). It also decays the LR "when the validation error does not decrease", which the code does not implement; its `LRdecay=1` option is lr/(epoch+1), so I left it off. Training data size, batch size, LR, optimizer, initialisation and test-set size all match the paper.
- **WMMSE stopping rule: the code's (100 iterations, Δobj ≤ 1e-3), not the paper's (500, 1e-5).** On 5k samples the paper's rule raises the WMMSE sum-rate by only 0.18 / 0.25 / 0.30 % (K=10/20/30), which would lower the ratios by about as much.
- **Fixed training data across seeds.** All seeds use training set seed 0 and test set seed 7 (as in `test.py`). The seed std therefore covers only init and minibatch noise.
- **CPU times.** Absolute times are lower than the paper's (M4 vs 2017 Haswell): DNN 0.010–0.016 s and WMMSE-Python 3.4–10.4 s per 10k samples at K=10. Python WMMSE time varied 3× between runs on the same idle machine, so the speed-up claim has a wide tolerance. The C-WMMSE columns were not reproduced (no C implementation in the repo).
- IMAC (Table II and later tables) not attempted. Its data needs the MATLAB generator in `IMAC_model/`.

## Traps for agents

- **Running `test.py` only evaluates the shipped checkpoints.** It gives numbers close to Table I (98.2 / 92.1 / 86.1 % on 1k samples), but it is not a reproduction of training. It also uses 1,000 test samples, not 10,000. With 1k samples, fixed TF overhead dominates the DNN time and the K=10 speed-up looks like about 50× instead of about 350×.
- **`demo.py` is a toy setup, not the paper's.** It uses 25k samples, batch 200 and 100 epochs.
- **Binarising the outputs is required (`binary=1`).** An undertrained K=30 net outputs everything below 0.5 and scores 0 %. This is correct behaviour, not a bug.
- **Naive full-scale runs can hit time limits and run out of memory.** Python data generation plus float64 storage will time out or go OOM at K=30 with 1e6 samples on a laptop. An agent that silently shrinks the data to fit the budget should state it; with 1e5 samples and 10 epochs, K=10 reaches only about 85 %.
- **Validation MSE plateaus early.** It sits at about 5 % (K=10) and 6.5 % (K=20/30), so an agent might stop training too early.

## Human effort (baseline for agent comparison)

- **Fixes:** 2 crash fixes plus 4 scale and performance fixes (the 4th was avoided rather than patched), and a ~70-line driver.
- **Runs:** about 30 in total (smoke and timing tests, 9 pretrained evaluations, 9 from-scratch runs, 1 sensitivity run).
- **Time:** about 2 h 25 min wall-clock, 16:40 to 19:05. About 1 h 50 min of that was CPU training and testing run serially; about 35 min was hands-on reading, patching and writing.
