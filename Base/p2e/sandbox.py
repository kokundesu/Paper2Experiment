"""Execution sandbox: every command a workflow runs goes through here.

Local backend: a per-run workspace directory, a wall-clock timeout that kills
the whole process group, a scrubbed environment (no API keys), a command guard
that blocks access to the hidden ground truth, and a full log file per command.
The agent's shell can still write into logs/, so the sandbox keeps an in-memory manifest of the sha256 of every
log it wrote; the runner saves it after all agents are done and the evaluator accepts only logs that match it.
It isolates by convention, not by the kernel; a Docker backend can implement
the same `run` interface later.

The workspace lives outside the project tree (P2E_WORKSPACE_ROOT, default ~/Library/Caches/p2e/workspaces) and the
environment stops uv and git from searching parent directories: a real run's `uv run` inside runs/<run>/workspace/repo
found this project's pyproject.toml, wrote uv.lock into the project root and re-synced the project's .venv, and git
run anywhere under runs/ resolved to this project's repository.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .models import secret_env_names


def describe_machine() -> str:
    """The machine the agents are told they run on. It is the real one: the demo server is a Linux x86_64 box, and
    telling its agents they were on an Apple Silicon Mac made them reach for macOS habits (BSD sed) and assume
    wheels that exist on Linux did not."""
    import platform
    arch = platform.machine()
    if sys.platform == "darwin":
        return "Apple Silicon Mac" if arch == "arm64" else f"Intel Mac ({arch})"
    return f"{platform.system()} {arch} server with {os.cpu_count()} CPU cores"


MACHINE = describe_machine()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Shared across runs so repeated `uv pip install` of the same wheels is fast. A parallel batch gives every job
# slot its own (P2E_UV_CACHE), since a job clears its cache after each capsule.
UV_CACHE = Path(os.environ.get("P2E_UV_CACHE", PROJECT_ROOT / "runs" / ".uv-cache")).expanduser()


def workspace_root() -> Path:
    """Where run workspaces live: outside the project, so tools that walk up the tree never reach it."""
    if env := os.environ.get("P2E_WORKSPACE_ROOT"):
        return Path(env).expanduser()
    cache = Path.home() / ("Library/Caches" if sys.platform == "darwin" else ".cache")
    return cache / "p2e" / "workspaces"

# micromamba (user directory, not the system): its package cache is shared, the environments agents create with
# `micromamba create -p ./.renv ...` live in the workspace and are deleted with it
MAMBA_ROOT = Path(os.environ.get("P2E_MAMBA_ROOT", Path.home() / ".p2e-mamba")).expanduser()
# per job slot in a parallel batch, like UV_CACHE; unset: micromamba's own pkgs/ under MAMBA_ROOT
MAMBA_PKGS = Path(os.environ["P2E_MAMBA_PKGS"]).expanduser() if os.environ.get("P2E_MAMBA_PKGS") else None

# On a shared server (the public demo), commands run as a separate, unprivileged user (P2E_RUN_AS), through
# `sudo -n -u <user>`: the code being reproduced can then read neither the project (its .env holds the API keys)
# nor this process's memory or environment, whatever it does. The command guard below only catches honest mistakes;
# this is the boundary. The workspace root, caches and P2E_RUN_HOME must be in a group both users share, setgid and
# group-writable (deploy/server-setup.sh sets this up); commands run with umask 002 so this process can still read
# and clean up what they write. Unset (the default, a researcher's own machine): commands run as this user.
RUN_AS = os.environ.get("P2E_RUN_AS") or None
RUN_HOME = os.environ.get("P2E_RUN_HOME") or None


def as_runner(argv: list[str], env: dict[str, str] | None = None) -> list[str]:
    """`argv` as the command user would run it: unchanged locally, through sudo with exactly `env` on a server."""
    if not RUN_AS:
        return argv
    pairs = [f"{k}={v}" for k, v in (env or {"PATH": "/usr/local/bin:/usr/bin:/bin"}).items()]
    return ["sudo", "-n", "-u", RUN_AS, "--", "/usr/bin/env", "-i", *pairs, *argv]


_BLOCKED = [
    (re.compile(r"case\.ya?ml"), "ground-truth files are off limits"),
    (re.compile(re.escape(str(PROJECT_ROOT / "benchmark"))), "the benchmark directory is off limits"),
    (re.compile(r"(^|[\s/'\"=<])\.env(?![\w.])"), "the project's .env holds API keys and is off limits"),
    (re.compile(r"(^|[\s;&|])sudo\s"), "sudo is not allowed"),
    (re.compile(r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|~)(\s|$)"), "refusing to delete / or ~"),
]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class CommandResult:
    command: str
    exit_code: int | None  # None means killed by timeout
    duration_s: float
    output: str
    log_path: Path

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def tail(self, max_chars: int = 6000) -> str:
        """Output trimmed for an LLM context: keep the head and the tail."""
        if len(self.output) <= max_chars:
            return self.output
        head = max_chars // 4
        return (self.output[:head] + f"\n... [{len(self.output) - max_chars} chars omitted] ...\n"
                + self.output[-(max_chars - head):])

    def summary(self, max_chars: int = 6000) -> str:
        status = "TIMEOUT" if self.exit_code is None else f"exit_code={self.exit_code}"
        return f"[{status}, {self.duration_s:.1f}s, full log: {self.log_path.name}]\n{self.tail(max_chars)}"


class Sandbox:
    def __init__(self, run_dir: Path, default_timeout_s: int = 600, root: Path | None = None):
        self.run_dir = run_dir
        # <root>/<run name>/workspace is the agent's working tree; <root>/<run name>/logs links back to run_dir/logs,
        # so `../logs/<file>` still works from the workspace while the logs (the evidence) stay in the project.
        self.home = (root or workspace_root()).resolve() / run_dir.name
        if self.home.is_relative_to(PROJECT_ROOT.resolve()):
            raise ValueError(f"workspace root must be outside the project ({PROJECT_ROOT}), got {self.home}")
        self.workspace = self.home / "workspace"
        self.log_dir = run_dir / "logs"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        for link, target in ((self.home / "logs", self.log_dir), (run_dir / "workspace", self.workspace)):
            if not link.is_symlink():  # run_dir/workspace: so people (not agents) can still find it
                link.symlink_to(target.resolve(), target_is_directory=True)
        UV_CACHE.mkdir(parents=True, exist_ok=True)
        self.default_timeout_s = default_timeout_s
        self._n = len(list(self.log_dir.glob("cmd_*.log")))
        self._lock = threading.Lock()
        self._live: set[int] = set()  # sessions of the commands running right now
        # log file name -> sha256 of what the sandbox wrote; in memory only, since on disk the agent could edit it
        self.manifest: dict[str, str] = {}
        # workspace files an agent wrote directly (write_file), not through a command: their content is the agent's
        self.authored: set[str] = set()

    def _env(self) -> dict[str, str]:
        secrets = secret_env_names()  # key variables named in models.yaml, e.g. a custom endpoint's
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("ANTHROPIC", "OPENAI", "CONDA", "VIRTUAL_ENV", "PYTHON"))
               and not k.endswith("_API_KEY") and k not in secrets}
        env.update({
            "HOME": RUN_HOME or os.environ.get("HOME", str(self.workspace)),
            "UV_CACHE_DIR": str(UV_CACHE),
            "PYTHONUNBUFFERED": "1",
            "MPLBACKEND": "Agg",
            "TF_CPP_MIN_LOG_LEVEL": "2",
            # never discover a project, pyproject.toml or uv.toml above the command's directory
            "UV_NO_PROJECT": "1",
            "UV_NO_CONFIG": "1",
            # git may find the repository the agent cloned, but never one above the run's own directory
            "GIT_CEILING_DIRECTORIES": str(self.home),
        })
        if (MAMBA_ROOT / "bin" / "micromamba").is_file():  # R (and other non-Python stacks) through micromamba
            env["MAMBA_ROOT_PREFIX"] = str(MAMBA_ROOT)
            env["PATH"] = f"{MAMBA_ROOT / 'bin'}:{env.get('PATH', '')}"
            if MAMBA_PKGS:
                env["CONDA_PKGS_DIRS"] = str(MAMBA_PKGS)
        return env

    def check(self, command: str) -> str | None:
        """Return a reason if the command is blocked, else None."""
        for pattern, reason in _BLOCKED:
            if pattern.search(command):
                return reason
        return None

    def resolve(self, rel: str) -> Path:
        """Map a workspace-relative path to an absolute one, refusing escapes."""
        path = (self.workspace / rel).resolve()
        if not path.is_relative_to(self.workspace.resolve()):
            raise PermissionError(f"path escapes the workspace: {rel}")
        return path

    def run(self, command: str, workdir: str = ".", timeout_s: int | None = None, tag: str = "cmd") -> CommandResult:
        with self._lock:  # parallel workers share one sandbox; log numbers must stay unique
            self._n += 1
            log_path = self.log_dir / f"cmd_{self._n:03d}_{tag}.log"
        if reason := self.check(command):
            self._write_log(log_path, f"$ {command}\nBLOCKED: {reason}\n")
            return CommandResult(command, 126, 0.0, f"BLOCKED: {reason}", log_path)

        # A bad workdir is a failed command with a log, not an exception: a planned run whose directory is missing
        # (the env agent reported repo/, the repo was elsewhere) once crashed the whole multi-agent workflow.
        try:
            cwd = self.resolve(workdir)
        except PermissionError as e:
            cwd, problem = None, str(e)
        else:
            problem = None if cwd.is_dir() else f"workdir does not exist or is not a directory: {workdir}"
        if problem:
            self._write_log(log_path, f"$ cd {workdir} && {command}\n# exit=2 duration=0.0s\nERROR: {problem}\n")
            return CommandResult(command, 2, 0.0, f"ERROR: {problem}", log_path)
        timeout_s = timeout_s or self.default_timeout_s
        start = time.monotonic()
        env = self._env()
        argv = ["/bin/bash", "-c", f"umask 002\n{command}" if RUN_AS else command]
        proc = subprocess.Popen(
            as_runner(argv, env), cwd=cwd, env=None if RUN_AS else env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            errors="replace", start_new_session=True,
        )
        with self._lock:
            self._live.add(proc.pid)
        try:
            output, _ = proc.communicate(timeout=timeout_s)
            exit_code: int | None = proc.returncode
        except subprocess.TimeoutExpired:
            self._kill(proc.pid)
            output, _ = proc.communicate()
            output += f"\n[killed after {timeout_s}s timeout]"
            exit_code = None
        finally:
            with self._lock:
                self._live.discard(proc.pid)
        duration = time.monotonic() - start
        self._write_log(log_path, f"$ cd {workdir} && {command}\n# exit={exit_code} duration={duration:.1f}s\n{output}")
        return CommandResult(command, exit_code, duration, output, log_path)

    def kill_live(self) -> None:
        """Kill every command running right now (the run is being stopped)."""
        with self._lock:
            live = list(self._live)
        for session in live:
            self._kill(session)

    @staticmethod
    def _kill(session: int) -> None:
        """Kill everything the command started: its session (start_new_session made the command's process its leader).
        Processes of the command user can only be signalled as that user, so on a server pkill runs through sudo."""
        if RUN_AS:
            subprocess.run(as_runner(["pkill", "-KILL", "-s", str(session)]), capture_output=True, timeout=30)
        try:
            os.killpg(session, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def _write_log(self, path: Path, text: str) -> None:
        path.write_text(text)
        self.manifest[path.name] = file_sha256(path)

    def discard_workspace(self) -> None:
        """Delete the workspace (cloned repo, venv, data: often over 1 GB per run) once the run is scored.
        logs/ stays in run_dir, and logs/ plus the run's json files are all the evaluator reads."""
        remove_workspace(self.home, self.run_dir)


def remove_workspace(home: Path, run_dir: Path) -> None:
    """Delete a run's workspace folder `home` and the run directory's link to it; the run directory stays."""
    if RUN_AS:  # what the command user wrote with its own permissions, it removes itself
        subprocess.run(as_runner(["rm", "-rf", "--", str(home)]), capture_output=True, timeout=600)
    shutil.rmtree(home, ignore_errors=True)  # the logs link inside is removed, not followed
    link = run_dir / "workspace"
    if link.is_symlink():
        link.unlink()
