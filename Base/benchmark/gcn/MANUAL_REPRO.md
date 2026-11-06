# GCN — manual reproduction (case 1)

Date: 2026-10-01 · Machine: Apple M4, 16 GB, CPU only · Python 3.11 (uv venvs in `envs/`)

## Result

Official code `tkipf/gcn`, Planetoid public split, default hyperparameters (200 epochs, lr 0.01, hidden 16, dropout 0.5, weight decay 5e-4, early stopping window 10), 10 seeds (123, 0–8).

| Dataset  | Paper (Table 2) | Reproduced (mean ± std) | Diff  |
|----------|-----------------|-------------------------|-------|
| Cora     | 81.5            | 81.76 ± 0.60            | +0.26 |
| Citeseer | 70.3            | 71.15 ± 0.82            | +0.85 |
| Pubmed   | 79.0            | 79.08 ± 0.25            | +0.08 |

**Verdict: full reproduction** (all claims within 1.5 pp). Raw numbers: `results/official_tf_10seeds.csv`. Each run takes a few seconds on CPU.

## Steps and fixes

Fixes applied to a copy (`manual/gcn/`), diff in `manual/official_tf2_compat.patch`:

1. `ModuleNotFoundError: No module named 'gcn'` → run with `PYTHONPATH=..`.
2. `No module named 'scipy.sparse.linalg.eigen.arpack'` → `from scipy.sparse.linalg import eigsh`.
3. TF1 API on TF 2.21 → `import tensorflow.compat.v1 as tf; tf.disable_v2_behavior()` in every module.
4. Seed hard-coded → read `SEED` env var (only needed for multi-seed runs).

Command (inside `manual/gcn/gcn`):

```bash
SEED=0 PYTHONPATH=.. ../../../../../envs/tf/bin/python train.py --dataset cora
```

## Trap: pygcn is not a reproduction

`tkipf/pygcn` runs after the same PYTHONPATH fix and reports ~82.9% on Cora (5 seeds: 83.8, 83.0, 82.2, 82.9, 82.8). Its README says it is not intended to reproduce the paper: it builds the graph from raw `cora.content`/`cora.cites` and uses a different split (train = first 140 nodes, test = nodes 500–1499). The number looks close to 81.5 but is not comparable. An agent that picks this repo and reports "reproduced" should be scored as wrong-setup, which makes this a useful check for the Repo Agent and the Evaluator.

## Human effort (baseline for agent comparison)

About 4 fixes and 6 runs to the first correct number; about 15 min wall-clock, including reading the code.
