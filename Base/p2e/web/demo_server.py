"""HTTP server of the demo UI (`p2e demo serve`): a user's prompt becomes a spec, one workflow version runs it as a
subprocess, and the page follows the run through its trace as a graph of agents.

    GET  /api/options                     workflows, model profiles (and whether their key is set), example capsules
    POST /api/draft   {prompt, capsule?, model}   the request as a ReproSpec (one LLM call); the repository is the
                                                  GitHub URL in the prompt; without one (and no capsule): {need: repo_url}
    POST /api/start   {spec, workflow, model}               launch `p2e demo run`; returns the job key
    GET  /api/history                     the runs started from the page, newest first
    GET  /api/workdir                     the run folder: where runs clone, install and run (each in its own sub-folder)
    POST /api/workdir {path} | /api/workdir/choose   set it, from a path or the macOS folder dialog
    GET  /api/examples                    every task that some earlier run finished quickly, once each
    POST /api/example {case}              that task as a fresh user spec plus the values to compare with
    GET  /api/jobs/<key>                  the run as a graph: nodes (agents, tasks), their steps, answers when done
    POST /api/jobs/<key>/stop             terminate the run's process group
    GET  /api/jobs/<key>/file?path=...    an image or text file of the run's workspace (figures the run made)
    GET  /api/auth | POST /api/auth {code}   whether an access code is needed / try one (sets the session cookie)
    POST /api/presence {id}               this page is open; returns who is online, runs running and queued
    POST /api/logout                      forget this browser's session (to sign in under another name)
    GET  /*                               the built frontend (Base/demo-web, `npm run build`)

On a shared server (P2E_DEMO_CODE set) every other /api/ call needs the session cookie: see access.py. At most
P2E_DEMO_MAX_RUNS runs go at once; the rest wait in a queue, first come first served.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import signal
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .. import corebench, demo, spend
from . import access
from ..models import load_profiles
from ..runner import RUNS
from ..sandbox import PROJECT_ROOT, workspace_root
from ..spec import ReproSpec

DIST = Path(__file__).resolve().parents[2] / "demo-web" / "dist"
WORKFLOWS = [  # the three versions of the comparison (A, B, D)
    {"id": "single", "letter": "A", "name": "Single agent", "desc": "One agent does it all: sets up, runs the code, reads the output, answers"},
    {"id": "fixed", "letter": "B", "name": "Fixed pipeline", "desc": "A fixed pipeline: environment agent → planner → executor → answerer"},
    {"id": "planner_workers", "letter": "D", "name": "Planner + workers",
     "desc": "A planner hands out tasks as needed: workers set up, the runtime runs commands, failures are retried"},
]
KEY = re.compile(r"^user-\d{8}-\d{6}_(single|fixed|planner_workers)$")  # a run launched from the page
RUN_NAME = re.compile(r"^\d{8}-\d{6}_[\w.-]+$")  # any run directory (examples come from these)
GITHUB = re.compile(r"https?://(?:www\.)?github\.com/[\w.-]+/[\w.-]+")
EXAMPLE_MAX_WALL_S = 600  # an example is a task some run answered in under 10 minutes
CB_REFERENCE = "CORE-Bench reference answer (mean of 3 manual re-runs)"
STEP_TARGET = {"run_shell": "command", "read_file": "path", "list_dir": "path", "write_file": "path",
               "view_image": "path", "read_log": "name", "read_skill": "name"}


SETTINGS = RUNS / "demo_drafts" / "settings.json"


def _settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def run_folder() -> Path:
    """Where the page's runs work: the folder chosen on the page, else the default workspace root."""
    chosen = _settings().get("workspace_root")
    return Path(chosen) if chosen else workspace_root()


def workdir_state() -> dict:
    folder = run_folder()
    return {"path": str(folder), "name": folder.name, "default": str(workspace_root()),
            "chosen": bool(_settings().get("workspace_root"))}


def set_run_folder(path: str) -> dict:
    """Make `path` the run folder: absolute, outside the project (agents must not reach the code that grades them),
    created if missing and writable. Raises ValueError with the reason otherwise."""
    if os.environ.get("P2E_DEMO_FIXED_WORKDIR"):  # a shared server: the run folder is set by its operator
        raise ValueError("the run folder is fixed on this server")
    folder = Path(path).expanduser()
    if not folder.is_absolute():
        raise ValueError("the run folder must be an absolute path")
    folder = folder.resolve()
    if folder == PROJECT_ROOT or PROJECT_ROOT in folder.parents or folder in PROJECT_ROOT.parents:
        raise ValueError(f"the run folder must be outside the project ({PROJECT_ROOT})")
    folder.mkdir(parents=True, exist_ok=True)
    if not os.access(folder, os.W_OK):
        raise ValueError(f"cannot write to {folder}")
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps({**_settings(), "workspace_root": str(folder)}, indent=1))
    return workdir_state()


def choose_run_folder() -> dict:
    """The macOS folder dialog (the server runs on the user's machine); {cancelled: true} when dismissed."""
    if sys.platform != "darwin":
        raise ValueError("the folder dialog needs macOS; enter the path instead")
    script = 'POSIX path of (choose folder with prompt "Choose the folder where reproductions run")'
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        return {**workdir_state(), "cancelled": True}
    return set_run_folder(r.stdout.strip())


def max_runs() -> int | None:
    """How many runs may go at once (P2E_DEMO_MAX_RUNS); None: no limit, the default on one's own machine."""
    raw = os.environ.get("P2E_DEMO_MAX_RUNS", "").strip()
    return max(1, int(raw)) if raw else None


class Jobs:
    """Runs launched from the page: key (spec id + workflow) -> process, and the runs waiting for a free slot."""

    def __init__(self):
        self.procs: dict[str, subprocess.Popen] = {}
        self.queue: list[tuple[str, list[str], Path]] = []  # (key, command, output file), first in line first
        self.cancelled: set[str] = set()  # stopped while still in the queue
        self.lock = threading.Lock()
        threading.Thread(target=self._dispatch_forever, daemon=True).start()

    def start(self, spec: ReproSpec, workflow: str, model: str) -> str:
        demo.DRAFTS.mkdir(parents=True, exist_ok=True)
        path = demo.DRAFTS / f"{spec.id}.json"
        path.write_text(spec.model_dump_json(indent=1))
        key = f"{spec.id}_{workflow}"
        out = demo.DRAFTS / f"{key}.out"
        cmd = [sys.executable, "-m", "p2e.cli", "demo", "run", str(path), "--workflow", workflow, "--model", model]
        with self.lock:
            self.cancelled.discard(key)
            self.queue.append((key, cmd, out))
            self._dispatch()
        return key

    def _running(self) -> int:
        return sum(p.poll() is None for p in self.procs.values())

    def _dispatch(self) -> None:
        """Start queued runs while there is a free slot (the caller holds the lock)."""
        limit = max_runs()
        while self.queue and (limit is None or self._running() < limit):
            key, cmd, out = self.queue.pop(0)
            env = {**os.environ, "P2E_WORKSPACE_ROOT": str(run_folder())}
            self.procs[key] = subprocess.Popen(cmd, cwd=RUNS.parent, stdout=out.open("w"), stderr=subprocess.STDOUT,
                                               start_new_session=True, env=env)

    def _dispatch_forever(self) -> None:
        while True:
            time.sleep(2)
            with self.lock:
                self._dispatch()

    def position(self, key: str) -> int | None:
        """1 for the next run to start, None when the run is not waiting."""
        with self.lock:
            return next((i + 1 for i, (k, _, _) in enumerate(self.queue) if k == key), None)

    def was_cancelled(self, key: str) -> bool:
        with self.lock:
            return key in self.cancelled

    def counts(self) -> dict:
        with self.lock:
            return {"running": self._running(), "queued": len(self.queue), "max_running": max_runs()}

    def alive(self, key: str) -> bool | None:
        with self.lock:
            if any(k == key for k, _, _ in self.queue):
                return True
            proc = self.procs.get(key)
        return None if proc is None else proc.poll() is None

    def stop(self, key: str) -> bool:
        with self.lock:
            waiting = [q for q in self.queue if q[0] == key]
            if waiting:
                self.queue.remove(waiting[0])
                self.cancelled.add(key)
                return True
            proc = self.procs.get(key)
        if proc is None or proc.poll() is not None:
            return False
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        return True


JOBS = Jobs()


def valid_key(key: str) -> bool:
    return bool(KEY.match(key) or (RUN_NAME.match(key) and (RUNS / key).is_dir()))


def run_dir_of(key: str) -> Path | None:
    if RUN_NAME.match(key) and (RUNS / key).is_dir():
        return RUNS / key
    hits = sorted(RUNS.glob(f"*_{key}"))
    return hits[-1] if hits else None


def repo_url_in(text: str) -> str | None:
    m = GITHUB.search(text or "")
    return m.group(0).rstrip(".").removesuffix(".git") if m else None


def _finished_runs():
    """(run dir, summary, spec) of every finished A/B/D run on a CORE-Bench task or a demo request."""
    for d in sorted(RUNS.iterdir()):
        if not (d.is_dir() and RUN_NAME.match(d.name) and (d / "summary.json").is_file() and (d / "spec.json").is_file()):
            continue
        try:
            s = json.loads((d / "summary.json").read_text())
            spec = json.loads((d / "spec.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if s.get("workflow") in {w["id"] for w in WORKFLOWS} and s.get("source") in ("corebench", "user"):
            yield d, s, spec


def _runnable(spec: dict) -> bool:
    code = spec.get("code") or {}
    return bool(code.get("repo_url")) or bool(code.get("capsule") and demo.capsule_path(code["capsule"]))


def list_examples(max_wall_s: float = EXAMPLE_MAX_WALL_S) -> list[dict]:
    """Every task (CORE-Bench capsule or demo request) that some run answered in under `max_wall_s` and whose code is
    still at hand, once each, fastest first: what the menu offers to run again from scratch."""
    by_case: dict[str, dict] = {}
    for d, s, spec in _finished_runs():
        ok = s.get("verdict") in ("full", "answered") and not s.get("error") and (s.get("wall_s") or 1e9) <= max_wall_s
        case = s.get("case") or spec.get("id")
        if not ok or not _runnable(spec):
            continue
        e = by_case.setdefault(case, {"case": case, "title": spec.get("title") or case, "source": s["source"],
                                      "code": (spec.get("code") or {}).get("capsule") or (spec.get("code") or {}).get("repo_url"),
                                      "language": spec.get("language", ""), "questions": len(spec.get("questions") or []),
                                      "fastest_s": s["wall_s"], "workflows": set(), "run": d.name})
        e["workflows"].add(s["workflow"])
        if s["wall_s"] < e["fastest_s"]:
            e.update(fastest_s=s["wall_s"], run=d.name)
    return sorted(({**e, "workflows": sorted(e["workflows"])} for e in by_case.values()), key=lambda e: e["fastest_s"])


def example_spec(case: str) -> dict:
    """A listed example as a new user spec (same code and questions, so the run starts from scratch) and the values to
    compare its answers with: CORE-Bench's reference answers for a capsule, the paper's values for a demo request."""
    hit = next((e for e in list_examples() if e["case"] == case), None)
    if hit is None:
        raise ValueError(f"no such example: {case}")
    old = json.loads((RUNS / hit["run"] / "spec.json").read_text())
    questions = old.get("questions") or []
    prompt = (old.get("origin") or {}).get("prompt") if hit["source"] == "user" else \
        "\n".join([old.get("task_prompt", ""), *(f"- {q['text']}" for q in questions)])
    spec = ReproSpec.model_validate({**old, "id": demo.new_spec_id(), "objective": demo.OBJECTIVE,
                                     "origin": {"source": "user", "prompt": prompt, "reference": f"example {case}"}})
    if hit["source"] == "user":
        found = demo.load_paper_values(old["id"])
    else:
        truth = _ground_truth(spec.code.capsule or "")
        found = {"arxiv": None, "source": "corebench", "values": {
            q.id: {"question_id": q.id, "value": truth[q.text], "unit": "", "location": CB_REFERENCE, "quote": ""}
            for q in spec.questions if q.text in truth}}
    demo.save_paper_values(spec.id, found)
    return {"spec": spec.model_dump(mode="json"), "paper": found, "cost": 0.0, "example": hit}


def _reruns(capsule_id: str) -> dict[str, list]:
    """CORE-Bench: question text -> the values of the manual re-runs (what its grader compares with)."""
    for data in (corebench.DATA, corebench.DEV_DATA):
        if data.is_file():
            for entry in corebench.load_tasks(data):
                if entry["capsule_id"] == capsule_id:
                    return {q: [r[q] for r in entry["results"]] for q in entry["results"][0]}
    return {}


def _ground_truth(capsule_id: str) -> dict:
    """CORE-Bench: question text -> the reference answer (the mean of the manual re-runs for numbers)."""
    return {q: (round(statistics.fmean(vs), 10) if isinstance(vs[0], (int, float)) and not isinstance(vs[0], bool)
                else vs[0]) for q, vs in _reruns(capsule_id).items()}


def answers_of(d: Path, spec: dict) -> list[dict] | None:
    """Each question with the run's answer, its evidence and provenance, and the value to compare it with: what the
    paper reports (demo runs, `paper`) or CORE-Bench's reference answer; `correct` where the run was graded."""
    if not (d / "eval.json").is_file():
        return None
    ev = json.loads((d / "eval.json").read_text())["questions"]
    if ev and "answer" in ev[0]:  # a demo run: demo.finish already wrote this shape
        found = demo.load_paper_values(spec.get("id", ""))
        capsule_id = (spec.get("code") or {}).get("capsule") or ""
        reruns = _reruns(capsule_id) if found.get("source") == "corebench" else {}
        for q in ev:
            ref = found["values"].get(q["id"])
            q["reference"] = ref and {"source": found.get("source", "paper"), "arxiv": found.get("arxiv"), **ref}
            q["comparison"] = demo.compare(q["answer"], ref["value"]) if ref else {"status": "unknown"}
            if q["question"] in reruns and q["answer"] is not None:  # a CORE-Bench example: its own grader decides
                graded = corebench.grade_question(capsule_id, q["question"], reruns[q["question"]], q["answer"])
                q["correct"] = graded.correct if graded.scored else None
        return ev
    given = {a["question_id"]: a for a in json.loads((d / "answers.json").read_text())["answers"]} \
        if (d / "answers.json").is_file() else {}
    graded = {q.get("question"): q for q in ev}
    truth = _ground_truth((spec.get("code") or {}).get("capsule") or "")
    out = []
    for q in spec.get("questions") or []:
        a, g = given.get(q["id"], {}), graded.get(q["text"], {})
        out.append({"id": q["id"], "question": q["text"], "answer": a.get("value"), "evidence": a.get("evidence", []),
                    "note": a.get("note", ""), "provenance": g.get("provenance"),
                    "correct": g.get("correct") if g.get("scored", True) else None,
                    "reference": {"source": "corebench", "value": truth[q["text"]], "unit": "",
                                  "location": CB_REFERENCE} if q["text"] in truth else None,
                    "comparison": demo.compare(a.get("value"), truth.get(q["text"])) if q["text"] in truth else {"status": "unknown"}})
    return out


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:  # the last line may be half written
            pass
    return out


def _iso(t: float | None) -> str | None:
    return None if t is None else datetime.fromtimestamp(t).astimezone().isoformat(timespec="milliseconds")


def _short(text, n: int = 160) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {"input": v}
    except (TypeError, json.JSONDecodeError):
        return {"input": raw}


class Graph:
    """Nodes and steps rebuilt from the trace on every poll (traces are small enough; the page polls every second)."""

    def __init__(self, workflow: str, prices: dict):
        self.workflow = workflow
        self.prices = prices
        self.nodes: dict[str, dict] = {}
        self.order: list[str] = []

    def node(self, nid: str, **init) -> dict:
        if nid not in self.nodes:
            self.nodes[nid] = {"id": nid, "parent": None, "kind": "agent", "role": nid, "model": "", "task": "",
                               "status": "pending", "cost": 0.0, "started": None, "ended": None, "steps": [],
                               "summary": "", "_open": {}} | init
            self.order.append(nid)
        return self.nodes[nid]

    def cost(self, usage: list[dict]) -> float:
        p, usd = self.prices, 0.0
        for u in usage or []:
            prompt, cached, written = u.get("prompt", 0), u.get("cached", 0), u.get("written", 0)
            usd += (max(prompt - cached - written, 0) * p.get("in", 0) + cached * p.get("cache_read", 0)
                    + written * p.get("cache_write", 0) + u.get("output", 0) * p.get("out", 0)) / 1e6
        return usd

    def step_open(self, n: dict, name: str, args: dict, t: float) -> None:
        target = args.get(STEP_TARGET.get(name, ""), "")
        step = {"id": f"{n['id']}-{len(n['steps'])}", "name": name, "label": LABELS.get(name, name),
                "target": _short(target, 90) if target else None, "status": "running", "startedAt": _iso(t),
                "args": {k: _short(v, 400) for k, v in args.items()}}
        n["steps"].append(step)
        n["_open"].setdefault(name, []).append(step)

    def step_close(self, n: dict, name: str, t: float, ok: bool, summary: str) -> None:
        queue = n["_open"].get(name) or []
        if not queue:
            return
        step = queue.pop(0)
        step.update(status="done" if ok else "error", finishedAt=_iso(t), summary=_short(summary, 140))


LABELS = {"run_shell": "Run command", "read_file": "Read file", "list_dir": "List directory", "write_file": "Write file",
          "view_image": "View image", "read_log": "Read log", "read_skill": "Read skill", "submit": "Submit",
          "run_task": "Run task", "agent_task": "Start worker"}
TASKS = {"env": "Set up the environment: dependencies, language version, data paths",
         "debug": "Find why a command failed, fix it and run it again",
         "planner": "Decide which commands to run and which question each one answers",
         "answer": "Read the outputs and figures and answer each question",
         "executor": "Run the planned commands and keep their logs"}
ROLE = {"single_agent": ("Single agent", "agent"), "env_agent": ("Environment", "env"), "planner": ("Planner", "planner"),
        "answerer": ("Answerer", "answer"), "executor": ("Executor", "executor"), "runner": ("Orchestrator", "pipeline")}


def build_state(key: str) -> dict:
    """The run as a graph, rebuilt from its trace."""
    workflow = "planner_workers" if key.endswith("planner_workers") else key.rsplit("_", 1)[-1]
    d = run_dir_of(key)
    if (pos := JOBS.position(key)) is not None:
        return {"phase": "queued", "position": pos, **JOBS.counts(), "workflow": workflow, "nodes": [],
                "now": time.time(), "error": None}
    alive = JOBS.alive(key)
    if d is None:
        if JOBS.was_cancelled(key):
            return {"phase": "stopped", "workflow": workflow, "nodes": [], "now": time.time(), "error": None}
        return {"phase": "preparing" if alive else "failed", "workflow": workflow, "nodes": [], "now": time.time(),
                "error": None if alive else _launch_error(key)}
    events = _read_jsonl(d / "trace.jsonl")
    start = next((e for e in events if e.get("agent") == "runner" and e.get("event") == "start"), {})
    workflow = start.get("workflow") or workflow
    profiles = load_profiles()
    prof = profiles.get(start.get("profile") or "")
    prices = {"in": prof.prices.input, "out": prof.prices.output, "cache_read": prof.prices.cache_read,
              "cache_write": prof.prices.cache_write} if prof else {}
    model_name = prof.model if prof else start.get("model", "")
    g = Graph(workflow, prices)
    spec = json.loads((d / "spec.json").read_text()) if (d / "spec.json").is_file() else None  # None: not written yet

    # the root: the agent itself (A), the pipeline (B) or the Planner (D)
    if workflow == "single":
        root = g.node("single_agent", role="Single agent", kind="agent", model=model_name, task=(spec or {}).get("title", ""))
    elif workflow == "fixed":
        root = g.node("runner", role="Orchestrator", kind="pipeline", model="fixed pipeline", task=(spec or {}).get("title", ""),
                      status="running", started=start.get("t"))
    else:
        root = g.node("planner", role="Planner", kind="planner", model=model_name, task=(spec or {}).get("title", ""))
    task_of_agent: dict[str, str] = {}  # D: worker agent name -> runtime task id
    planned: dict[str, dict] = {}  # D: task id -> the Planner's spec of it (purpose, command, objective)

    for e in events:
        agent, ev, t = e.get("agent"), e.get("event"), e.get("t")
        if agent == "runtime":  # D's tasks
            tid = e.get("task_id")
            if ev == "task/added" and tid:
                parent = e.get("lineage") if e.get("lineage") and e.get("lineage") != tid else root["id"]
                plan = planned.get(tid, {})
                n = g.node(f"task:{tid}", parent=f"task:{parent}" if parent != root["id"] else root["id"],
                           kind="worker" if e.get("kind") == "agent" else "run", role=tid, model="worker" if
                           e.get("kind") == "agent" else "runtime", status="pending", started=t,
                           attempt=e.get("attempt", 1),
                           task=_short(plan.get("purpose") or plan.get("objective") or plan.get("command"), 120))
                n["command"] = plan.get("command")
            elif ev in ("task/running", "task/done", "task/failed", "task/cancelled", "task/blocked") and tid \
                    and f"task:{tid}" in g.nodes:
                n = g.nodes[f"task:{tid}"]
                n["status"] = {"task/running": "running", "task/done": "done", "task/failed": "failed",
                               "task/cancelled": "stopped", "task/blocked": "pending"}[ev]
                if ev == "task/running":
                    n["started"] = t
                if ev in ("task/done", "task/failed", "task/cancelled"):
                    n["ended"] = t
                    n["summary"] = _short(e.get("summary") or e.get("signature") or "; ".join(e.get("problems") or []), 200)
                if n["kind"] == "run":  # a run task has no agent: one step for the command itself
                    if ev == "task/running":
                        g.step_open(n, "run_task", {"command": n.get("command") or tid}, t)
                    elif ev in ("task/done", "task/failed"):
                        g.step_close(n, "run_task", t, ev == "task/done", n["summary"] or e.get("log", ""))
            continue
        if agent == "executor" and ev == "run":  # B's executor: one step per command
            n = g.node("executor", parent=root["id"], role="Executor", kind="executor", model="runtime", status="done",
                       task=TASKS["executor"])
            n["started"] = n["started"] or t - e.get("duration_s", 0)
            g.step_open(n, "run_task", {"command": e.get("command", ""), "run_id": e.get("run_id", "")},
                        t - e.get("duration_s", 0))
            n["steps"][-1]["target"] = e.get("run_id")
            g.step_close(n, "run_task", t, e.get("exit_code") == 0, f"exit {e.get('exit_code')} · {e.get('log', '')}")
            n["ended"] = t
            n["status"] = "done" if e.get("exit_code") == 0 else "failed"
            continue
        if agent in (None, "runner", "planner_runtime"):
            continue
        # an LLM agent
        if workflow == "planner_workers" and agent != "planner":
            tid = task_of_agent.get(agent) or next((t_ for t_ in (n_["role"] for n_ in g.nodes.values()
                                                                  if n_["kind"] == "worker") if agent.endswith(f"_{t_}")), None)
            if tid is None:
                n = g.node(agent, parent=root["id"], role=agent, kind="worker", model=model_name)
            else:
                task_of_agent[agent] = tid
                n = g.nodes[f"task:{tid}"]
                n["model"] = model_name
        elif agent in g.nodes:
            n = g.nodes[agent]
        else:
            role, kind = ROLE.get(agent, (agent, "worker"))
            if agent.startswith("debugger"):  # B's debug sessions: debugger_1, debugger_2, ...
                role, kind = f"Debugger {agent.rsplit('_', 1)[-1]}", "debug"
            n = g.node(agent, parent=root["id"], role=role, kind=kind, model=model_name)
        if ev == "start":
            n["status"] = "running"
            n["started"] = n["started"] or t
            n["ended"] = None
            if not n["task"]:
                n["task"] = TASKS.get(n["kind"]) or _short((e.get("task") or "").split("\n")[0], 120)
        elif ev == "response":
            n["cost"] += g.cost(e.get("usage"))
            for call in e.get("tool_calls") or []:
                g.step_open(n, call.get("name", "?"), _args(call.get("input")), t)
        elif ev == "tool_result":
            g.step_close(n, e.get("tool", "?"), t, not e.get("is_error"), e.get("output", ""))
        elif ev == "submit":
            g.step_close(n, "submit", t, True, "submitted")
            out = e.get("output") or {}
            for task in out.get("add_tasks") or [] if isinstance(out, dict) else []:
                planned[task.get("task_id", "")] = task
        elif ev == "end":
            if n["kind"] != "worker" or workflow != "planner_workers":
                n["status"] = "waiting" if agent == "planner" else "done"
            if agent != "planner":  # the Planner sleeps between wakes; its clock runs until the run ends
                n["ended"] = t
        elif ev == "error":
            n["status"] = "failed"
            n["summary"] = _short(e.get("error"), 200)
            n["ended"] = t

    summary = json.loads((d / "summary.json").read_text()) if (d / "summary.json").is_file() else None
    finished = summary is not None
    if finished or alive is False:  # nothing runs any more: close what is still open
        for n in g.nodes.values():
            for s in n["steps"]:
                if s["status"] == "running":
                    s.update(status="denied" if not finished else "done", finishedAt=s["startedAt"])
            if n["status"] in ("running", "waiting", "pending"):
                n["status"] = "done" if finished and not (summary or {}).get("error") else \
                    "failed" if finished else "stopped"
            n["ended"] = n["ended"] or (events[-1]["t"] if events else None)
        if workflow == "fixed":
            root["status"] = "failed" if finished and summary.get("error") else "done" if finished else "stopped"
    elif workflow == "fixed":
        root["status"] = "running"
    answers = answers_of(d, spec) if spec else None
    nodes = []
    for nid in g.order:
        n = g.nodes[nid]
        n.pop("_open", None)
        if workflow == "fixed" and nid == "runner":
            n["cost"] = sum(x["cost"] for x in g.nodes.values() if x is not n)
        nodes.append(n | {"started": _iso(n["started"]), "ended": _iso(n["ended"])})
    total = summary["llm"]["cost_usd"] if finished else sum(n["cost"] for n in g.nodes.values()
                                                             if not (workflow == "fixed" and n["id"] == "runner"))
    phase = "done" if finished and not summary.get("error") else "failed" if finished else \
        "running" if alive or (alive is None and events and time.time() - events[-1]["t"] < 1800) else "stopped"
    return {"phase": phase, "workflow": workflow, "run": d.name, "spec": spec, "model": model_name,
            "profile": start.get("profile"),
            "vendor": vendor_of(prof.model, prof.provider, prof.base_url) if prof else "anthropic", "started": _iso(start.get("t")), "nodes": nodes, "answers": answers,
            "summary": summary, "cost": round(total, 4), "now": time.time(),
            "error": (summary or {}).get("error")}


def draft(body: dict) -> dict:
    """POST /api/draft: {need: repo_url} when there is no code to run (no LLM call), else the spec and the paper's
    values for its questions (saved beside the spec for the comparison, never put in it)."""
    prompt = body["prompt"].strip()
    capsule = body.get("capsule") or None
    repo = None if capsule else repo_url_in(body.get("repo_url") or "") or repo_url_in(prompt)
    if not capsule and not repo:
        return {"need": "repo_url"}
    model = body.get("model") or "haiku55"
    if spend.status()["exhausted"]:
        raise BudgetError(spend.exhausted_message())
    spec, cost = demo.draft_spec(prompt, capsule=capsule, repo_url=repo, model=model)
    try:
        paper, c = demo.paper_values(spec, model=model)
        cost += c
    except Exception as e:  # no paper is not a reason to refuse the task
        paper = {"arxiv": None, "values": {}, "error": f"{type(e).__name__}: {e}"}
    demo.save_paper_values(spec.id, paper)
    return {"spec": spec.model_dump(mode="json"), "paper": paper, "cost": round(cost, 4)}


class BudgetError(Exception):
    """The month's API budget is used up: the page shows this message as it is."""


def _launch_error(key: str) -> str:
    out = demo.DRAFTS / f"{key}.out"
    return out.read_text(errors="replace")[-2000:] if out.is_file() else "the run did not start"


VENDORS = [  # (pattern in the model id or endpoint, vendor), first match wins
    (r"claude|anthropic", "anthropic"), (r"deepseek", "deepseek"), (r"qwen|dashscope", "qwen"), (r"kimi", "kimi"),
    (r"moonshot", "moonshot"), (r"glm|zhipu|bigmodel|z\.ai", "zai"), (r"minimax", "minimax"), (r"mistral|mixtral", "mistral"),
    (r"gemini|google", "google"), (r"grok|x\.ai", "xai"), (r"llama|meta", "meta"), (r"openrouter", "openrouter"),
    (r"groq", "groq"), (r"gpt|openai|o\d", "openai"),
]


def vendor_of(model: str, provider: str, base_url: str | None = None) -> str:
    """Who makes a model, for its logo: from the model id, then the endpoint, then the API it is called through."""
    for text in (model, base_url or ""):
        for pattern, vendor in VENDORS:
            if re.search(pattern, text.lower()):
                return vendor
    return provider


def options() -> dict:
    profiles = load_profiles()
    return {"workflows": WORKFLOWS,
            "models": [{"id": name, "model": p.model, "provider": p.provider,
                        "vendor": vendor_of(p.model, p.provider, p.base_url),
                        "available": bool(os.environ.get(p.api_key_env))} for name, p in profiles.items()],
            "examples": demo.examples(), "budget": spend.status()}


def list_history(limit: int = 50) -> list[dict]:
    """Runs started from the page (demo requests), newest first, with how they ended."""
    out = []
    for d in sorted(RUNS.glob("*_user-*"), reverse=True):
        if not (d.is_dir() and RUN_NAME.match(d.name) and (d / "spec.json").is_file()):
            continue
        try:
            spec = json.loads((d / "spec.json").read_text())
            s = json.loads((d / "summary.json").read_text()) if (d / "summary.json").is_file() else None
        except (OSError, json.JSONDecodeError):
            continue
        start = next((json.loads(l) for l in (d / "trace.jsonl").read_text().splitlines()[:3]
                      if '"event": "start"' in l and '"agent": "runner"' in l), {}) if (d / "trace.jsonl").is_file() else {}
        status = "running" if s is None and JOBS.alive(f"{spec['id']}_{d.name.rsplit(spec['id'] + '_', 1)[-1]}") else \
            "stopped" if s is None else "failed" if s.get("error") else "done"
        out.append({"key": d.name, "title": spec.get("title") or spec.get("id"), "workflow": d.name.rsplit(spec["id"] + "_", 1)[-1],
                    "profile": start.get("profile"), "started": start.get("t"), "status": status,
                    "answered": (s or {}).get("answered"), "questions": len(spec.get("questions") or []),
                    "wall_s": (s or {}).get("wall_s"), "cost": ((s or {}).get("llm") or {}).get("cost_usd")})
        if len(out) >= limit:
            break
    return out


GUARD = access.Guard()
PRESENCE = access.Presence()


class Handler(BaseHTTPRequestHandler):
    server_version = "p2e-demo/0.1"

    def log_message(self, fmt, *args):
        pass

    def _address(self) -> str:
        """The visitor's address: Caddy, in front, puts it last in X-Forwarded-For (and drops what a client sent)."""
        forwarded = (self.headers.get("X-Forwarded-For") or "").split(",")[-1].strip()
        return forwarded or self.client_address[0]

    def _locked(self, parts: list[str]) -> bool:
        """An /api/ call that needs the session cookie and has none (the code check itself is always open)."""
        return parts[:1] == ["api"] and parts[:2] != ["api", "auth"] and not access.valid_session(self.headers.get("Cookie"))

    def _send(self, body: bytes, ctype: str, status: int = 200, headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200, headers: dict | None = None) -> None:
        self._send(json.dumps(obj, default=str, ensure_ascii=False).encode(), "application/json; charset=utf-8", status,
                   headers)

    def do_GET(self):
        url = urlparse(self.path)
        parts = [unquote(p) for p in url.path.split("/") if p]
        try:
            if parts == ["api", "auth"]:
                return self._json(access.status(self.headers.get("Cookie")))
            if self._locked(parts):
                return self._json({"error": "locked"}, 401)
            if parts == ["api", "options"]:
                return self._json(options())
            if parts == ["api", "workdir"]:
                return self._json(workdir_state())
            if parts == ["api", "history"]:
                return self._json({"runs": list_history()})
            if parts == ["api", "examples"]:
                return self._json({"examples": list_examples()})
            if parts[:2] == ["api", "jobs"] and len(parts) == 3 and valid_key(parts[2]):
                return self._json(build_state(parts[2]))
            if parts[:2] == ["api", "jobs"] and len(parts) == 4 and parts[3] == "file" and valid_key(parts[2]):
                return self._file(parts[2], parse_qs(url.query).get("path", [""])[0])
            if parts[:1] == ["api"]:
                return self._json({"error": "not found"}, 404)
            return self._static(parts)
        except Exception as e:  # keep the page alive on a bad run directory
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def _file(self, key: str, rel: str):
        d = run_dir_of(key)
        if d is None or not rel or rel.startswith("/") or ".." in Path(rel).parts:
            return self._json({"error": "not allowed"}, 403)
        root = (d / "workspace").resolve()
        f = (root / rel).resolve()
        # resolve() follows symlinks: one the run made (to .env, say) must not take the request outside its workspace
        if not f.is_relative_to(root) or not f.is_file() or f.stat().st_size > 20_000_000:
            return self._json({"error": "no such file"}, 404)
        ctype = mimetypes.guess_type(f.name)[0] or "text/plain"
        if not (ctype.startswith("image/") or ctype.startswith("text/") or ctype == "application/pdf"):
            return self._json({"error": "not allowed"}, 403)
        return self._send(f.read_bytes(), ctype)

    def _static(self, parts: list[str]):
        rel = "/".join(parts) or "index.html"
        f = (DIST / rel).resolve()
        if DIST not in f.parents or not f.is_file():
            f = DIST / "index.html"
        if not f.is_file():
            return self._send(b"frontend not built: cd Base/demo-web && npm install && npm run build",
                              "text/plain; charset=utf-8", 503)
        return self._send(f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")

    def do_POST(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        try:
            if parts == ["api", "auth"]:
                name = access.clean_name(body.get("name") or "")
                status, out = access.check_code(GUARD, self._address(), body.get("code") or "", name)
                if status != 200 or not access.required():
                    return self._json(out, status)
                cookie, age = access.new_session(name)
                out = {**out, "name": name}
                return self._json(out, 200, {"Set-Cookie": f"{access.COOKIE}={cookie}; Max-Age={age}; Path=/; HttpOnly; "
                                                            f"SameSite=Lax{'; Secure' if access.required() else ''}"})
            if parts == ["api", "logout"]:
                return self._json({"ok": True}, 200, {"Set-Cookie": f"{access.COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"})
            if self._locked(parts):
                return self._json({"error": "locked"}, 401)
            if parts == ["api", "presence"]:
                me = access.session_name(self.headers.get("Cookie")) if access.required() else None
                PRESENCE.ping(str(body.get("id") or self._address()), me)
                people = PRESENCE.people()
                return self._json({"online": len(people), "names": [n for n in people if n], "me": me, **JOBS.counts()})
            if parts == ["api", "draft"]:
                if not (body.get("prompt") or "").strip():
                    return self._json({"error": "Say what to reproduce first"}, 400)
                try:
                    return self._json(draft(body))
                except BudgetError as e:
                    return self._json({"error": str(e), "budget": spend.status()}, 402)
            if parts == ["api", "workdir"]:
                try:
                    return self._json(set_run_folder(body.get("path") or ""))
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
            if parts == ["api", "workdir", "choose"]:
                try:
                    return self._json(choose_run_folder())
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
            if parts == ["api", "example"]:
                return self._json(example_spec(body.get("case") or ""))
            if parts == ["api", "start"]:
                spec = ReproSpec.model_validate(body.get("spec") or {})
                workflow, model = body.get("workflow"), body.get("model") or "haiku55"
                if spec.origin.source != "user" or workflow not in {w["id"] for w in WORKFLOWS}:
                    return self._json({"error": "unknown workflow or not a user spec"}, 400)
                prof = load_profiles().get(model)
                if prof is None or not os.environ.get(prof.api_key_env):
                    return self._json({"error": f"No API key is set for model {model}"}, 400)
                if spend.status()["exhausted"]:
                    return self._json({"error": spend.exhausted_message(), "budget": spend.status()}, 402)
                return self._json({"key": JOBS.start(spec, workflow, model)})
            if parts[:2] == ["api", "jobs"] and len(parts) == 4 and parts[3] == "stop" and KEY.match(parts[2]):
                return self._json({"stopped": JOBS.stop(parts[2])})
            return self._json({"error": "not found"}, 404)
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def serve(host: str = "127.0.0.1", port: int = 8780) -> int:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"p2e demo at http://{host}:{port}/  (runs in {RUNS}; Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
