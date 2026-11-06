"""Command line entry point.

    p2e run --case <case> --workflow single fixed planner --model haiku55
    p2e resume runs/<run_dir>          # continue an interrupted run of a checkpointed workflow
    p2e eval runs/<run_dir>            # re-score a finished run
    p2e table                          # summary of all runs
    p2e serve                          # web UI (live workflow view + workflow comparison)
    p2e corebench overview             # CORE-Bench v1.1 tasks and how our tolerance grades them
    p2e corebench grade <capsule> <report.json>
    p2e corebench export --split dev|test [--languages Python R] [--vision]   # spec.yaml + case.yaml per runnable task
    p2e corebench download --split dev [capsules...]   # capsule archives of that split's exported tasks
    p2e corebench report --split dev --since <stamp> [--out file.md]   # agent evaluation of a batch of runs
    p2e corebench inspect <capsule>    # Hard-level clean-up of a downloaded capsule: what is removed, what looks risky
    p2e corebench run <capsule...|downloaded> --split dev --workflow single fixed planner_workers --model haiku55
                       [--update-skills]  # dev only: one skill upgrade round after the batch
                       (test split: refuses piloted capsules and an unfrozen skill library)
    p2e intent run [paper ids]         # v4 dataset: draft specs, multi-provider checks, GT extraction
    p2e intent freeze | check          # apply decisions.yaml and freeze; verify the frozen hashes
    p2e reference status | run <id> | finalize <id>   # reference re-runs of the official code -> case.yaml
    p2e skills status                  # skill library: version, skills, freeze state
    p2e skills update <run dirs...> [--dry-run] [--curator sonnet55]   # one upgrade round from development runs
    p2e skills freeze "<reason>"       # lock the library before any test-split run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml


def load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines from the project's .env; variables already set in the shell win.

    Runs before the imports below, which read P2E_* settings at import time.
    """
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .evaluator import evaluate  # noqa: E402
from .llm import DEFAULT_EFFORT, DEFAULT_MODEL, RUN_BUDGET_USD  # noqa: E402
from .models import get_profile  # noqa: E402
from .runner import BENCHMARK, RUNS, new_run, resume_run  # noqa: E402
from .schemas import Case, DiscrepancyReport, Metrics  # noqa: E402
from .versions import discover  # noqa: E402
from .workflows import deterministic  # noqa: E402

# deterministic is built in; every other workflow is a version folder next to Base/ (see p2e.versions)
VERSIONS = discover()
WORKFLOWS = {"deterministic": deterministic.run, **{name: m.run for name, m in VERSIONS.items()}}
LLM_WORKFLOWS = set(VERSIONS)


MIN_FREE_GB = 6.0  # below this before a run: clear the package caches; still below STOP_FREE_GB: stop the batch
STOP_FREE_GB = 4.0
KEEP_ARCHIVES_GB = 10.0  # below this after a capsule's runs, its archive is deleted


def free_gb() -> float:
    import shutil as _sh
    return _sh.disk_usage(RUNS).free / 1e9


def clear_caches() -> None:
    """Package caches (uv, micromamba) grow by gigabytes per task, since every task installs different packages."""
    import shutil as _sh
    import subprocess
    from .sandbox import MAMBA_PKGS, MAMBA_ROOT, UV_CACHE
    _sh.rmtree(UV_CACHE, ignore_errors=True)
    mm = MAMBA_ROOT / "bin" / "micromamba"
    if MAMBA_PKGS:  # this job slot's own package cache
        _sh.rmtree(MAMBA_PKGS, ignore_errors=True)
    elif mm.is_file():
        subprocess.run([str(mm), "clean", "-a", "-y", "-q"], env={**os.environ, "MAMBA_ROOT_PREFIX": str(MAMBA_ROOT)},
                       capture_output=True)


def disk_ok() -> bool:
    if free_gb() < MIN_FREE_GB:
        clear_caches()
    if free_gb() < STOP_FREE_GB:
        print(f"stopping: only {free_gb():.1f} GB free on disk", flush=True)
        return False
    return True


def cmd_run(args) -> int:
    try:
        profiles = [get_profile(m) for m in args.model]
    except KeyError as e:
        print(f"error: {e.args[0]}", file=sys.stderr)
        return 2
    if set(args.workflow) & LLM_WORKFLOWS:
        for prof in profiles:
            if not os.environ.get(prof.api_key_env):
                print(f"error: model profile {prof.name} needs {prof.api_key_env} (put it in .env or export it)",
                      file=sys.stderr)
                return 2
            if not prof.prices.known:
                print(f"warning: model profile {prof.name} has no prices: its cost counts as $0 and the run budget "
                      f"cannot stop it", file=sys.stderr)
    llm_profiles = profiles if set(args.workflow) & LLM_WORKFLOWS else profiles[:1]
    from .corebench import code_fingerprint
    print(f"models={', '.join(p.label for p in llm_profiles)} effort={DEFAULT_EFFORT} "
          f"budget per run=${RUN_BUDGET_USD:.2f} code={code_fingerprint()}", flush=True)
    from . import skills, v4
    if args.update_skills and (test := [c for c in args.case if c.removeprefix(v4.PREFIX) in v4.members("test")]):
        print(f"error: {test} are test cases: their runs never update the skill library", file=sys.stderr)
        return 2
    batch = []
    for case_id in args.case:
        for wf in args.workflow:
            # the deterministic workflow uses no model: run it once, not once per profile
            for prof in (profiles[:1] if wf == "deterministic" else profiles):
                for rep in range(args.repeats):
                    # run dir: <stamp>_<case>_<workflow>[_<profile>][_r<n>]; the profile is in the name for LLM runs
                    parts = ([prof.name] if wf != "deterministic" else []) + ([f"r{rep}"] if args.repeats > 1 else [])
                    ctx = new_run(case_id, wf, tag="_".join(parts), model=prof.name)
                    print(f"[{case_id} / {wf}] {ctx.run_dir.relative_to(RUNS.parent)}", flush=True)
                    result = WORKFLOWS[wf](ctx)
                    summary = json.loads((ctx.run_dir / "summary.json").read_text())
                    print(f"  verdict={result.verdict}  wall={summary['wall_s']}s  cost=${summary['llm']['cost_usd']}")
                    det, attr, strict, fs = _diagnosis_cols(summary.get("diagnosis"))
                    print(f"  diagnosis: detected={det}  attribution={attr}  strict={strict}  false_success={fs}")
                    for cid, c in summary["claims"].items():
                        val = "-" if c["value"] is None else f"{c['value']:.4g}"
                        tag = " [diagnosis only]" if c.get("diagnostic_only") else ""
                        print(f"    {cid:20s} target={c['target']:<10g} {c['aggregate']}={val:<10} n={c['n']} "
                              f"{'PASS' if c['pass'] else 'FAIL'}{tag} {c['reason']}")
                    if not args.keep_workspace:
                        ctx.sandbox.discard_workspace()
                    batch.append(ctx.run_dir)
    if args.update_skills and batch:
        _update_skills(batch, args.curator)
    return 0


def cmd_resume(args) -> int:
    try:
        ctx = resume_run(Path(args.run_dir))
    except (OSError, ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    version = VERSIONS.get(ctx.workflow)
    if version is None or not getattr(version, "RESUMABLE", False):
        resumable = ", ".join(n for n, m in VERSIONS.items() if getattr(m, "RESUMABLE", False))
        print(f"error: {ctx.run_dir.name} is a {ctx.workflow} run; only these workflows are checkpointed: {resumable}",
              file=sys.stderr)
        return 2
    if not os.environ.get(ctx.budget.profile.api_key_env):
        print(f"error: model profile {ctx.budget.profile.name} needs {ctx.budget.profile.api_key_env}", file=sys.stderr)
        return 2
    print(f"[{ctx.case_id} / {ctx.workflow}] resuming {ctx.run_dir.relative_to(RUNS.parent)}", flush=True)
    result = version.run(ctx, resume=True)
    summary = json.loads((ctx.run_dir / "summary.json").read_text())
    print(f"  verdict={result.verdict}  wall={summary['wall_s']}s  cost=${summary['llm']['cost_usd']}")
    if not args.keep_workspace:
        ctx.sandbox.discard_workspace()
    return 0


def cmd_eval(args) -> int:
    run_dir = Path(args.run_dir).resolve()
    summary = json.loads((run_dir / "summary.json").read_text())
    metrics = Metrics.model_validate_json((run_dir / "metrics.json").read_text())
    manifest_path = run_dir / "log_manifest.json"  # absent in runs from before the log integrity check
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    result = evaluate(Case.load(BENCHMARK / summary["case"]), metrics, run_dir, summary["workflow"],
                      DiscrepancyReport.load(run_dir), manifest)
    print(result.model_dump_json(indent=2))
    return 0


def _diagnosis_cols(dg: dict | None) -> tuple[str, str, str, str]:
    """det = failing claims flagged, attr = scored root causes right, strict = right and for a decisive reason,
    false_succ = misses called reproduced."""
    if not dg or not dg["present"]:
        return "none", "-", "-", "-"
    return (f"{dg['n_detected']}/{dg['n_failing']}", f"{dg['n_attribution_correct']}/{dg['n_attributed']}",
            f"{dg.get('n_strict_correct', '?')}/{dg['n_attributed']}", str(len(dg["false_success"])))


def cmd_table(args) -> int:
    rows = []
    for s in sorted(RUNS.glob("*/summary.json")):
        d = json.loads(s.read_text())
        scored = [c for c in d["claims"].values() if not c.get("diagnostic_only")]  # claims behind the verdict
        rows.append((s.parent.name, d["case"], d["workflow"], d["verdict"],
                     f"{sum(c['pass'] for c in scored)}/{len(scored)}",
                     *_diagnosis_cols(d.get("diagnosis")),
                     f"{d['wall_s']:.0f}", f"{d['llm'].get('cost_usd', 0):.2f}", (d.get("error") or "")[:40]))
    header = ("run", "case", "workflow", "verdict", "claims", "det", "attr", "strict", "false_succ", "wall_s", "usd",
              "error")
    widths = [max(len(str(r[i])) for r in rows + [header]) for i in range(len(header))]
    for r in [header] + rows:
        print("  ".join(str(x).ljust(w) for x, w in zip(r, widths)))
    return 0


def cmd_serve(args) -> int:
    from .web.server import serve
    return serve(args.host, args.port, open_browser=not args.no_browser)


def cmd_corebench(args) -> int:
    from . import corebench
    tasks = corebench.load_tasks()
    if args.action == "run":
        return _corebench_run(args, corebench)
    if args.action == "report":
        from . import agenteval
        runs = agenteval.collect(RUNS, split=args.split, since=args.since, until=args.until,
                                 workflows=args.workflow if args.workflow != ["single"] else None,
                                 profiles=args.profile, skills={"on": True, "off": False}.get(args.skills))
        if not runs:
            print("error: no CORE-Bench runs match", file=sys.stderr)
            return 2
        text = agenteval.report(runs, title=f"Agent evaluation: CORE-Bench {args.split}"
                                + (f", runs since {args.since}" if args.since else "")
                                + (f", {' '.join(args.profile)}" if args.profile else "")
                                + (f", skills {args.skills}" if args.skills else ""))
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text)
        print(text)
        return 0
    if args.action == "export":
        data, tasks_dir, _ = corebench.split_paths(args.split)
        langs = tuple(args.languages)
        ids = corebench.export(corebench.load_tasks(data), out=tasks_dir, data=data, split=args.split,
                               languages=langs, vision=args.vision)
        print(f"wrote {len(ids)} {args.split} tasks to {tasks_dir}: {', '.join(ids)}")
        return 0
    if args.action == "download":
        import subprocess
        from concurrent.futures import ThreadPoolExecutor
        data, tasks_dir, caps_dir = corebench.split_paths(args.split)
        wanted = [c for c in (args.capsule, args.report, *args.more) if c] or sorted(
            "capsule-" + d.name.removeprefix("cb-") for d in tasks_dir.glob("cb-*"))
        caps_dir.mkdir(parents=True, exist_ok=True)

        def fetch(cid: str) -> str:  # the server throttles each connection: several at once, resumable
            dest = caps_dir / f"{cid}.tar.gz"
            if dest.is_file():
                return f"  have {cid}"
            part = caps_dir / f"{cid}.tar.gz.part"
            url = corebench.CAPSULE_URL[args.split].format(id=cid)
            for _ in range(30):  # a stalled connection (under 2 KB/s for 60 s) is dropped and resumed
                r = subprocess.run(["curl", "-sSL", "--fail", "--speed-limit", "2048", "--speed-time", "60",
                                    "-C", "-", "-o", str(part), url])
                if r.returncode in (0, 33) or r.returncode == 22:  # 33: range not satisfiable = already complete
                    break
            if r.returncode == 22:
                return f"  FAILED {cid} (HTTP error)"
            if r.returncode not in (0, 33):
                return f"  FAILED {cid} (curl exit {r.returncode}; run again to resume)"
            if subprocess.run(["gzip", "-t", str(part)], capture_output=True).returncode != 0:
                part.unlink(missing_ok=True)
                return f"  FAILED {cid} (archive corrupt; deleted, run again)"
            part.rename(dest)
            return f"  got {cid} ({dest.stat().st_size / 1e6:.1f} MB)"

        with ThreadPoolExecutor(args.parallel) as pool:
            for line in pool.map(fetch, wanted):
                print(line, flush=True)
        return 0
    if args.action == "inspect":
        import tempfile
        from . import capsule
        archive = corebench.CAPSULES / f"{args.capsule}.tar.gz"
        if not archive.is_file():
            print(f"error: {archive} not downloaded", file=sys.stderr)
            return 2
        with tempfile.TemporaryDirectory() as tmp:
            ext = capsule.extract(archive, Path(tmp), hard=True)
            snap = capsule.snapshot(Path(tmp))
        print(f"kept {len(ext.kept)} files; removed {len(ext.removed)}; refused {len(ext.refused)}")
        for rel, why in sorted(ext.removed.items()):
            print(f"  removed  {rel}  ({why})")
        for rel, why in sorted(ext.refused.items()):
            print(f"  refused  {rel}  ({why})")
        for rel in capsule.opaque_results(snap):
            print(f"  RISK     {rel}  (binary file that looks like stored results; answers read from it are not detected)")
        return 0
    if args.action == "overview":
        rows = corebench.overview(tasks)
        for r in rows:
            num = ", ".join(f"h={t['h']:.3g}({t['term']}{', stochastic' if t['stochastic'] else ''})"
                            for t in r["numeric"])
            print(f"{r['capsule_id']}  {r['language']:<6} {'GPU' if r['gpu'] else 'cpu'}  questions={r['questions']} "
                  f"vision={r['vision_questions']}  {num}")
        fit = [r for r in rows if not r["gpu"] and r["language"] == "Python" and not r["vision_questions"]]
        print(f"\n{len(rows)} tasks; CPU + Python + no figure questions: {len(fit)}")
        return 0
    task = next((t for t in tasks if t["capsule_id"] == args.capsule), None)
    if task is None:
        print(f"error: unknown capsule {args.capsule}", file=sys.stderr)
        return 2
    text = Path(args.report).read_text()
    result = corebench.grade_task(task, text)
    for q in result.questions:
        flag = "ok " if q.correct else "NO "
        print(f"{flag}{'' if q.scored else '(stochastic, not scored) '}{q.question[:90]}"
              + (f"  [h={q.detail['h']:.3g} {q.detail['term']}]" if "h" in q.detail else "")
              + (f"  note: {q.note}" if q.note else ""))
    hal = corebench.hal_grade(task, json.loads(text)) if result.valid else False
    print(f"full: {result.full}   (original HAL rule: {hal})")
    return 0 if result.full else 1


def cmd_intent(args) -> int:
    from . import intent
    roles = intent.Roles(drafter=args.drafter, checkers=tuple(args.checkers), extractors=tuple(args.extractors))
    if problems := roles.problems():
        print("error: " + "; ".join(problems), file=sys.stderr)
        return 2
    for m in {roles.drafter, *roles.checkers, *roles.extractors}:
        if not os.environ.get(get_profile(m).api_key_env):
            print(f"error: model profile {m} needs {get_profile(m).api_key_env}", file=sys.stderr)
            return 2
    if args.action == "check":
        bad = intent.check_frozen()
        print("frozen files intact" if not bad else "CHANGED since freezing: " + ", ".join(bad))
        return 1 if bad else 0
    if args.action == "freeze":
        decisions = yaml.safe_load((intent.V4 / "decisions.yaml").read_text())
        for pid, d in decisions["papers"].items():
            if d.get("revise"):
                entry = next(p for p in intent.load_dataset() if p["id"] == pid)
                have = {q["id"] for q in yaml.safe_load((intent.V4 / pid / "spec.yaml").read_text())["questions"]}
                todo = {old: new for old, new in d["revise"].items() if old in have}  # skip ones already applied
                if not todo:
                    continue
                res = intent.revise(entry, todo, roles)
                print(f"[{pid}] revised: " + ", ".join(f"{q}={g.get('printed')} ({g['status']})"
                                                       for q, g in res["values"].items()), flush=True)
        if proto := decisions.get("protocol"):
            for entry in intent.load_dataset():
                intent.update_fields(entry, proto.get("all_questions", {}),
                                     proto.get("splits", {}).get(entry["id"], ""))
        manifest = intent.freeze(intent.load_dataset(), decisions)
        print(f"frozen {len(manifest['papers'])} papers, "
              f"{sum(len(r['questions']) for r in manifest['papers'].values())} questions; code {manifest['code']}")
        return 0
    papers = intent.load_dataset()
    if args.ids:
        papers = [p for p in papers if p["id"] in args.ids]
    print(f"drafter={roles.drafter} checkers={','.join(roles.checkers)} extractors={','.join(roles.extractors)} "
          f"papers={len(papers)}", flush=True)
    results, total = [], 0.0
    for p in papers:
        try:
            r = intent.run_paper(p, roles)
        except Exception as e:  # one paper must not stop the others
            print(f"[{p['id']}] failed: {type(e).__name__}: {e}", flush=True)
            continue
        results.append(r)
        total += r.cost_usd
        agreed = sum(g["status"] == "agreed" for g in r.gt.values())
        print(f"[{p['id']}] questions={len(r.spec.questions)} values agreed={agreed}/{len(r.gt)} "
              f"to clarify={len(r.queue)} cost=${r.cost_usd:.4f}", flush=True)
    saved = [r for p in intent.load_dataset() if (r := intent.load_result(p))]  # every paper, not just this run's
    (intent.V4 / "clarifications.md").write_text(intent.clarifications_md(saved))
    print(f"total cost ${total:.4f}; clarifications in {intent.V4 / 'clarifications.md'}")
    return 0


def cmd_reference(args) -> int:
    from . import intent, reference
    papers = {p["id"]: p for p in intent.load_dataset()}
    if bad := intent.check_frozen():
        print("error: frozen files changed: " + ", ".join(bad), file=sys.stderr)
        return 2
    if args.action == "status":
        for pid in papers:
            d = intent.V4 / pid
            r = reference.load_recipe(d / "reference.yaml")
            qids = [q["id"] for q in yaml.safe_load((d / "spec.yaml").read_text())["questions"]]
            done = "case.yaml" if (d / "case.yaml").exists() else "values" if (d / "reference_values.yaml").exists() \
                else "-"
            problems = r.problems(qids)
            print(f"{pid:16s} {r.status:9s} {done:11s} {'ready' if not problems else '; '.join(problems)}")
        return 0
    if args.id not in papers:
        print(f"error: unknown paper {args.id}", file=sys.stderr)
        return 2
    d = intent.V4 / args.id
    qids = [q["id"] for q in yaml.safe_load((d / "spec.yaml").read_text())["questions"]]
    if args.action == "run":
        ref = reference.run(reference.load_recipe(d / "reference.yaml"), qids, d)
        for q in qids:
            print(f"{q}: {reference.summary(ref['values'][q])}")
        return 0
    ref = yaml.safe_load((d / "reference_values.yaml").read_text())
    gt = yaml.safe_load((d / "gt.yaml").read_text())["values"]
    case = reference.finalize(args.id, ref, gt)
    (d / "case.yaml").write_text("# Hidden: tolerances from the reference re-runs (pre-registered before any "
                                 "workflow runs).\n" + yaml.safe_dump(case, sort_keys=False, allow_unicode=True))
    for q, row in case["questions"].items():
        print(f"{q}: {row['status']}  {row.get('justification', '')}")
    return 0


SPEC_WORKFLOWS = ("single", "fixed", "planner_workers")  # A, B, D: the versions in the comparison


def _corebench_run(args, corebench) -> int:
    from . import skills
    capsules = [c for c in (args.capsule, args.report, *args.more) if c]
    if capsules == ["downloaded"]:
        _, tasks_dir, caps_dir = corebench.split_paths(args.split)
        capsules = sorted(p.name.removesuffix(".tar.gz") for p in caps_dir.glob("*.tar.gz")
                          if (tasks_dir / corebench.spec_id(p.name.removesuffix(".tar.gz"))).is_dir())
    if not capsules:
        print("error: name capsules (or 'downloaded' with --split)", file=sys.stderr)
        return 2
    splits = {c: corebench.split_of(c) for c in capsules}
    if missing := [c for c, s in splits.items() if s is None]:
        print(f"error: not exported in any split: {missing} (p2e corebench export --split ...)", file=sys.stderr)
        return 2
    if any(s == "test" for s in splits.values()):
        if piloted := [c for c in capsules if c in corebench.PILOTED]:
            print(f"error: {piloted} were run during development and are not in the test split", file=sys.stderr)
            return 2
        try:
            skills.require_frozen()
        except RuntimeError as e:
            print(f"error: test-split run: {e}", file=sys.stderr)
            return 2
        if args.update_skills:
            print("error: test-split runs never update the skill library", file=sys.stderr)
            return 2
    if bad := [w for w in args.workflow if w not in SPEC_WORKFLOWS]:
        print(f"error: no spec mode in {bad}; use {', '.join(SPEC_WORKFLOWS)}", file=sys.stderr)
        return 2
    try:
        profiles = [get_profile(m) for m in args.model]
    except KeyError as e:
        print(f"error: {e.args[0]}", file=sys.stderr)
        return 2
    for prof in profiles:
        if not os.environ.get(prof.api_key_env):
            print(f"error: model profile {prof.name} needs {prof.api_key_env}", file=sys.stderr)
            return 2
    def tag_of(prof, rep: int) -> str:
        return "_".join([prof.name] + ([f"r{rep}"] if args.repeats > 1 else []) + ([] if skills.enabled() else ["noskills"]))

    done = _finished_runs(args.skip_done) if args.skip_done else set()
    todo = {cid: [(wf, prof, rep) for wf in args.workflow for prof in profiles for rep in range(args.repeats)
                  if (corebench.spec_id(cid), wf, tag_of(prof, rep)) not in done] for cid in capsules}
    todo = {cid: units for cid, units in todo.items() if units}
    print(f"capsules={', '.join(capsules)} workflows={', '.join(args.workflow)} repeats={args.repeats} "
          f"models={', '.join(p.label for p in profiles)} budget per run=${RUN_BUDGET_USD:.2f} "
          f"skills={'on' if skills.enabled() else 'off'} jobs={args.jobs} code={corebench.code_fingerprint()}"
          + (f" skipping {sum(len(args.workflow) * len(profiles) * args.repeats for _ in capsules) - sum(map(len, todo.values()))}"
             f" runs finished since {args.skip_done}" if args.skip_done else ""), flush=True)
    _keep_awake()
    if args.jobs > 1:
        batch = _parallel_batch(args, list(todo))
        if args.update_skills and batch:
            _update_skills(batch, args.curator)
        return 0
    batch = []
    for cid, units in todo.items():
        for wf, prof, rep in units:
            if not disk_ok():
                return 1
            tag = tag_of(prof, rep)
            ctx = corebench.new_run(cid, wf, tag=tag, model=prof.name)
            print(f"[{cid} / {wf}] {ctx.run_dir.relative_to(RUNS.parent)}", flush=True)
            try:
                result = WORKFLOWS[wf](ctx)
            except Exception as e:  # one broken run must not stop the batch
                print(f"  crashed: {type(e).__name__}: {e}", flush=True)
                if not args.keep_workspace:
                    ctx.sandbox.discard_workspace()
                continue
            summary = json.loads((ctx.run_dir / "summary.json").read_text())
            print(f"  verdict={result.verdict} tolerance_only={result.full_tolerance_only} "
                  f"hal={result.hal_full} shortcut={len(result.shortcut)} typed={len(result.typed)} "
                  f"wall={summary['wall_s']}s cost=${summary['llm']['cost_usd']}", flush=True)
            if not args.keep_workspace:
                ctx.sandbox.discard_workspace()
            batch.append(ctx.run_dir)
        if not args.keep_workspace:
            clear_caches()  # every workflow has run this capsule: its packages are not needed again
            if free_gb() < KEEP_ARCHIVES_GB:  # short on disk: the archive can be downloaded again
                _, _, caps_dir = corebench.split_paths(splits[cid])
                (caps_dir / f"{cid}.tar.gz").unlink(missing_ok=True)
    if args.update_skills and batch:
        _update_skills(batch, args.curator)
    return 0


def _finished_runs(since: str) -> set[tuple[str, str, str]]:
    """(task, workflow, tag) of every CORE-Bench run with a summary since the stamp `since` (a resumed batch skips them)."""
    out = set()
    for f in RUNS.glob("*_cb-*/summary.json"):
        name = f.parent.name
        if name < since:
            continue
        s = json.loads(f.read_text())
        prefix = f"{s['case']}_{s['workflow']}_"
        if prefix in name:
            out.add((s["case"], s["workflow"], name.split(prefix, 1)[1]))
    return out


def _keep_awake() -> None:
    """macOS: hold an idle-sleep assertion for as long as this process lives (a sleeping Mac stalls every run)."""
    import shutil as _sh
    import subprocess
    if sys.platform == "darwin" and _sh.which("caffeinate"):
        subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


def _parallel_batch(args, capsules: list[str]) -> list[Path]:
    """Run capsules `args.jobs` at a time, each in a child `p2e corebench run` with its own package caches (a child
    clears its caches after each capsule, which must not hit another job's install). Returns the run directories."""
    import queue
    import subprocess
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from .sandbox import MAMBA_ROOT

    slots: queue.Queue[int] = queue.Queue()
    for k in range(args.jobs):
        slots.put(k)
    batch: list[Path] = []
    lock = threading.Lock()
    stop = threading.Event()

    def one(cid: str) -> None:
        if stop.is_set():
            return
        slot = slots.get()
        try:
            if not disk_ok():
                stop.set()
                return
            cmd = [sys.executable, "-m", "p2e.cli", "corebench", "run", cid, "--split", args.split,
                   "--workflow", *args.workflow, "--model", *args.model, "--repeats", str(args.repeats)]
            cmd += (["--skip-done", args.skip_done] if args.skip_done else []) + (
                ["--keep-workspace"] if args.keep_workspace else [])
            env = {**os.environ, "P2E_UV_CACHE": str(RUNS / f".uv-cache-job{slot}"),
                   "P2E_MAMBA_PKGS": str(MAMBA_ROOT / f"pkgs-job{slot}")}
            proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                line = line.rstrip("\n")
                if line.startswith("capsules="):
                    continue  # the child's header repeats the batch's
                with lock:
                    print(f"[job{slot}] {line}", flush=True)
                    if line.startswith("[") and "] runs/" in line:
                        batch.append(RUNS.parent / line.rsplit("] ", 1)[1])
            proc.wait()
        finally:
            slots.put(slot)

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(one, capsules))
    if stop.is_set():
        print(f"stopping: only {free_gb():.1f} GB free on disk", flush=True)
    return [d for d in batch if (d / "summary.json").is_file()]


def _update_skills(batch: list[Path], curator: str) -> None:
    """One skill-library upgrade round from a finished batch of development runs."""
    from . import skills
    try:
        cur, _ = skills.curate([d for d in batch if (d / "summary.json").is_file()], model=curator)
    except Exception as e:  # the batch's results stand without an upgrade
        print(f"skills: curator failed: {type(e).__name__}: {e}", flush=True)
        return
    version, problems = skills.apply(cur)
    print(f"skills: {cur.assessment}\n  " + "\n  ".join(f"{e.action} {e.name}: {e.rationale}" for e in cur.edits)
          + (f"\n  not applied: {problems}" if problems else f"\n  library is now version {version}"), flush=True)


def cmd_skills(args) -> int:
    from . import skills
    if args.action == "status":
        st = skills.state()
        print(f"library {skills.ROOT}: version {st.get('version', 0)}, frozen: {st.get('frozen') or 'no'}, "
              f"hash {skills.library_hash()}, enabled: {skills.enabled()}")
        for s in skills.load():
            print(f"  {s.name} (v{s.version}): {s.description}")
        return 0
    if args.action == "freeze":
        st = skills.freeze(" ".join(args.items) or "frozen")
        print(f"frozen version {st['version']} ({st['frozen']}), hash {st['hash']}")
        return 0
    runs = [Path(r) if Path(r).is_absolute() else RUNS.parent / r for r in args.items]
    if missing := [str(r) for r in runs if not (r / "summary.json").is_file()]:
        print(f"error: not finished runs: {missing}", file=sys.stderr)
        return 2
    cur, out = skills.curate(runs, model=args.curator)
    print(f"curator ({args.curator}): {cur.assessment}\n")
    for e in cur.edits:
        print(f"  {e.action} {e.name}: {e.rationale} (runs: {', '.join(e.evidence)})")
    if args.dry_run:
        print(f"\ndry run: nothing applied; the proposal is in {out / 'curation.json'}")
        return 0
    version, problems = skills.apply(cur)
    if problems:
        print("\nnot applied:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    print(f"\nlibrary is now version {version}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="p2e", description="Paper2Experiment")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run workflow(s) on benchmark case(s)")
    r.add_argument("--case", nargs="+", required=True, choices=sorted(d.name for d in BENCHMARK.iterdir()
                                                                    if (d / "task.yaml").exists()))
    r.add_argument("--workflow", nargs="+", default=["single"], choices=list(WORKFLOWS),
                   help="; ".join(f"{n}: {m.DESCRIPTION}" for n, m in VERSIONS.items()))
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--model", nargs="+", default=[DEFAULT_MODEL],
                   help=f"model profile(s) from models.yaml (default {DEFAULT_MODEL}); several = one run each")
    r.add_argument("--keep-workspace", action="store_true",
                   help="keep each run's workspace/ (repo, venv) after scoring; by default it is deleted")
    r.add_argument("--update-skills", action="store_true",
                   help="after the batch, one skill-library upgrade round from its runs (dev cases only)")
    r.add_argument("--curator", default="sonnet55")
    r.set_defaults(fn=cmd_run)
    rs = sub.add_parser("resume", help="continue an interrupted run of a checkpointed workflow from its last checkpoint")
    rs.add_argument("run_dir")
    rs.add_argument("--keep-workspace", action="store_true")
    rs.set_defaults(fn=cmd_resume)
    e = sub.add_parser("eval", help="re-score a finished run")
    e.add_argument("run_dir")
    e.set_defaults(fn=cmd_eval)
    t = sub.add_parser("table", help="summarise all runs")
    t.set_defaults(fn=cmd_table)
    s = sub.add_parser("serve", help="web UI: live view of running workflows and the single-vs-multi comparison")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true", help="do not open the page in the default browser")
    s.set_defaults(fn=cmd_serve)
    cb = sub.add_parser("corebench", help="CORE-Bench v1.1: task overview, or grade a report with our tolerance")
    cb.add_argument("action", choices=["overview", "grade", "export", "download", "inspect", "run", "report"])
    cb.add_argument("--split", choices=["dev", "test"], default="dev",
                    help="dev: original train set (tuning, skills); test: v1.1 mainline (once, after the freeze)")
    cb.add_argument("--languages", nargs="+", default=["Python"], help="export: languages this machine can run")
    cb.add_argument("--vision", action="store_true", help="export: include tasks with figure questions")
    cb.add_argument("--update-skills", action="store_true",
                    help="run: after the batch, one skill-library upgrade round from its runs (dev split only)")
    cb.add_argument("--curator", default="sonnet55")
    cb.add_argument("--parallel", type=int, default=8, help="download: capsules fetched at once")
    cb.add_argument("--since", default="", help="report: first run stamp, e.g. 20261017-2300")
    cb.add_argument("--until", default="", help="report: last run stamp")
    cb.add_argument("--out", default="", help="report: also write the markdown here")
    cb.add_argument("--profile", nargs="+", help="report: only runs of these model profiles, e.g. haiku55")
    cb.add_argument("--skills", choices=["on", "off"], help="report: only runs with the skill library on / off")
    cb.add_argument("capsule", nargs="?")
    cb.add_argument("report", nargs="?", help="grade: the report.json")
    cb.add_argument("more", nargs="*", help="run: more capsules")
    cb.add_argument("--workflow", nargs="+", default=["single"])
    cb.add_argument("--repeats", type=int, default=1)
    cb.add_argument("--model", nargs="+", default=[DEFAULT_MODEL])
    cb.add_argument("--keep-workspace", action="store_true")
    cb.add_argument("--jobs", type=int, default=1, help="run: capsules run at once (each in its own process)")
    cb.add_argument("--skip-done", default="", metavar="STAMP",
                    help="run: skip runs (same task, workflow, model, repeat, skills on/off) finished since STAMP")
    cb.set_defaults(fn=cmd_corebench)
    it = sub.add_parser("intent", help="v4 dataset: intent stage (draft + checks) and GT stage (extraction)")
    it.add_argument("action", choices=["run", "freeze", "check"])
    it.add_argument("ids", nargs="*")
    it.add_argument("--drafter", default="sol")
    it.add_argument("--checkers", nargs="+", default=["sonnet55", "haiku55"])
    it.add_argument("--extractors", nargs="+", default=["haiku55", "luna"])
    it.set_defaults(fn=cmd_intent)
    rf = sub.add_parser("reference", help="v4 dataset: reference re-runs of the official code and tolerances")
    rf.add_argument("action", choices=["status", "run", "finalize"])
    rf.add_argument("id", nargs="?")
    rf.set_defaults(fn=cmd_reference)
    sk = sub.add_parser("skills", help="skill library shared by A, B and D: status, upgrade round, freeze")
    sk.add_argument("action", choices=["status", "update", "freeze"])
    sk.add_argument("items", nargs="*", help="update: run directories; freeze: the reason")
    sk.add_argument("--curator", default="sonnet55", help="model profile of the curator")
    sk.add_argument("--dry-run", action="store_true")
    sk.set_defaults(fn=cmd_skills)
    args, extra = p.parse_known_args(argv)
    # argparse leaves positionals that come after options unparsed ("download --split dev capsule-1 capsule-2")
    if extra and args.cmd == "corebench" and all(re.fullmatch(r"capsule-\d+", x) for x in extra):
        args.more = [*args.more, *extra]
    elif extra:
        p.error(f"unrecognized arguments: {' '.join(extra)}")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
