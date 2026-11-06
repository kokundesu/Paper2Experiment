# SGC — manual reproduction

Date: 2026-10-04 · Machine: Apple M4, 16 GB, CPU only, 4 threads (`OMP_NUM_THREADS=MKL_NUM_THREADS=4`) · Python 3.11.16, torch 2.14.1 (CPU), NumPy 2.4.6, SciPy 1.17.1, networkx 3.6.1, scikit-learn 1.9.1, hyperopt 0.3.0 (uv venv `envs/sgc`)

## Result

Official code `Tiiiger/SGC` (commit 2c7a272, 2021-04-13), run **unmodified** with the README commands: SGC with K = 2 propagation steps of the augmented normalised adjacency (`AugNormAdj`), row-normalised features, full-batch Adam with lr 0.2, no dropout, and the hyperopt-tuned weight decay that ships in `SGC-tuning/<dataset>.txt` (`--tuned`). Cora and Pubmed train for 100 epochs and Citeseer for 150 (`--epochs 150`, README only). The metric is test accuracy on the 1000 Planetoid test nodes after the last epoch (no early stopping, no model selection). Ten seeds per claim: 42 (the `--seed` default) and 0-8.

Target values: Table 2, row "SGC" under "Our experiments", "Test accuracy (%) averaged over 10 runs": `SGC 81.0± 0.0 71.9± 0.1 78.9± 0.0`.

| Claim (id) | Paper | Reproduced mean ± std (10 seeds) | Min–max | Seed 42 | Dev. of mean | Tolerance | Pass |
|---|---|---|---|---|---|---|---|
| `cora_acc`     | 81.0 ± 0.0 | 81.02 ± 0.04 | 81.0–81.1 | 81.0 | +0.02 | abs 0.5 | yes |
| `citeseer_acc` | 71.9 ± 0.1 | 71.84 ± 0.07 | 71.7–71.9 | 71.9 | −0.06 | abs 0.5 | yes |
| `pubmed_acc`   | 78.9 ± 0.0 | 78.95 ± 0.05 | 78.9–79.0 | 78.9 | +0.05 | abs 0.5 | yes |

**Verdict: full reproduction, exact to the printed decimal.** The default seed 42 gives exactly 81.0 / 71.9 / 78.9, and the 10-seed standard deviations (0.04-0.07) match the paper's ± 0.0 / 0.1 / 0.0. The seed only changes the initial weights of a logistic regression on the fixed features S²X, so different seeds move at most one or two test nodes.

The runs are deterministic on CPU. Seed 42 gave the same accuracies in the first smoke run, in the 10-seed sweep and with `OMP_NUM_THREADS=1` (`results/logs/diag_*_threads1_s42.log`).

Raw numbers: `results/sgc_runs.csv`, one row per run (experiment, dataset, seed, epochs, tuned, extra flags, weight decay, validation and test accuracy, train time, wall time). Logs: `results/logs/<claim>_s<seed>.log` for the claims and `results/logs/diag_*` / `retune_*` for the diagnostics. Per-experiment statistics: `results/sgc_summary.txt` (`python3 manual/summarize.py`).

## Citeseer: 100 vs 150 epochs

This is the one place where the paper text and the official command differ. The paper says "we train SGC for 100 epochs using Adam with learning rate 0.2" for the citation networks. The README runs Citeseer with `--epochs 150` (already in the initial code release, 5f0e9e9, 2019-01-30). The paper covers this with a later sentence in the same paragraph: "On all datasets, we tune the number of epochs based on both convergence behavior and validation accuracy."

**150 epochs reproduces the table; 100 epochs does not.** Single-factor experiments, everything else as in the README command:

| Citeseer setup | Weight decay | Val. acc. | Test acc. (n) | Dev. |
|---|---|---|---|---|
| README: 150 epochs, `--tuned` | 2.35e-5 (shipped) | 72.8 | 71.84 ± 0.07 (10) | −0.06 |
| Paper text: 100 epochs, `--tuned` | 2.35e-5 (shipped) | 72.2 | **71.20 ± 0.00 (10)** | **−0.70** |
| 100 epochs, weight decay re-tuned with `tuning.py` at 100 epochs (6 hyperopt seeds) | 5.4e-5 – 7.8e-5 | 73.2 | 72.0–72.3 (seed 42) | +0.1 to +0.4 |
| 150 epochs, weight decay re-tuned at 150 epochs (3 hyperopt seeds) | 2.8e-5 – 3.7e-5 | 73.4–73.8 | 71.9–72.0 (seed 42) | 0.0 to +0.1 |

The 71.2 result is a mixed setup: a weight decay tuned for one epoch budget, trained for another. The shipped value 2.35e-5 lies near the values hyperopt finds at 150 epochs and well below those it finds at 100 epochs. That suggests the authors tuned Citeseer at 150 epochs. This is likely, not confirmed, because hyperopt is stochastic and the original tuning seed is unknown. Its validation accuracy is also higher at 150 epochs (72.8) than at 100 (72.2), which fits "tune the number of epochs on validation accuracy".

Following the paper text consistently, with 100 epochs and the weight decay re-tuned for it, also lands within 0.4 pp. The only setup that misses is the mixed one. Since the README command is part of the official release and reproduces the number exactly, this is a **trap, not a discrepancy**. No claim is `diagnostic_only` and `case.yaml` has no `discrepancies` entry.

The same switch on the other datasets: Cora at 150 epochs gives 81.4 (+0.4), Pubmed at 150 epochs gives 78.9 (±0.0).

## Tolerance argument

The rubric compares the **mean** over at least 3 seeds with an absolute tolerance of **0.5 pp** for every claim. One test node is 0.1 pp.

All C(10,3) = 120 three-seed subsets of the faithful runs have a mean within 0.17 pp of the paper, so a faithful run passes with certainty. 0.5 pp is about 7 standard deviations of the noisiest claim. It leaves room for platform numerics such as a GPU or another BLAS: a completely different initialisation moves the result by ≤ 0.2 pp, and a thread-count change moved it by 0.

The tolerance also rejects the plausible wrong setups:

| Setup (single factor changed) | Cora | Citeseer | Pubmed | Caught? |
|---|---|---|---|---|
| Faithful (README commands) | 81.02 | 71.84 | 78.95 | passes |
| Citeseer 100 epochs, shipped weight decay | — | 71.20 (−0.70) | — | yes |
| All at 150 epochs | 81.40 (+0.40) | (= faithful) | 78.90 (0.00) | no (harmless) |
| No `--tuned` (weight decay 5e-6, args.py default) | 80.60 (−0.40) | 69.50 (−2.40) | 77.83 (−1.07) | yes, by Citeseer and Pubmed |
| K = 1 (`--degree 1`) | 76.60 (−4.40) | 68.30 (−3.60) | 77.50 (−1.40) | yes |
| K = 3 (`--degree 3`) | 81.90 (+0.90) | 71.40 (−0.50) | 79.00 (+0.10) | yes, by Cora |
| Weight decay re-tuned with hyperopt (paper procedure) | 80.9–81.0 | 71.9–72.3 | 78.9 | passes (intended) |

These rows use 2-3 seeds each (10 for Citeseer at 100 epochs). The re-tuning row uses one seed per hyperopt result.

The weak spots are on Cora: a missing `--tuned` (−0.4) and 150 epochs (+0.4) still pass that claim. The missing `--tuned` is caught by the other two claims.

A 1.0 pp tolerance would accept Citeseer at 100 epochs (−0.7) and K = 3 on Cora (+0.9). With a seed spread this small, that would throw away the case's ability to detect them.

## Steps and fixes

**No fixes were needed.** `manual/SGC/` is a byte-identical copy of upstream; `diff -r -x .git repos/SGC manual/SGC` is empty. For that reason there is no `.patch` file. Things checked on the way:

1. **Do not install `requirements.txt` as pinned.** It pins `networkx==1.11` and `hyperopt==0.1.1`. Both install on Python 3.11, but `import networkx` then fails with `ImportError: cannot import name 'gcd' from 'fractions'` (removed in Python 3.9), and hyperopt 0.1.1 fails the same way because it imports networkx. Unpinned current versions (networkx 3.6.1, hyperopt 0.3.0) work with the code unchanged. `nx.adjacency_matrix` now returns a sparse array, but the code converts it with `sp.coo_matrix` before the row sums.
2. torch 2.14 prints a deprecation `UserWarning` for `torch.sparse.FloatTensor` in `utils.py`. It is harmless and was left in place.
3. Seeds: `--seed` already exists (default 42) and sets NumPy and torch seeds, so no SEED patch was needed.
4. CUDA is used only if available, so on a Mac it runs on CPU automatically. MPS is never used.
5. Repo history: the citation code path is unchanged since the 2019-01-30 release. The one later edit, `d2a66ec`, changes a default argument of `load_citation` that `citation.py` always overrides. The `ablation` branch holds the paper's ablation code and is not needed for Table 2.

Environment:

```bash
uv venv --python 3.11 envs/sgc
VIRTUAL_ENV=envs/sgc uv pip install torch numpy scipy networkx scikit-learn hyperopt   # hyperopt only for tuning.py
git clone https://github.com/Tiiiger/SGC.git benchmark/sgc/repos/SGC                    # full history, HEAD 2c7a272
```

Commands (from `benchmark/sgc/`). `manual/run_seeds.sh` runs seeds sequentially from `manual/SGC`, writes one log per seed and appends to the CSV:

```bash
manual/run_seeds.sh cora_acc     cora     100 42 0 1 2 3 4 5 6 7 8
manual/run_seeds.sh citeseer_acc citeseer 150 42 0 1 2 3 4 5 6 7 8
manual/run_seeds.sh pubmed_acc   pubmed   100 42 0 1 2 3 4 5 6 7 8
# diagnostics
manual/run_seeds.sh diag_citeseer_ep100 citeseer 100 42 0 1 2 3 4 5 6 7 8
TUNED=0 manual/run_seeds.sh diag_cora_untuned cora 100 42 0 1
EXTRA="--degree 3" manual/run_seeds.sh diag_cora_K3 cora 100 42 0
python3 manual/summarize.py > results/sgc_summary.txt
# single run by hand (must be inside the repo root: data/ and SGC-tuning/ are relative paths)
cd manual/SGC && OMP_NUM_THREADS=4 ../../../../envs/sgc/bin/python citation.py --dataset citeseer --tuned --epochs 150 --seed 0
```

Re-tuning (`retune_*` logs) ran `HYPEROPT_FMIN_SEED=<h> python tuning.py --dataset <d> --epochs <e>` in a scratch copy, because `tuning.py` overwrites `SGC-tuning/<dataset>.txt`. Each best value was then evaluated with `TUNED=0 EXTRA="--weight_decay <wd>"`.

## Metric parsing

`citation.py` prints one result line per run after training, e.g. `Validation Accuracy: 0.7280 Test Accuracy: 0.7190`, followed by `Pre-compute time: 0.0521s, train time: 0.0402s, total: 0.0923s`. Parse with

```
Test Accuracy: ([0-9.]+)
```

and **scale 100** (the value is a fraction). This regex was checked against all 82 runs in the CSV (plus the 3 thread-check logs), and its last match equals the CSV value in every case. The case's `evidence_pattern` requires the result line directly followed by the timing line, which `citation.py` prints only after the training loop has run:

```
Validation Accuracy: [0-9.]+ Test Accuracy: [0-9.]+\s*\nPre-compute time: [0-9.]+s, train time: [0-9.]+s
```

A dry run of `p2e.evaluator.evaluate` on seeds 0-2 of these logs gives `full`. Swapping in the Citeseer 100-epoch runs gives `partial`, and the untuned runs give `fail`.

## Traps an agent could fall into

**Setting**

- **Citeseer epochs.** The paper says 100 epochs, but the official command uses 150. 100 epochs with the shipped weight decay gives 71.2 (−0.7) on every seed. See the section above.
- **Forgetting `--tuned`.** The args.py default weight decay of 5e-6 is not the paper setting. It gives 80.6 / 69.5 / 77.8. The tuned values live in binary pickles named `.txt` (`SGC-tuning/cora.txt` etc.): cora 1.30e-5, citeseer 2.35e-5, pubmed 7.40e-5.
- **Re-tuning instead of using the shipped values.** Running `tuning.py` is a legitimate reading of the paper and lands within 0.4 pp, but it is random: hyperopt 0.3 is unseeded unless `HYPEROPT_FMIN_SEED` is set. It also overwrites the shipped pickle in place and runs a full `citation.py` training on import.
- **Degree K.** Table 2 uses K = 2 (`--degree 2`, the code default). The paper text never states K for Table 2; K = 2 is named only for other experiments (text classification, relation extraction). K = 1 loses 1.4-4.4 pp, and K = 3 gives Cora +0.9.
- **Re-implementations.** The README lists PyG, DGL, Spektral, StellarGraph and tf_geometric examples and warns that their hyperparameters and results differ. These are not the official code.

**Running and parsing**

- **Pinned requirements.** `pip install -r requirements.txt` gives networkx 1.11, which cannot be imported on Python ≥ 3.9 (`fractions.gcd`). Unpin it; do not patch the code.
- **Silent argument fallback.** `args.py` uses `parse_known_args`, so a misspelled flag (`--weight-decay`, `--K 3`) is ignored without an error. Passing the whole command as one quoted string, as an unsplit shell variable in zsh does, silently runs **Cora with untuned defaults**: val 79.2, test 80.7. This happened in our own first Citeseer attempt. Abbreviations are accepted (`--epoch 150` works).
- **Working directory.** `data/` and `SGC-tuning/` are opened with relative paths, so `citation.py` must run from the repo root.
- **Validation vs test accuracy.** Both are on the same line. The claim is the second number, `Test Accuracy`; the validation numbers (79.4 / 72.8 / 81.8) would fail Cora and Pubmed.
- **Units.** The log prints fractions (0.8100), and Table 2 is in %.
- **Model selection.** The code reports the test accuracy after the last epoch. There is no early stopping or best-validation checkpoint, and adding one changes the protocol.

## Runtimes

Every run takes 4-6 s wall-clock on the M4 CPU with 4 threads, with other jobs running in parallel. Training itself takes 0.02-0.04 s; the rest is Python/torch import and loading the pickled Planetoid data.

| Work | Runs | Wall time |
|---|---|---|
| 3 claims × 10 seeds | 30 | 137 s |
| Single-factor diagnostics (epochs, weight decay, K, threads) | 37 | ≈ 4 min |
| Hyperopt re-tuning (60 evals each, ≈ 9 s per tuning) + evaluation | 15 + 15 | ≈ 2.3 + 1.6 min |
| Whole case incl. 7 smoke runs | ≈ 104 | ≈ 11 min |

A minimal 3-seed reproduction of the three claims (9 runs) takes under a minute.

## Human effort (baseline for agent comparison)

The first number took **0 code fixes** and came from the first run, about 3 minutes after cloning; most of that was installing torch. Dependencies were installed unpinned from the start. Following `requirements.txt` literally would have cost one environment fix (networkx 1.11 import error). All three claims matched the paper exactly on the first correct invocation. The only stumble was the zsh word-splitting slip described under traps, which silently produced a Cora result. The session took about 20 min wall-clock (23:10-23:30), covering the paper read, code and history review, environment, 104 runs, and the write-up.
