"""Standard-library HTTP server for the web UI: static index.html plus a small JSON API over runs/.

    GET  /                                  the frontend
    GET  /api/cases                         benchmark cases, workflows, whether an API key is set
    GET  /api/runs                          one row per run (running ones first in the UI)
    GET  /api/runs/<run>?since=<n>          stages, claims and the event feed from event n on
    GET  /api/runs/<run>/file/<name>        a role's JSON output or logs/<name>
    GET  /api/compare?version=V2&case=gcn   single vs multi aggregates, per version / case / claim
    POST /api/start   {case, workflow, repeats}   launch `p2e run` as a subprocess
    POST /api/stop    {pid}                       terminate a launched run (its whole process group)
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..runner import BENCHMARK, RUNS
from . import data
from ..versions import discover

HERE = Path(__file__).resolve().parent
# deterministic plus every version folder (SingleAgent, Multiagent/*), as `p2e run` sees them
WORKFLOWS = ("deterministic", *discover())


class Launcher:
    """Runs started from the UI. Knowing the process lets the run list say running / aborted exactly."""

    def __init__(self):
        self.procs: list[dict] = []
        self.lock = threading.Lock()

    def start(self, case: str, workflow: str, repeats: int) -> dict:
        RUNS.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = RUNS / f"launch_{stamp}_{case}_{workflow}.out"
        cmd = [sys.executable, "-m", "p2e.cli", "run", "--case", case, "--workflow", workflow, "--repeats", str(repeats)]
        proc = subprocess.Popen(cmd, cwd=RUNS.parent, stdout=out.open("w"), stderr=subprocess.STDOUT,
                                start_new_session=True)
        rec = {"pid": proc.pid, "case": case, "workflow": workflow, "repeats": repeats, "started": time.time(),
               "out": str(out.relative_to(RUNS.parent)), "proc": proc}
        with self.lock:
            self.procs.append(rec)
        return self.public(rec)

    def stop(self, pid: int) -> bool:
        with self.lock:
            rec = next((r for r in self.procs if r["pid"] == pid), None)
        if rec is None or rec["proc"].poll() is not None:
            return False
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        return True

    def public(self, rec: dict) -> dict:
        code = rec["proc"].poll()
        return {k: v for k, v in rec.items() if k != "proc"} | {"alive": code is None, "exit_code": code}

    def listing(self) -> list[dict]:
        with self.lock:
            return [self.public(r) for r in self.procs]

    def alive_map(self) -> dict[str, bool]:
        """run dir name -> alive, for runs that match a launched process (same case/workflow, started after it)."""
        out: dict[str, bool] = {}
        with self.lock:
            procs = list(self.procs)
        for d in RUNS.iterdir():
            if not d.is_dir() or (d / "summary.json").exists():
                continue
            parts = d.name.split("_")
            if len(parts) < 3:
                continue
            try:
                started = time.mktime(time.strptime(parts[0], "%Y%m%d-%H%M%S"))
            except ValueError:
                continue
            for rec in procs:
                if parts[1] == rec["case"] and parts[2] == rec["workflow"] and started >= rec["started"] - 2:
                    out[d.name] = rec["proc"].poll() is None
        return out


LAUNCHER = Launcher()


class Handler(BaseHTTPRequestHandler):
    server_version = "p2e-web/0.1"

    def log_message(self, fmt, *args):  # quiet: one line per poll would flood the terminal
        pass

    # ------------------------------------------------------------ helpers

    def _json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, body: str, ctype: str = "text/plain; charset=utf-8", status: int = 200) -> None:
        raw = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _run_dir(self, name: str) -> Path | None:
        if "/" in name or name.startswith(".") or not name:
            return None
        d = RUNS / name
        return d if d.is_dir() else None

    # ------------------------------------------------------------ routes

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        parts = [p for p in url.path.split("/") if p]
        try:
            if not parts:
                return self._text((HERE / "index.html").read_text(), "text/html; charset=utf-8")
            if parts[:2] == ["api", "cases"]:
                cases = sorted(d.name for d in BENCHMARK.iterdir() if (d / "task.yaml").exists())
                return self._json({"cases": cases, "workflows": list(WORKFLOWS),
                                   "api_key": bool(os.environ.get("OPENAI_API_KEY")), "launches": LAUNCHER.listing()})
            if parts[:2] == ["api", "runs"] and len(parts) == 2:
                return self._json({"runs": data.list_runs(LAUNCHER.alive_map()), "launches": LAUNCHER.listing(),
                                   "now": time.time()})
            if parts[:2] == ["api", "runs"] and len(parts) == 3:
                d = self._run_dir(parts[2])
                if d is None:
                    return self._json({"error": "no such run"}, 404)
                since = int(q.get("since", "0") or 0)
                return self._json(data.run_detail(d, since, LAUNCHER.alive_map().get(d.name)) | {"now": time.time()})
            if parts[:2] == ["api", "runs"] and len(parts) >= 5 and parts[3] == "file":
                d = self._run_dir(parts[2])
                rel = "/".join(parts[4:])
                if d is None or ".." in rel or not (rel.endswith(".json") or rel.startswith("logs/")):
                    return self._json({"error": "not allowed"}, 403)
                f = d / rel
                if not f.is_file():
                    return self._json({"error": "no such file"}, 404)
                return self._text(f.read_text(errors="replace")[:400_000],
                                  "application/json; charset=utf-8" if rel.endswith(".json") else "text/plain; charset=utf-8")
            if parts[:2] == ["api", "compare"]:
                return self._json(data.compare(q.get("version") or None, q.get("case") or None))
            return self._json({"error": "not found"}, 404)
        except Exception as e:  # keep the UI alive on a bad run directory
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        try:
            if parts == ["api", "start"]:
                case, wf = body.get("case"), body.get("workflow")
                cases = {d.name for d in BENCHMARK.iterdir() if (d / "task.yaml").exists()}
                if case not in cases or wf not in WORKFLOWS:
                    return self._json({"error": "unknown case or workflow"}, 400)
                if wf != "deterministic" and not os.environ.get("OPENAI_API_KEY"):
                    return self._json({"error": "OPENAI_API_KEY is not set (put it in .env and restart p2e serve)"}, 400)
                repeats = max(1, min(int(body.get("repeats") or 1), 10))
                return self._json(LAUNCHER.start(case, wf, repeats))
            if parts == ["api", "stop"]:
                ok = LAUNCHER.stop(int(body.get("pid") or 0))
                return self._json({"stopped": ok}, 200 if ok else 404)
            return self._json({"error": "not found"}, 404)
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> int:
    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"p2e web UI at {url}  (runs in {RUNS}; Ctrl+C to stop)", flush=True)
    if open_browser:
        import webbrowser
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
