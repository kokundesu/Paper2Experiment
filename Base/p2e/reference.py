"""Reference re-runs: the official code run n times in our sandbox, which sets each question's tolerance
(the tolerance rule explained in the p2e.corebench docstring).

A recipe (benchmark/v4/<id>/reference.yaml, hidden) is written and checked by the benchmark builder, never by a
workflow under test: setup commands, one run command with {seed}, and a regex per question. `run` executes it n times
(n=5, half of the runs with one BLAS/OpenMP thread so that s also covers summation-order noise), parses the values
and writes reference_values.yaml. `finalize` turns values + paper values into case.yaml:

    h = max(t(0.975, n-1) * s * sqrt(1/m + 1/n), half a unit of the coarser of paper and printed precision,
            1e-5 * |ref_mean| (1e-8 when the mean is 0))
    stochastic       h > 5% of |ref_mean|: reported, not scored
    paper_mismatch   |ref_mean - paper| > h + h_paper: the official code does not reproduce the paper here;
                     still scored against the reference, and the agent should report the gap

n=5 rather than CORE-Bench's 3: with m=1 the noise term is about 5*s at n=3 and 3*s at n=5. Agents run at least
m=3 seeds (stated in the task), which tightens h further. h_paper, the paper value's own tolerance (never scored):
max(precision, 2*std/sqrt(k)) when the paper reports a std over k seeds (k=1 if unknown) or k folds; precision plus
the noise term when it reports no spread. Each claim's case.yaml stores a justification: the three terms, which
one won, n, m and s.

Values are never typed into a recipe; they come only from the logs of these runs.
"""
from __future__ import annotations

import math
import re
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from .corebench import TOLERANCE_RULE, decimals, t975, tolerance
from .runner import RUNS, parse_metric
from .sandbox import Sandbox

N_RUNS = 5
AGENT_RUNS = 3  # m: the seeds an agent submits per question
SEEDS = (0, 1, 2, 3, 4)
ONE_THREAD = "OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 "


class MetricRule(BaseModel):
    regex: str = Field(description="One capture group; the last match in the run's output is used")
    scale: float = 1.0


class Recipe(BaseModel):
    id: str
    status: Literal["draft", "validated"] = "draft"
    repo: str
    commit: str = ""  # pinned once the builder has cloned and checked the setup
    files: dict[str, str] = Field(default_factory=dict, description="Helper files (patch scripts) written into the "
                                                                    "workspace before setup")
    setup: list[str] = Field(default_factory=list, description="Run once, from the workspace")
    command: str = Field("", description="One run, from the workspace; {seed} is replaced")
    timeout_s: int = 1800
    seeded: bool = True  # False: deterministic code, the n runs differ only in threads
    metrics: dict[str, MetricRule] = Field(default_factory=dict)
    entry: str = ""  # the reproduction entry point the builder starts from
    # The official code's own trace (training/fit output) that a log must show for its numbers to count; checked
    # against this recipe's reference logs. Hidden, like the recipe.
    evidence_pattern: str = ""
    notes: list[str] = Field(default_factory=list)

    def problems(self, question_ids: list[str]) -> list[str]:
        out = []
        if not self.command:
            out.append("no run command")
        elif self.seeded and "{seed}" not in self.command:
            out.append("seeded recipe without {seed} in the command")
        if missing := [q for q in question_ids if q not in self.metrics]:
            out.append(f"no metric regex for {missing}")
        for q, rule in self.metrics.items():
            try:
                if re.compile(rule.regex).groups != 1:
                    out.append(f"{q}: regex needs exactly one capture group")
            except re.error as e:
                out.append(f"{q}: regex does not compile: {e}")
        return out


def load_recipe(path: Path) -> Recipe:
    return Recipe.model_validate(yaml.safe_load(path.read_text()))


def printed_places(regex: str, output: str) -> int | None:
    """Decimal places of the last value the run printed for this regex."""
    try:
        matches = re.findall(regex, output)
    except re.error:
        return None
    if not matches:
        return None
    last = matches[-1] if isinstance(matches[-1], str) else next((g for g in matches[-1] if g), "")
    try:
        float(last)
    except ValueError:
        return None
    return decimals(last)


def run(recipe: Recipe, questions: list[str], out_dir: Path, n: int = N_RUNS, seeds=SEEDS,
        runs_root: Path | None = None) -> dict:
    """Execute a recipe n times; write and return reference_values.yaml's content."""
    if problems := recipe.problems(questions):
        raise ValueError(f"{recipe.id}: recipe not runnable: {problems}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = (runs_root or RUNS / "reference") / f"{stamp}_{recipe.id}"
    sb = Sandbox(run_dir, default_timeout_s=recipe.timeout_s)
    for name, text in recipe.files.items():
        path = sb.resolve(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    setup_logs = []
    for cmd in recipe.setup:
        res = sb.run(cmd, ".", recipe.timeout_s, tag="setup")
        setup_logs.append(res.log_path.name)
        if not res.ok:
            raise RuntimeError(f"{recipe.id}: setup failed ({res.log_path}): {res.tail(800)}")
    runs, values = [], {q: [] for q in questions}
    places: dict[str, int] = {}
    for i in range(n):
        seed = seeds[i % len(seeds)]
        threads = "1" if i % 2 else "default"
        cmd = (ONE_THREAD if threads == "1" else "") + recipe.command.replace("{seed}", str(seed))
        t0 = time.monotonic()
        res = sb.run(cmd, ".", recipe.timeout_s, tag=f"ref_{i}")
        row = {"i": i, "seed": seed if recipe.seeded else None, "threads": threads, "exit": res.exit_code,
               "wall_s": round(time.monotonic() - t0, 1), "log": res.log_path.name, "values": {}}
        for q in questions:
            rule = recipe.metrics[q]
            v = parse_metric(res.output, rule.regex, rule.scale) if res.ok else None
            row["values"][q] = v
            if v is not None:
                values[q].append(v)
                if (p := printed_places(rule.regex, res.output)) is not None:
                    places[q] = max(places.get(q, 0), p)
        runs.append(row)
    doc = {"id": recipe.id, "recipe_status": recipe.status, "commit": recipe.commit, "run_dir": str(run_dir),
           "n": n, "setup_logs": setup_logs, "runs": runs, "values": values, "printed_places": places,
           "manifest": dict(sb.manifest)}
    (out_dir / "reference_values.yaml").write_text("# Reference re-runs of the official code (hidden).\n"
                                                   + yaml.safe_dump(doc, sort_keys=False))
    sb.discard_workspace()  # values, logs and their hashes are kept; the environment is gigabytes
    return doc


def paper_half_width(g: dict, noise: float, precision: float) -> float:
    """h_paper: the paper value's own uncertainty (section 3.3, table of spreads)."""
    spread, over = g.get("reported_spread"), g.get("spread_over")
    if spread and over in ("seeds", "runs", "splits", "folds"):
        k = g.get("n_runs") or 1
        return max(precision, 2 * spread / math.sqrt(k))
    return precision + noise


def finalize(pid: str, ref: dict, gt_values: dict, m: int = AGENT_RUNS) -> dict:
    """case.yaml content: per question the reference statistics, h and its terms, status and justification."""
    questions = {}
    for qid, vals in ref["values"].items():
        g = gt_values[qid]
        if len(vals) < 2:
            questions[qid] = {"status": "no_reference", "values": vals,
                              "justification": f"only {len(vals)} reference value(s): tolerance not computable"}
            continue
        paper_places = g.get("precision")
        printed = ref.get("printed_places", {}).get(qid)
        places = min(p for p in (paper_places, printed) if p is not None) if (paper_places is not None or
                                                                                printed is not None) else None
        tol = tolerance(vals, m=m, places=places)
        h_paper = paper_half_width(g, tol["noise"], tol["precision"])
        gap = abs(tol["mean"] - g["paper_value"])
        mismatch = gap > tol["h"] + h_paper
        status = "stochastic" if tol["stochastic"] else "paper_mismatch" if mismatch else "scored"
        questions[qid] = {
            "status": status, "paper_value": g["paper_value"], "ref_mean": tol["mean"], "ref_s": tol["s"],
            "n": tol["n"], "m": m, "h": tol["h"], "term": tol["term"], "noise": tol["noise"],
            "precision": tol["precision"], "floor": tol["floor"], "h_paper": h_paper, "paper_gap": gap,
            "justification": (f"h = max(noise {tol['noise']:.3g} [t({tol['n'] - 1})={t975(tol['n'] - 1)}, "
                              f"s={tol['s']:.3g}, n={tol['n']}, m={m}], precision {tol['precision']:.3g} "
                              f"[{places} places], floor {tol['floor']:.3g}) = {tol['h']:.3g} ({tol['term']}); "
                              f"paper gap {gap:.3g} vs h + h_paper {tol['h'] + h_paper:.3g}")}
    return {"id": pid, "rule": TOLERANCE_RULE, "reference_run_dir": ref["run_dir"],
            "questions": questions}


def scaffold(entry: dict, questions: list[str], entry_point: str = "", notes: list[str] | None = None) -> Recipe:
    """A draft recipe for the builder to complete (no command or regex is guessed)."""
    return Recipe(id=entry["id"], repo=entry["repo"], entry=entry_point, notes=notes or [],
                  setup=[f"git clone {entry['repo'].split('/tree/')[0]} repo"], metrics={})


def summary(values: list[float]) -> str:
    if not values:
        return "-"
    s = statistics.stdev(values) if len(values) > 1 else 0.0
    return f"{statistics.fmean(values):.6g} ± {s:.2g} (n={len(values)})"
