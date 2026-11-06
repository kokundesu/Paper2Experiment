"""Baseline without an LLM: clone, install as documented, run the README command, regex the metric.

It follows the repository's own instructions literally and has no way to
debug, so it measures how far "just run it" gets on a modern machine.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from ..runner import RunContext, aggregate, execute, finish
from ..schemas import EvalResult, Metrics, RunSpec

GENERIC_METRIC = r"(?i)(?:accuracy|acc|error|ratio|rate)\b[^0-9\n]*?([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"


def _readme_command(repo: Path) -> tuple[str, Path] | None:
    """First `python <script>.py ...` mentioned in the README, resolved to a file in the repo."""
    for readme in sorted(repo.glob("README*")):
        for m in re.finditer(r"python3?\s+([\w./-]+\.py)([^\n`]*)", readme.read_text(errors="replace")):
            script = m.group(1)
            if Path(script).name == "setup.py":
                continue
            hits = [p for p in repo.rglob(Path(script).name) if ".venv" not in p.parts]
            if hits:
                return m.group(0).strip(), hits[0]
    return None


def _fallback_entry(repo: Path) -> Path | None:
    for name in ("main.py", "train.py", "run.py", "demo.py"):
        hits = [p for p in repo.rglob(name) if ".venv" not in p.parts]
        if hits:
            return sorted(hits, key=lambda p: len(p.parts))[0]
    return None


def run(ctx: RunContext) -> EvalResult:
    started = time.monotonic()
    sb = ctx.sandbox
    task = ctx.task

    if not sb.run(f"git clone --depth 1 {task.repo_url} repo", tag="clone").ok:
        return finish(ctx, Metrics(claims=[], notes="clone failed"), started, "clone failed")
    repo = sb.workspace / "repo"

    sb.run("uv venv --python 3.11 .venv", tag="venv")
    py = str(sb.workspace / ".venv/bin/python")
    req = repo / "requirements.txt"
    if req.exists():
        if not sb.run(f"uv pip install --python {py} -r repo/requirements.txt", timeout_s=900, tag="install").ok:
            # Pinned versions often no longer exist for this Python; retry without pins.
            names = [re.split(r"[<>=!~;\[ ]", line.strip())[0] for line in req.read_text().splitlines()
                     if line.strip() and not line.startswith("#")]
            sb.run(f"uv pip install --python {py} {' '.join(names)}", timeout_s=900, tag="install_unpinned")
    if (repo / "setup.py").exists() or (repo / "pyproject.toml").exists():
        sb.run(f"uv pip install --python {py} --no-deps -e repo", tag="install_pkg")

    found = _readme_command(repo)
    script = found[1] if found else _fallback_entry(repo)
    if script is None:
        return finish(ctx, Metrics(claims=[], notes="no entrypoint found"), started, "no entrypoint")
    source = script.read_text(errors="replace")
    ctx.trace.log("deterministic", "entrypoint", readme_command=found[0] if found else None,
                  script=str(script.relative_to(sb.workspace)))

    records = []
    for claim in task.claims:
        for seed in range(task.seeds):
            args = []
            if re.search(r"['\"]-?-?dataset['\"]", source):
                args.append(f"--dataset {claim.setting}")
            if re.search(r"['\"]-?-?seed['\"]", source):
                args.append(f"--seed {seed}")
            spec = RunSpec(run_id=f"{claim.id}_s{seed}", claim_id=claim.id, seed=seed,
                           command=f"{py} {script.name} {' '.join(args)}".strip(),
                           workdir=str(script.parent.relative_to(sb.workspace)),
                           timeout_s=1200, metric_regex=GENERIC_METRIC)
            rec = execute(ctx, spec)
            if rec.value is not None and claim.unit == "%" and rec.value <= 1.0:
                rec.value *= 100
            records.append(rec)
            if rec.exit_code != 0 and seed == 0:
                break  # same command will fail again; don't burn time on more seeds
    return finish(ctx, aggregate(records), started)
