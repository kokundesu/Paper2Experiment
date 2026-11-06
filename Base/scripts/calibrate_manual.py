"""Score the human (manual) reproductions with the same evaluator the workflows use.

If the evaluator is calibrated, every manual reproduction should come out as
the verdict its MANUAL_REPRO.md reports. Run: .venv/bin/python scripts/calibrate_manual.py
"""
from __future__ import annotations

import re
from pathlib import Path

from p2e.evaluator import evaluate
from p2e.runner import BENCHMARK
from p2e.schemas import Case, ClaimMeasurement, Metrics


def from_logs(case_dir: Path, claim_globs: dict[str, tuple[str, str]]) -> Metrics:
    """claim id -> (log glob under results/logs, regex with one group) ."""
    claims = []
    for cid, (pattern, regex) in claim_globs.items():
        values, evidence = [], []
        for log in sorted((case_dir / "results/logs").glob(pattern)):
            found = re.findall(regex, log.read_text(errors="replace"))
            if found:
                values.append(float(found[-1]))
                evidence.append(str(log.relative_to(case_dir)))
        claims.append(ClaimMeasurement(claim_id=cid, values=values, evidence=evidence))
    return Metrics(claims=claims)


def _pct(m: Metrics) -> Metrics:
    """Scripts that print accuracy as a fraction; claims are in %."""
    for c in m.claims:
        c.values = [v * 100 for v in c.values]
    return m


def gcn(case_dir: Path) -> Metrics:
    # Run logs regenerated 2026-10-05 from manual/gcn (same seeds 123, 0-8; identical to official_tf_10seeds.csv).
    return _pct(from_logs(case_dir, {f"{ds}_acc": (f"{ds}_acc_s*.log", r"Test set results:.*accuracy= ([0-9.]+)")
                                     for ds in ("cora", "citeseer", "pubmed")}))


CASES = {
    "gcn": gcn,
    "l2o_wmmse": lambda d: from_logs(d, {
        "k10_dnn_pct": ("K10_s*.log", r"'dnn_pct_of_wmmse': np\.float64\(([\d.]+)\)"),
        "k20_dnn_pct": ("K20_s*.log", r"'dnn_pct_of_wmmse': np\.float64\(([\d.]+)\)"),
        "k30_dnn_pct": ("K30_s*.log", r"'dnn_pct_of_wmmse': np\.float64\(([\d.]+)\)"),
        "k10_speedup_py": ("K10_s*.log", r"time speed up: ([\d.]+) X"),
    }),
    # diagnostic_only claims (dlinear etth1_720, kalmannet Table VI) are scored but do not enter the verdict
    "dlinear": lambda d: from_logs(d, {
        cid: (f"{cid}_s*.log", r"(?m)^mse:([0-9.eE+-]+), mae:")
        for cid in ("etth1_96_mse", "etth1_336_mse", "etth2_96_mse", "ettm1_96_mse", "etth1_720_mse")
    }),
    "kalmannet": lambda d: from_logs(d, {
        "knet_lin_T20": ("lin_T20_s*.log", r"KalmanNet-MSE Test: tensor\((-?[0-9.]+)\) \[dB\]"),
        "kf_lin_T20": ("lin_T20_s*.log", r"(?<!Extended )Kalman Filter - MSE LOSS: tensor\((-?[0-9.]+)\) \[dB\]"),
        "knet_nlobs_30dB": ("nlobs_30dB_s*.log", r"KalmanNet-MSE Test: tensor\((-?[0-9.]+)\) \[dB\]"),
        "ekf_nlobs_30dB": ("nlobs_30dB_s*.log", r"Extended Kalman Filter - MSE LOSS: tensor\((-?[0-9.]+)\) \[dB\]"),
    }),
    "sgc": lambda d: _pct(from_logs(d, {c: (f"{c}_s*.log", r"Test Accuracy: ([0-9.]+)")
                                         for c in ("cora_acc", "citeseer_acc", "pubmed_acc")})),
    "fits": lambda d: from_logs(d, {c: (f"{c}_s*.log", r"(?m)^mse:([0-9.eE+-]+), mae:")
                                    for c in ("etth1_96_mse", "etth1_720_mse", "etth2_96_mse", "ettm1_96_mse")}),
    "pinn_burgers": lambda d: from_logs(d, {
        "burgers_main_l2": ("main_seed*.log", r"Error u: ([\d.eE+-]+)"),
        "burgers_nu200_l2": ("nu200_seed*.log", r"Error u: ([\d.eE+-]+)"),
        "burgers_l4n20_l2": ("l4n20_seed*.log", r"Error u: ([\d.eE+-]+)"),
    }),
}

if __name__ == "__main__":
    for cid, build in CASES.items():
        case_dir = BENCHMARK / cid
        res = evaluate(Case.load(case_dir), build(case_dir), case_dir, "manual")
        print(f"{cid}: {res.verdict}")
        for v in res.claims:
            print(f"  {v.claim_id:18s} target={v.target:<9g} {v.aggregate}={v.measured_agg or 0:<10.4g} n={v.n_values:<2d} "
                  f"{'PASS' if v.within_tolerance and v.evidence_ok else 'FAIL'}"
                  f"{' [diagnosis only]' if v.diagnostic_only else ''} {v.reason}")
