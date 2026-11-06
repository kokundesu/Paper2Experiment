"""Skill library: procedures for recurring situations in reproduction work, shared by every workflow version and
upgraded round by round from what the runs went through.

A skill is `skills/<name>/SKILL.md` at the repository root: YAML front matter (name, description = when to use it,
version, evidence = the runs it was written or last revised from) and a body (the procedure: when, steps, checks).
Every agent of A, B and D gets the same `read_skill` tool (p2e.llm.sandbox_tools): its description carries the index
(name + when to use), the body is read on demand. So the versions differ only in how they use the library, never in
what it holds. `P2E_SKILLS=off` drops the tool (the no-skills ablation).

Upgrade loop (`p2e skills update <run dirs>`), one round after each batch of development runs:

    digest   per run, deterministically: verdict, each question's answer and whether it passed (never the expected
             value), failed commands with the end of their log, which skills the agents read, the agents' notes
    curate   an LLM (by default another model than the agents') reads the digests, the current library, its changelog
             and per-skill usage statistics across library versions, and proposes edits: create, revise, retire
    check    deterministically: valid names and sizes, and no benchmark identifier or answer in any skill (task ids,
             titles, paper ids, repository names, ground-truth values): skills hold procedures, never answers
    apply    the old library goes to skills/history/v<N>/, the edits are written, the version goes up and
             skills/CHANGELOG.md records every edit with its rationale and evidence runs

Each run records the library version it used (summary.json `skills`), so the next round sees whether an edit helped
and can revise or retire it: that is what makes the upgrade recursive. Runs on a test split may only feed nothing:
`digest` refuses them, and `freeze` locks the library before any test run.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from .sandbox import PROJECT_ROOT

ROOT = Path(os.environ.get("P2E_SKILLS_DIR", PROJECT_ROOT.parent / "skills")).resolve()
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,40}$")
MAX_BODY_LINES = 80
MAX_DESCRIPTION = 300
MAX_EDITS = 6
DIGEST_CHARS = 9000  # per run
CURATION_CHARS = 140_000  # all digests together: stays under the 100K-token price tier
LOG_TAIL_LINES = 25


def enabled() -> bool:
    return os.environ.get("P2E_SKILLS", "on").lower() not in ("off", "0", "false", "no")


@dataclass
class Skill:
    name: str
    description: str
    body: str
    version: int = 1
    evidence: list[str] = field(default_factory=list)

    def text(self) -> str:
        head = {"name": self.name, "description": self.description, "version": self.version,
                "evidence": self.evidence}
        return f"---\n{yaml.safe_dump(head, sort_keys=False, allow_unicode=True)}---\n\n{self.body.strip()}\n"


def parse(text: str) -> Skill:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML front matter")
    head, body = text[4:].split("\n---", 1)
    meta = yaml.safe_load(head) or {}
    return Skill(name=meta["name"], description=meta["description"], body=body.strip(),
                 version=int(meta.get("version", 1)), evidence=list(meta.get("evidence") or []))


def load(root: Path | None = None) -> list[Skill]:
    root = root or ROOT
    return [parse(p.read_text()) for p in sorted(root.glob("*/SKILL.md"))]


def state(root: Path | None = None) -> dict:
    p = (root or ROOT) / "library.yaml"
    return yaml.safe_load(p.read_text()) if p.is_file() else {"version": 0, "frozen": None}


def library_hash(root: Path | None = None) -> str:
    h = hashlib.sha256()
    for p in sorted((root or ROOT).glob("*/SKILL.md")):
        h.update(p.parent.name.encode() + p.read_bytes())
    return h.hexdigest()[:16]


def library_version(root: Path | None = None) -> dict:
    """What a run records: the library version and the hash of its skill files (None when skills are off)."""
    if not enabled():
        return {"version": None, "hash": None, "enabled": False}
    return {"version": state(root).get("version", 0), "hash": library_hash(root), "enabled": True}


def index(skills: list[Skill]) -> str:
    return "\n".join(f"- {s.name}: {s.description}" for s in skills)


def read_tool(root: Path | None = None):
    """The read_skill tool every agent gets, or None when the library is empty or switched off."""
    from .llm import Tool

    if not enabled():
        return None
    skills = {s.name: s for s in load(root)}
    if not skills:
        return None

    def read_skill(a: dict) -> str:
        s = skills.get(str(a.get("name", "")).strip())
        if s is None:
            return f"No skill named {a.get('name')!r}. Skills: {', '.join(skills)}"
        return f"# {s.name} (v{s.version})\n\n{s.body}"

    return Tool("read_skill",
                "Read a skill: a procedure for a recurring situation in reproduction work, written from earlier runs. "
                "When your next step matches a skill's 'when to use', read it first and follow it unless the task "
                "says otherwise. Skills:\n" + index(list(skills.values())),
                {"type": "object", "properties": {"name": {"type": "string", "description": "Skill name"}},
                 "required": ["name"]}, read_skill)


# ---------------------------------------------------------------- leakage check


def _answer_values(entries: list[dict]) -> set[str]:
    out = set()
    for e in entries:
        for run in e.get("results", []):
            for v in run.values():
                for x in (v if isinstance(v, list) else [v]):
                    s = str(x).strip()
                    if _significant(s) >= 3 or (not _is_number(s) and len(s) >= 5 and not _common_word(s)):
                        out.add(s.lower())
    return out


_WORDS: set[str] | None = None


def _common_word(s: str) -> bool:
    """A single dictionary word ("search", "positive") is no identifier; phrases and coined names are."""
    global _WORDS
    if _WORDS is None:
        d = Path("/usr/share/dict/words")
        _WORDS = {w.strip().lower() for w in d.read_text().splitlines()} if d.is_file() else set()
    return " " not in s.strip() and s.strip().lower() in _WORDS


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _significant(s: str) -> int:
    if not _is_number(s):
        return 0
    digits = re.sub(r"[^0-9]", "", s.split("e")[0].split("E")[0]).lstrip("0")
    return len(digits)


def forbidden_terms() -> dict[str, set[str]]:
    """Identifiers and answers of every benchmark task this project holds; none may appear in a skill."""
    from .runner import BENCHMARK

    ids, titles, answers = set(), set(), set()
    for data in BENCHMARK.glob("corebench*/core_*.json"):
        entries = json.loads(data.read_text())
        for e in entries:
            ids.add(e["capsule_id"].lower())
            ids.add(e["capsule_id"].removeprefix("capsule-"))
            titles.add(e["capsule_title"].lower())
        answers |= _answer_values(entries)
    v4 = BENCHMARK / "v4" / "dataset.yaml"
    if v4.is_file():
        for e in yaml.safe_load(v4.read_text()).get("papers", yaml.safe_load(v4.read_text())):
            if not isinstance(e, dict):
                continue
            ids.add(str(e.get("id", "")).lower())
            if e.get("title"):
                titles.add(str(e["title"]).lower())
            if e.get("repo"):
                ids.add(e["repo"].rstrip("/").split("/tree/")[0].split("/")[-1].lower())
    for case in BENCHMARK.glob("*/case.yaml"):
        ids.add(case.parent.name.lower())
        doc = yaml.safe_load(case.read_text()) or {}
        for c in doc.get("claims", []):
            for k in ("value", "paper_value"):
                if c.get(k) is not None and _significant(str(c[k])) >= 3:
                    answers.add(str(c[k]).lower())
    for vals in BENCHMARK.glob("v4/*/reference_values.yaml"):
        for v in (yaml.safe_load(vals.read_text()) or {}).get("values", {}).values():
            answers |= {str(x).lower() for x in v if _significant(str(x)) >= 3}
    # An identifier that is also an ordinary English word names nothing in a skill's text: a curator note on
    # fitting mixed models was rejected for one (2026-10-19). Titles and answers are still checked.
    words = _english_words()
    ids = {i for i in ids if len(i) >= 3 and not _is_word(i, words)}
    return {"identifier": ids, "title": titles, "answer": answers}


def _is_word(token: str, words: set[str]) -> bool:
    """In the dictionary as given or after one common inflection (the macOS word list has stems only)."""
    return token in words or any(token.endswith(s) and token[:-len(s)] in words for s in ("s", "es", "ed", "ing"))


def _english_words() -> set[str]:
    words = Path("/usr/share/dict/words")
    return {w.strip().lower() for w in words.read_text().splitlines()} if words.is_file() else set()


def check(skill: Skill, terms: dict[str, set[str]] | None = None) -> list[str]:
    problems = []
    if not NAME_RE.match(skill.name):
        problems.append(f"{skill.name}: name must be lowercase words joined by '-'")
    if not skill.description or len(skill.description) > MAX_DESCRIPTION:
        problems.append(f"{skill.name}: description must be 1-{MAX_DESCRIPTION} characters")
    if len(skill.body.splitlines()) > MAX_BODY_LINES:
        problems.append(f"{skill.name}: body over {MAX_BODY_LINES} lines")
    terms = terms if terms is not None else forbidden_terms()
    text = f"{skill.name}\n{skill.description}\n{skill.body}".lower()
    tokens = set(re.findall(r"[a-z0-9][a-z0-9._+-]*[a-z0-9]|[a-z0-9]", text))
    for kind in ("identifier", "answer"):
        hits = sorted(t for t in terms[kind] if (t in tokens if re.fullmatch(r"[\w.+-]+", t) else t in text))
        if hits:
            problems.append(f"{skill.name}: contains benchmark {kind}s {hits[:5]}")
    if hits := sorted(t for t in terms["title"] if t in text):
        problems.append(f"{skill.name}: contains task titles {hits[:3]}")
    return problems


# ---------------------------------------------------------------- run digests


def _events(run_dir: Path) -> list[dict]:
    p = run_dir / "trace.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.is_file() else []


def skills_read(events: list[dict]) -> list[str]:
    out = []
    for e in events:
        if e.get("event") == "response":
            for c in e.get("tool_calls") or []:
                if c.get("name") == "read_skill":
                    try:
                        out.append(json.loads(c["input"]).get("name", "?") if isinstance(c["input"], str)
                                   else c["input"].get("name", "?"))
                    except (ValueError, AttributeError):
                        out.append("?")
    return out


def _mask_numbers(text: str) -> str:
    return re.sub(r"\d+\.\d+|\d{3,}", "#", text)


def _failed_commands(run_dir: Path, events: list[dict], limit: int = 6) -> list[str]:
    out = []
    for e in events:
        if e.get("event") in ("run", "command") and e.get("exit_code") not in (0, None):
            log = e.get("log") or e.get("log_path")
            tail = ""
            if log and (run_dir / log).is_file():
                lines = (run_dir / log).read_text(errors="replace").splitlines()
                tail = "\n".join(lines[-LOG_TAIL_LINES:])
            out.append(f"$ {e.get('command', '')[:300]}  (exit {e.get('exit_code')})\n{tail}")
    return out[-limit:]


def _shell_failures(run_dir: Path, limit: int = 6) -> list[str]:
    """Failed shell commands from the sandbox logs (every version runs commands through the sandbox)."""
    out = []
    for log in sorted((run_dir / "logs").glob("cmd_*.log")):
        text = log.read_text(errors="replace")
        m = re.search(r"# exit=(-?\d+)", text)
        if m and m.group(1) != "0":
            lines = text.splitlines()
            out.append(f"{log.name}: {lines[0][:300] if lines else ''} (exit {m.group(1)})\n"
                       + "\n".join(lines[-LOG_TAIL_LINES:]))
    return out[-limit:]


def is_test_run(summary: dict) -> bool:
    case = str(summary.get("case", ""))
    try:
        from . import v4
        if case.startswith(v4.PREFIX) and case.removeprefix(v4.PREFIX) in v4.members("test"):
            return True
    except Exception:  # noqa: BLE001 - no v4 split file: nothing is a v4 test case
        pass
    return summary.get("split") == "test"


def digest(run_dir: Path) -> str:
    """What the curator may see of one run. Never the expected values: only answers, pass/fail and failures."""
    summary = json.loads((run_dir / "summary.json").read_text())
    if is_test_run(summary):
        raise ValueError(f"{run_dir.name}: a test-split run cannot feed the skill library")
    events = _events(run_dir)
    lines = [f"## run {run_dir.name}",
             f"workflow={summary.get('workflow')} verdict={summary.get('verdict')} "
             f"skills={summary.get('skills', {}).get('version') if isinstance(summary.get('skills'), dict) else None} "
             f"cost=${summary.get('llm', {}).get('cost_usd')} wall={summary.get('wall_s')}s"]
    if summary.get("error"):
        lines.append(f"error: {summary['error'][:500]}")
    ev = json.loads((run_dir / "eval.json").read_text()) if (run_dir / "eval.json").is_file() else {}
    report = {}
    if (run_dir / "report.json").is_file():
        try:
            report = json.loads((run_dir / "report.json").read_text())
        except ValueError:
            pass
    for q in ev.get("questions", []):  # spec runs (CORE-Bench); `detail` holds the expected value: never shown
        prov = (q.get("provenance") or {}).get("status")
        given = json.dumps(report[q["question"]])[:120] if q.get("question") in report else "(no answer)"
        lines.append(f"- question: {q.get('question')!r} answered={given} passed={q.get('correct')} "
                     f"scored={q.get('scored')} provenance={prov}")
    for c in ev.get("claims", []):  # paper runs
        lines.append(f"- claim {c.get('claim_id')}: passed={c.get('within_tolerance')} "
                     f"evidence_ok={c.get('evidence_ok')} reason={_mask_numbers(str(c.get('reason', '')))[:300]}")
    if read := skills_read(events):
        lines.append(f"skills read: {', '.join(read)}")
    notes = [e.get("text", "") for e in events if e.get("event") == "response" and e.get("text")][-3:]
    for name in ("answers.json", "metrics.json"):
        if (run_dir / name).is_file():
            notes.append(str(json.loads((run_dir / name).read_text()).get("notes", "")))
    if notes := [n for n in notes if n.strip()]:
        lines.append("agent notes (last):\n" + "\n".join(_mask_numbers(n)[:600] for n in notes))
    fails = _failed_commands(run_dir, events) + _shell_failures(run_dir)
    if fails:
        lines.append("failed commands (end of log):\n" + "\n---\n".join(fails[-8:]))
    return "\n".join(lines)[:DIGEST_CHARS]


def usage_stats(run_dirs: list[Path]) -> dict:
    """Per skill and library version: how many runs read it and their verdicts (what the curator weighs edits by)."""
    stats: dict = {}
    for d in run_dirs:
        try:
            summary = json.loads((d / "summary.json").read_text())
        except (OSError, ValueError):
            continue
        ver = (summary.get("skills") or {}).get("version")
        for name in set(skills_read(_events(d))) or {"(no skill read)"}:
            row = stats.setdefault(name, {}).setdefault(str(ver), {"runs": 0, "full": 0})
            row["runs"] += 1
            row["full"] += summary.get("verdict") == "full"
    return stats


# ---------------------------------------------------------------- curation


class SkillEdit(BaseModel):
    action: Literal["create", "revise", "retire"]
    name: str = Field(description="lowercase-words-joined-by-dashes")
    description: str = Field("", description="When to use it, one sentence (create/revise)")
    body: str = Field("", description="The procedure (create/revise): when, steps, checks. Generic: no task, paper, "
                                      "repository, dataset or answer")
    rationale: str = Field(description="What in the runs calls for this edit")
    evidence: list[str] = Field(description="Run directory names the edit is based on")


class Curation(BaseModel):
    assessment: str = Field(description="What the runs went through, and whether earlier skill edits helped")
    edits: list[SkillEdit] = Field(default_factory=list, max_length=MAX_EDITS)


CURATOR = f"""You maintain the skill library of a system that reproduces research code (sets up old code, runs it,
answers questions about its results). Skills are short procedures for recurring situations, read by every agent of
every workflow version. After each batch of development runs you get: a digest of each run (what passed, what failed,
failed commands with the end of their log, which skills were read, the agents' notes), the current library with its
changelog, and per-skill usage statistics across library versions.

Propose at most {MAX_EDITS} edits that would have prevented the failures you see, or that remove guidance that misled:
- create: a recurring situation no skill covers (it appeared in more than one run, or it cost a whole run).
- revise: a skill that was read but did not prevent the failure, or is incomplete or wrong. Keep what works.
- retire: a skill that is never useful or that misleads.
Rules:
- Generic only. A skill must help on tasks it has never seen: never name a task, paper, capsule, repository,
  dataset or a value from any result. Name kinds of situations ("a notebook that needs a kernel", "a library that
  changed a default"), not instances. Skills holding identifiers or answers are rejected automatically.
- Procedures, not answers: when to use, ordered steps, the check that confirms each step worked.
- Base every edit on the digests and cite the runs. Do not edit for a failure the runs do not show.
- Look at the statistics: if runs that read a skill still fail the same way, revise it; prefer fewer, better skills.
- Body at most {MAX_BODY_LINES} lines; description one sentence saying when to use the skill.
Submit a Curation."""


def changelog(root: Path | None = None) -> str:
    p = (root or ROOT) / "CHANGELOG.md"
    return p.read_text() if p.is_file() else "(empty)"


def curation_prompt(run_dirs: list[Path], root: Path | None = None, all_runs: list[Path] | None = None) -> str:
    skills = load(root)
    digests, used = [], 0
    for d in run_dirs:
        text = digest(d)
        if used + len(text) > CURATION_CHARS:
            digests.append(f"(... {len(run_dirs) - len(digests)} more runs left out: size limit)")
            break
        digests.append(text)
        used += len(text)
    lib = "\n\n".join(f"### {s.name} (v{s.version})\nwhen: {s.description}\n{s.body}" for s in skills) or "(empty)"
    return (f"Library version {state(root).get('version', 0)}:\n\n{lib}\n\nChangelog:\n{changelog(root)[-6000:]}\n\n"
            f"Usage statistics (skill -> library version -> runs that read it, of which full):\n"
            f"{json.dumps(usage_stats(all_runs or run_dirs), indent=1)}\n\nRun digests:\n\n" + "\n\n".join(digests))


def curate(run_dirs: list[Path], model: str = "sonnet55", root: Path | None = None,
           out_dir: Path | None = None) -> tuple[Curation, Path]:
    """Ask the curator for edits; returns them (not applied) and the directory holding its trace."""
    from .llm import Agent, Budget, Trace
    from .models import get_profile
    from .runner import RUNS

    out = out_dir or RUNS / "skills" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    prompt = curation_prompt(run_dirs, root)
    (out / "prompt.md").write_text(prompt)
    agent = Agent("skill_curator", CURATOR, [], Curation, Trace(out / "trace.jsonl"),
                  Budget(profile=get_profile(model), limit_usd=2.0), max_turns=4, max_cost_usd=2.0)
    cur: Curation = agent.run(prompt)
    (out / "curation.json").write_text(cur.model_dump_json(indent=1))
    return cur, out


def apply(cur: Curation, root: Path | None = None, terms: dict[str, set[str]] | None = None) -> tuple[int, list[str]]:
    """Check every edit, then write them all as one new library version. Returns (new version, problems); nothing
    is written when any edit has a problem."""
    root = root or ROOT
    st = state(root)
    if st.get("frozen"):
        return st.get("version", 0), [f"library is frozen at version {st['version']} ({st['frozen']})"]
    current = {s.name: s for s in load(root)}
    terms = terms if terms is not None else forbidden_terms()
    new, problems = dict(current), []
    for e in cur.edits:
        if e.action == "retire":
            if e.name not in new:
                problems.append(f"retire {e.name}: no such skill")
            new.pop(e.name, None)
            continue
        if e.action == "create" and e.name in current:
            problems.append(f"create {e.name}: exists already (use revise)")
            continue
        if e.action == "revise" and e.name not in current:
            problems.append(f"revise {e.name}: no such skill (use create)")
            continue
        old = current.get(e.name)
        s = Skill(e.name, e.description or (old.description if old else ""), e.body or (old.body if old else ""),
                  version=(old.version + 1) if old else 1, evidence=e.evidence)
        problems += check(s, terms)
        new[e.name] = s
    if problems:
        return st.get("version", 0), problems
    version = st.get("version", 0) + 1
    if current:
        snap = root / "history" / f"v{st.get('version', 0)}"
        snap.mkdir(parents=True, exist_ok=True)
        for s in current.values():
            (snap / f"{s.name}.md").write_text(s.text())
    for name in current:
        if name not in new:
            shutil.rmtree(root / name)
    for s in new.values():
        (root / s.name).mkdir(parents=True, exist_ok=True)
        (root / s.name / "SKILL.md").write_text(s.text())
    entry = [f"## v{version} ({datetime.now():%Y-%m-%d %H:%M})", "", cur.assessment.strip(), ""]
    entry += [f"- {e.action} `{e.name}`: {e.rationale.strip()} (runs: {', '.join(e.evidence) or '-'})"
              for e in cur.edits]
    log = root / "CHANGELOG.md"
    log.write_text((log.read_text() if log.is_file() else "# Skill library changelog\n") + "\n" + "\n".join(entry) + "\n")
    (root / "library.yaml").write_text(yaml.safe_dump({"version": version, "frozen": None,
                                                       "hash": library_hash(root)}, sort_keys=False))
    return version, []


def freeze(reason: str, root: Path | None = None) -> dict:
    root = root or ROOT
    st = state(root) | {"frozen": f"{datetime.now():%Y-%m-%d %H:%M} {reason}", "hash": library_hash(root)}
    (root / "library.yaml").write_text(yaml.safe_dump(st, sort_keys=False))
    return st


def require_frozen(root: Path | None = None) -> None:
    """Test-split runs use a frozen library whose files are unchanged since the freeze."""
    if not enabled():
        return
    st = state(root)
    if not st.get("frozen"):
        raise RuntimeError("the skill library is not frozen: run `p2e skills freeze` before any test-split run")
    if st.get("hash") != library_hash(root):
        raise RuntimeError("skill files changed after the freeze")
