"""Capsules (a paper's code + data as one archive): safe extraction, CORE-Bench Hard clean-up, snapshot, provenance.

Hard clean-up follows the CORE-Bench paper's definition of the Hard level: the agent gets the README, the code and
the data (checkpoints and training data included), but not the results, the reproduction instructions, the
environment spec (environment/, the Dockerfile) or the run scripts. The HAL harness's CoreBenchHard additionally drops
training data, caches and checkpoints (to keep uploads small); that made tasks whose prompt evaluates a shipped
checkpoint or reads a training file impossible (development round 1, 2026-10-18), so we do not follow it there.
Python bytecode caches (__pycache__) are dropped as build artefacts.

The CORE-Bench follow-up (arXiv 2606.26158) found 20 of 45 Hard tasks answerable from files that were already in the
capsule. So before the agent starts, every file of the cleaned workspace is hashed (`snapshot`); after the run,
`provenance` checks where each answer can be found: in output the run produced (a new or changed file, or a sandbox
log) or only in files that were there from the start and never changed (a shortcut).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import tarfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

# binary files that look like stored results: the agent cannot be checked against them, so they are reported
_RESULT_NAME = re.compile(r"result|record|output|pred|score|metric|log", re.IGNORECASE)
_OPAQUE_EXT = (".npz", ".npy", ".pkl", ".pickle", ".pt", ".pth", ".rds", ".rdata", ".rda", ".h5", ".hdf5", ".mat",
               ".joblib", ".parquet", ".xlsx", ".png")  # PDFs have a text layer that is searched
# Figures are often PDFs: their text layer is searched too, so an answer read off a produced figure counts.
MAX_PDF_BYTES = 50_000_000
MAX_PDF_PAGES = 50
MAX_TEXT_BYTES = 20_000_000  # larger files are not searched for answers
# Installed environments and caches: an install writes thousands of files, and some number or name in them matches
# almost any answer (a pilot run "found" an AUC of 0.957 in scipy's test data). They are never searched.
ENV_PARTS = {".venv", "venv", "site-packages", "dist-packages", "node_modules", "__pycache__", ".git", ".cache",
             ".ipynb_checkpoints", ".mypy_cache", ".pytest_cache", ".local", "renv", ".renv"}
# Text the agent writes out itself: the argument of echo/printf, or a quoted string inside print(...)/write(...).
_ECHO = re.compile(r"\b(?:echo|printf)\b([^;|&\n]*)")
_CALL = re.compile(r"(?:\bprint\s*\(|\.write\s*\(|\bjson\.dumps?\s*\()([^\n]*)")
_QUOTED = re.compile(r"(?:'[^'\n]*'|\"[^\"\n]*\")")
_NUM = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")


def hard_excluded(rel: str) -> str | None:
    """Why the Hard level removes this capsule-relative path, or None if the agent gets it."""
    p = PurePosixPath(rel)
    parts, name = p.parts, p.name.lower()
    if "results" in parts[:-1]:
        return "results directory"
    if rel == "REPRODUCING.md" or rel.endswith("/REPRODUCING.md"):
        return "reproduction instructions"
    if parts[:1] == ("environment",):
        return "environment spec"
    if rel in ("code/run.sh", "code/run") or rel.endswith(("/code/run.sh", "/code/run")):
        return "run script"
    if "__pycache__" in parts[:-1]:
        return "__pycache__"
    return None


@dataclass
class Extraction:
    kept: list[str] = field(default_factory=list)
    removed: dict[str, str] = field(default_factory=dict)  # path -> reason
    refused: dict[str, str] = field(default_factory=dict)  # archive members not extracted, and why


def extract(archive: Path, dest: Path, hard: bool = True) -> Extraction:
    """Extract a capsule archive into `dest`, dropping its single top-level folder (capsule-XXXXXXX/).

    Only regular files and directories are extracted; links, devices and paths that would leave `dest` are refused.
    With `hard`, the Hard-level clean-up is applied."""
    out = Extraction()
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        tops = {PurePosixPath(m.name).parts[0] for m in members if PurePosixPath(m.name).parts}
        # one shared top-level folder (capsule-XXXXXXX/), whether or not the archive lists it as a directory
        strip = len(tops) == 1 and all(len(PurePosixPath(m.name).parts) > 1 or m.isdir() for m in members)
        for m in members:
            parts = PurePosixPath(m.name).parts[1 if strip else 0:]
            if not parts:
                continue
            rel = "/".join(parts)
            if m.name.startswith("/") or ".." in parts:
                out.refused[m.name] = "path leaves the capsule"
                continue
            if not (m.isfile() or m.isdir()):
                out.refused[rel] = "not a regular file or directory"
                continue
            if m.isdir():
                continue
            if hard and (why := hard_excluded(rel)):
                out.removed[rel] = why
                continue
            target = (dest / rel).resolve()
            if not target.is_relative_to(root):
                out.refused[rel] = "path leaves the capsule"
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(m) as src:
                target.write_bytes(src.read())
            out.kept.append(rel)
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(root: Path) -> dict[str, dict]:
    """relative path -> {sha256, size} for every regular file under `root` (symlinks are not followed)."""
    snap = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            snap[p.relative_to(root).as_posix()] = {"sha256": _sha256(p), "size": p.stat().st_size}
    return snap


def opaque_results(snap: dict[str, dict]) -> list[str]:
    """Pre-existing binary files whose names suggest stored results: answers read from them cannot be detected."""
    return [rel for rel in snap
            if rel.lower().endswith(_OPAQUE_EXT) and _RESULT_NAME.search(rel) and not rel.startswith("code/")]


def in_environment(rel: str) -> bool:
    return any(part in ENV_PARTS or part.endswith(".dist-info") for part in PurePosixPath(rel).parts)


def typed_lines(text: str, answer) -> bool:
    """True if the agent wrote the answer out itself: in the argument of echo/printf, or in a quoted string inside
    print(...)/write(...). Naming a package (`pip install catboost`) or a variable (`print(catboost.__version__)`)
    is not typing the answer."""
    if isinstance(answer, list):
        return bool(answer) and any(typed_lines(text, a) for a in answer)
    for line in text.splitlines():
        if any(answer_in(answer, m.group(1)) for m in _ECHO.finditer(line)):
            return True
        for m in _CALL.finditer(line):
            if any(answer_in(answer, q[1:-1]) for q in _QUOTED.findall(m.group(1))):
                return True
    return False


def changed_files(root: Path, before: dict[str, dict]) -> tuple[list[str], list[str]]:
    """(produced, untouched): files new or changed since `before`, and files of `before` still unchanged."""
    after = snapshot(root)
    produced = [rel for rel, meta in after.items() if before.get(rel, {}).get("sha256") != meta["sha256"]]
    untouched = [rel for rel, meta in before.items() if after.get(rel, {}).get("sha256") == meta["sha256"]]
    return produced, untouched


def _pdf_text(path: Path) -> str | None:
    """The text layer of a PDF (a figure's axis labels, legends and tick values); None if it has none."""
    try:
        if path.stat().st_size > MAX_PDF_BYTES:
            return None
        from pypdf import PdfReader
        pages = PdfReader(path).pages[:MAX_PDF_PAGES]
        return "\n".join(pg.extract_text() or "" for pg in pages) or None
    except Exception:  # a damaged or encrypted PDF is just not searchable
        return None


def _read_text(path: Path) -> str | None:
    if path.suffix.lower() == ".pdf":
        return _pdf_text(path)
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        return None  # binary
    return data.decode("utf-8", errors="replace")


def _decimals(text: str) -> int:
    mantissa, _, exp = text.lower().partition("e")
    places = len(mantissa.partition(".")[2])
    return places - int(exp) if exp else places


def number_in(value: float, text: str) -> bool:
    """True if `value` is printed in `text`, possibly with more digits (the answer is a rounding of it) or as a
    percentage of it (x100 or /100)."""
    for tok in _NUM.findall(text):
        try:
            n = float(tok)
        except ValueError:
            continue
        for scaled in (n, n * 100, n / 100):
            if math.isclose(scaled, value, rel_tol=1e-9, abs_tol=0):
                return True
    places = _decimals(repr(float(value)) if not float(value).is_integer() else str(int(value)))
    half = 0.5 * 10 ** -places
    for tok in _NUM.findall(text):
        try:
            n = float(tok)
        except ValueError:
            continue
        if _decimals(tok) > places and any(abs(s - value) <= half for s in (n, n * 100, n / 100)):
            return True
    return False


def answer_in(answer, text: str) -> bool:
    """True if every part of an answer (number, string, boolean, list) appears in `text`."""
    if isinstance(answer, list):
        return bool(answer) and all(answer_in(a, text) for a in answer)
    if isinstance(answer, bool):
        return str(answer).lower() in text.lower()
    if isinstance(answer, (int, float)):
        return number_in(float(answer), text)
    s = str(answer).strip()
    if not s:
        return False
    try:
        return number_in(float(s.rstrip("%")), text)
    except ValueError:
        return re.search(rf"(?<![\w]){re.escape(s.lower())}(?![\w])", text.lower()) is not None


@dataclass
class Provenance:
    status: str  # typed | produced | preexisting_only | not_found
    produced_in: list[str] = field(default_factory=list)
    preexisting_in: list[str] = field(default_factory=list)
    typed_in: list[str] = field(default_factory=list)
    weak: bool = False  # the answer is short enough to appear by chance (e.g. "yes", "blue", 1)


def split_log(text: str) -> tuple[str, str]:
    """(command, output) of a sandbox log: '$ cd <dir> && <command>' then '# exit=... duration=...', then output."""
    if not text.startswith("$ "):
        return "", text
    for marker in ("\n# exit=", "\nBLOCKED:", "\nERROR:"):
        if (i := text.find(marker)) >= 0:
            rest = text[i + 1:]
            return text[:i], rest.partition("\n")[2] if marker == "\n# exit=" else rest
    return text, ""


def provenance(answers: dict, workspace: Path, before: dict[str, dict], logs: list[Path],
               exclude: set[str] | frozenset = frozenset(), authored: set[str] | frozenset = frozenset()
               ) -> dict[str, Provenance]:
    """Where each answer can be found.

    produced: in the output of a command that did not type it, or in a file that is new or changed since `before`
    (minus `exclude`, e.g. the answer file, and minus `authored`). Files do not count once a command typed the answer
    (it may have written them), and nothing counts once a script the agent wrote (`authored`) prints it.
    typed: otherwise found only where the agent wrote it out itself (typed_lines). preexisting_only: only in files the
    capsule shipped with, unchanged. Installed environments (ENV_PARTS) are never searched."""
    produced, untouched = changed_files(workspace, before)
    produced = [rel for rel in produced if not in_environment(rel)]
    untouched = [rel for rel in untouched if not in_environment(rel)]
    log_texts = {}  # name -> (command, output)
    for p in logs:
        if (t := _read_text(p)) is not None:
            log_texts[f"logs/{p.name}"] = split_log(t)
    authored_texts = {rel: t for rel in authored if (t := _read_text(workspace / rel)) is not None}
    file_texts = {rel: t for rel in produced if rel not in exclude and rel not in authored
                  and (t := _read_text(workspace / rel)) is not None}
    old_texts = {rel: t for rel in untouched if (t := _read_text(workspace / rel)) is not None}
    out = {}
    for q, a in answers.items():
        echoed = [name for name, (cmd, _) in log_texts.items() if typed_lines(cmd, a)]
        scripted = [rel for rel, t in authored_texts.items() if typed_lines(t, a)]
        typed = [f"{n} (command)" for n in echoed] + scripted
        if scripted:  # a script the agent wrote prints the answer: no run output can be told apart from it
            new = []
        else:  # a command that echoes the answer proves nothing, and neither does any file (it may have written it)
            new = [n for n, (_, outp) in log_texts.items() if n not in echoed and answer_in(a, outp)]
            if not echoed:
                new += [rel for rel, t in file_texts.items() if answer_in(a, t)]
        old = [name for name, t in old_texts.items() if answer_in(a, t)]
        status = "produced" if new else "typed" if typed else "preexisting_only" if old else "not_found"
        short = str(a).strip() if not isinstance(a, list) else ""
        weak = isinstance(a, bool) or (isinstance(a, (int, float)) and abs(a) < 100 and float(a).is_integer()) or (
            0 < len(short) <= 4 and not _NUM.fullmatch(short))
        out[q] = Provenance(status, new, old, typed, weak)
    return out


def viewed_figures(viewed: list[str], workspace: Path, before: dict[str, dict]) -> list[str]:
    """Images the agent looked at (view_image) that this run made: new since `before`, or changed. A figure question's
    answer is read off such an image, not found in any text, so it counts as produced when the text search finds
    nothing. Once the workspace is deleted (rescoring old runs) only "new" can be checked, from the trace alone."""
    live = workspace.is_dir()
    out = []
    for rel in dict.fromkeys(r.removeprefix("./") for r in viewed):
        path = workspace / rel
        if in_environment(rel) or rel.startswith("logs/") or (live and not path.is_file()):
            continue
        if rel not in before or (live and _sha256(path) != before[rel].get("sha256")):
            out.append(rel)
    return out


def save(path: Path, obj) -> None:
    path.write_text(json.dumps(obj if not hasattr(obj, "__dataclass_fields__") else asdict(obj), indent=2))


# ---------------------------------------------------------------- repositories the agent cloned itself

# A command segment that prints a file's content instead of running code: a reader program applied to the file,
# a Python snippet that opens it, or nbconvert without --execute.
_READERS = {"cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "sed", "awk", "jq", "column",
            "strings", "nl", "xxd", "bat", "tac"}
_OPENS = re.compile(r"open\s*\(|read_csv|read_json|read_table|json\.load|np\.load|loadtxt|genfromtxt|\.read_text\s*\(")


def _reading_segments(command: str) -> list[str]:
    out = []
    for seg in re.split(r"\|\||&&|;|\||\n", command):
        words = [w for w in seg.strip().split() if not re.match(r"^\w+=", w)]  # skip VAR=value prefixes
        if not words:
            continue
        program = PurePosixPath(words[0].strip("'\"")).name
        if program in _READERS or _OPENS.search(seg) or ("nbconvert" in seg and "--execute" not in seg):
            out.append(seg)
    return out


def shipped_files(workspace: Path, max_depth: int = 3) -> dict[str, Path]:
    """Files of every git repository in the workspace that are tracked and unchanged since the checkout:
    workspace-relative path -> absolute path. These came with the repository, not from a run."""
    import subprocess
    from .sandbox import as_runner
    out: dict[str, Path] = {}
    if not workspace.is_dir():
        return out
    repos = [p.parent for d in range(max_depth + 1) for p in workspace.glob("/".join(["*"] * d + [".git"]))
             if not in_environment(p.relative_to(workspace).as_posix().removesuffix("/.git"))]
    for repo in repos:
        try:
            # as the command user on a server: the repository (its .git/config included) is theirs, and a hostile
            # config (core.fsmonitor, diff.external) must not run anything with this process's rights
            tracked = subprocess.run(as_runner(["git", "-C", str(repo), "ls-files", "-z"]), capture_output=True,
                                     text=True, timeout=60).stdout.split("\0")
            changed = subprocess.run(as_runner(["git", "-C", str(repo), "diff", "--name-only", "-z", "HEAD"]),
                                     capture_output=True, text=True, timeout=60).stdout.split("\0")
        except (OSError, subprocess.SubprocessError):
            continue
        for rel in set(filter(None, tracked)) - set(changed):
            path = repo / rel
            if path.is_file() and not path.is_symlink():
                out[path.relative_to(workspace).as_posix()] = path
    return out


def shortcut_read(log_text: str, value, shipped: dict[str, Path]) -> list[str]:
    """Shipped files that a segment of this log's command prints (cat, grep, open(...), nbconvert without
    --execute...) and that contain `value`: the log then shows the repository's stored result, not a run. A file a
    program merely runs (`python train.py | tail`) is not read this way."""
    command, _ = split_log(log_text)
    segments = _reading_segments(command)
    hits = []
    for rel, path in shipped.items():
        name = PurePosixPath(rel).name
        pattern = rf"(?<![\w.-]){re.escape(name)}(?![\w-])"
        if name and any(re.search(pattern, seg) for seg in segments):
            text = _read_text(path)
            if text is not None and answer_in(value, text):
                hits.append(rel)
    return hits


SHIPPED_DIR = "shipped_reads"  # in the run directory: copies of shipped files that some log's command printed
SHIPPED_COPY_LIMIT = 5_000_000


def save_shipped_reads(run_dir: Path, workspace: Path, logs: list[Path]) -> dict[str, list[str]]:
    """Before the workspace is discarded: copy every shipped file that a log's command reads (cat, grep, open(...)
    ...) into run_dir/shipped_reads/, and record which log read which file, so the shortcut check can be re-run
    without the workspace."""
    shipped = shipped_files(workspace)
    reads: dict[str, list[str]] = {}
    for log in logs:
        segments = _reading_segments(split_log(_read_text(log) or "")[0])
        hits = [rel for rel in shipped if segments and any(
            re.search(rf"(?<![\w.-]){re.escape(PurePosixPath(rel).name)}(?![\w-])", seg) for seg in segments)]
        if hits:
            reads[f"logs/{log.name}"] = hits
    for rel in sorted({r for hits in reads.values() for r in hits}):
        src = shipped[rel]
        if src.stat().st_size <= SHIPPED_COPY_LIMIT:
            dst = run_dir / SHIPPED_DIR / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
    save(run_dir / f"{SHIPPED_DIR}.json", reads)
    return reads


def saved_shipped(run_dir: Path) -> dict[str, Path]:
    """The shipped files save_shipped_reads kept: workspace-relative path -> copy."""
    root = run_dir / SHIPPED_DIR
    return {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()} if root.is_dir() else {}
