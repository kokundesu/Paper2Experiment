"""Summarise results/discrepancy_etth1_720.csv (+ the faithful runs in results/dlinear_runs.csv).

Usage (from benchmark/dlinear/): python3 discrepancy/summarize.py
Prints one row per experiment: n, mean, std, median, min, max, seed-2021 value, epochs run,
and the deviation of the median from the paper value for that horizon.
"""
import csv
import statistics as st
from collections import OrderedDict
from pathlib import Path

CASE = Path(__file__).resolve().parent.parent
PAPER = {96: 0.375, 192: 0.405, 336: 0.439, 720: 0.472}  # Table 2 DLinear ETTh1 MSE (v1 = v3 = AAAI)
PAPER_XCHECK = {"xcheck_ETTh2_96": 0.289, "xcheck_ETTm1_96": 0.299}  # Table 2, horizon 96

groups = OrderedDict()
for row in csv.DictReader(open(CASE / "results/dlinear_runs.csv")):
    if row["data"] == "ETTh1" and row["claim_id"] in ("etth1_96_mse", "etth1_336_mse"):  # T=720 baseline is in the discrepancy CSV
        key = ("faithful_current_cfg (dlinear_runs.csv, T=96/336)", int(row["pred_len"]))
        groups.setdefault(key, []).append((row["seed"], float(row["mse"]), row["epochs_run"]))
for row in csv.DictReader(open(CASE / "results/discrepancy_etth1_720.csv")):
    key = (row["experiment"], int(row["pred_len"]))
    groups.setdefault(key, []).append((row["seed"], float(row["mse"]), row["epochs_run"]))

print(f"{'experiment':58s} {'T':>4s} {'n':>2s} {'mean':>7s} {'std':>7s} {'median':>7s} {'min':>7s} {'max':>7s} {'s2021':>7s} {'paper':>6s} {'med.dev':>8s}  epochs")
for (name, T), runs in groups.items():
    v = [m for _, m, _ in runs]
    s2021 = next((m for s, m, _ in runs if s == "2021"), float("nan"))
    sd = st.stdev(v) if len(v) > 1 else 0.0
    med = st.median(v)
    ref = next((v for k, v in PAPER_XCHECK.items() if name.startswith(k)), PAPER[T])
    print(f"{name:58s} {T:4d} {len(v):2d} {st.mean(v):7.4f} {sd:7.4f} {med:7.4f} {min(v):7.4f} {max(v):7.4f} {s2021:7.4f} {ref:6.3f} {100*(med/ref-1):+7.1f}%  {','.join(e for *_, e in runs)}")
