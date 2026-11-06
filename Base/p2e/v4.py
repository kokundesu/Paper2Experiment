"""The v4 dataset (benchmark/v4) in the run format every workflow version reads: benchmark/v4-<id>/task.yaml (what
agents see) and case.yaml (hidden).

Built from the frozen ReproSpec (spec.yaml), the paper values (gt.yaml) and the reference re-runs (case.yaml of
benchmark/v4/<id>), following docs/benchmark-redesign.md section 3.3:

    target       the official code's mean over the reference re-runs (claim.target = "reference")
    tolerance    abs h from the reference re-runs, the mean over at least 3 seed runs is compared
    stochastic   diagnostic_only: measured and reported, never in the verdict
    paper value  kept in the case (paper_value) and in an unresolved discrepancy for paper_mismatch claims: the
                 diagnosis is still graded on whether the agent reports the gap

A paper without reference re-runs (no case.yaml) cannot be converted: its tolerance does not exist yet.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from .intent import V4, check_frozen, load_dataset
from .runner import BENCHMARK

PREFIX = "v4-"
SEED_RUN = "one complete run of the experiment with one seed; the three runs use different seeds, and the seed must " \
           "change what the code does"
# A run's own counter trace (seed/split/trial/fold/iteration/epoch/step/run followed by a number). It is ORed with
# each paper's official-code trace, so an agent's own driver around the official code is accepted too.
GENERIC_TRACE = r"(?i:\b(?:seeds?|splits?|trials?|folds?|iter(?:ation)?s?|epochs?|steps?|runs?)\b\W{0,3}\d+)"


def evidence_pattern(official: str) -> str:
    """The official trace OR the generic one; a leading (?i) becomes a scoped group so the two can be joined."""
    part = f"(?i:{official[4:]})" if official.startswith("(?i)") else f"(?:{official})"
    return f"{part}|{GENERIC_TRACE}"
MIN_SEEDS = 3


def split() -> dict:
    return yaml.safe_load((V4 / "split.yaml").read_text())


def members(part: str) -> list[str]:
    return sorted(p for ids in split()[part].values() for p in ids)


def ready(ids: list[str] | None = None) -> list[str]:
    return [p for p in (ids or [e["id"] for e in load_dataset()]) if (V4 / p / "case.yaml").exists()]


def convert(pid: str, out_root: Path = BENCHMARK) -> Path:
    if bad := check_frozen():
        raise ValueError(f"frozen files changed: {bad}")
    src = V4 / pid
    entry = next(e for e in load_dataset() if e["id"] == pid)
    spec = yaml.safe_load((src / "spec.yaml").read_text())
    ref = yaml.safe_load((src / "case.yaml").read_text())["questions"]
    gt = yaml.safe_load((src / "gt.yaml").read_text())["values"]
    protocol = yaml.safe_load((V4 / "decisions.yaml").read_text()).get("protocol", {})
    run_definition = (protocol.get("splits", {}).get(pid) or SEED_RUN).removeprefix("一次运行 = ")
    pattern = yaml.safe_load((src / "reference.yaml").read_text()).get("evidence_pattern")
    if not pattern:
        raise ValueError(f"{pid}: reference.yaml has no evidence_pattern")
    case_id = PREFIX + pid
    out = out_root / case_id
    (out / "paper").mkdir(parents=True, exist_ok=True)
    pdf = f"paper/{entry['arxiv']}.pdf"
    shutil.copy(src / pdf, out / pdf)
    claims, gt_claims, discrepancies = [], [], []
    for q in spec["questions"]:
        r = ref[q["id"]]
        if r["status"] == "no_reference":
            raise ValueError(f"{pid}/{q['id']}: no reference values")
        description = f"{q['text']} Setting: {q['setting']}"
        claims.append({"id": q["id"], "metric": q["metric"] or q["id"], "setting": q["locator"], "unit": q["unit"],
                       "description": description})
        gt_claims.append({"id": q["id"], "metric": q["metric"] or q["id"], "setting": q["locator"], "unit": q["unit"],
                          "value": float(r["ref_mean"]), "tolerance": {"abs": float(r["h"])}, "target": "reference",
                          "paper_value": float(gt[q["id"]]["paper_value"]), "evidence_pattern": evidence_pattern(pattern),
                          "ref_spread": float(r["ref_s"]), "run_definition": run_definition,
                          "diagnostic_only": r["status"] == "stochastic"})
        if r["status"] == "stochastic":
            discrepancies.append({"claim_id": q["id"], "category": "randomness", "confidence": "unresolved",
                                  "summary": f"reference re-runs vary too much to score (h = {r['h']:.3g}, "
                                             f"over 5% of the mean)"})
        elif r["status"] == "paper_mismatch":
            discrepancies.append({"claim_id": q["id"], "category": "unknown", "confidence": "unresolved",
                                  "summary": f"the official code itself misses the paper here (reference "
                                             f"{r['ref_mean']:.4g} vs paper {r['paper_value']:.4g}); scored against "
                                             f"the reference, the diagnosis should report the gap"})
    task = {"id": case_id, "paper_pdf": pdf, "paper_url": f"https://arxiv.org/pdf/{entry['arxiv']}",
            "repo_url": entry["repo"], "objective": spec["objective"], "claims": claims,
            "seeds": MIN_SEEDS}
    case = {"id": case_id, "rubric": {"min_seeds": MIN_SEEDS, "aggregate": "mean"}, "claims": gt_claims,
            "discrepancies": discrepancies,
            "source": {"spec": "benchmark/v4/" + pid, "split": "test" if pid in members("test") else "dev"}}
    (out / "task.yaml").write_text("# v4 task as agents see it (from the frozen ReproSpec). No target values.\n"
                                   + yaml.safe_dump(task, sort_keys=False, allow_unicode=True))
    (out / "case.yaml").write_text("# Hidden: targets are the reference re-runs' means, tolerances their h.\n"
                                   + yaml.safe_dump(case, sort_keys=False, allow_unicode=True))
    return out
