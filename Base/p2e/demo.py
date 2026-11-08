"""User-prompt runs for the demo UI: the user's request becomes a ReproSpec (origin.source="user"), one of the
workflow versions runs it, and its answers are reported as they are. There is no ground truth, so nothing is graded.

    draft_spec(prompt, capsule=..., repo_url=...)   one LLM call: the request -> objective, task and questions
    paper_values(spec)                               what the paper reports for each question (a second LLM call on
                                                     the arXiv paper the prompt or the README links); kept beside the
                                                     spec, never in it, so the agents cannot copy it
    compare(answer, paper)                           the run's answer against the paper's value
    new_run(spec, workflow, model)                   the run context (capsules get the same Hard-level workspace)
    finish(ctx, ...)                                 what corebench.finish does for a user spec: answers, no score

`p2e demo run <spec.json> --workflow single --model haiku55` runs one spec (the server launches it as a subprocess).
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Literal, Union

import yaml
from pydantic import BaseModel, Field

from . import capsule, corebench, skills
from .llm import Agent, Budget, Trace
from .models import get_profile
from .runner import RUNS, RunContext
from .sandbox import Sandbox
from .schemas import Task
from .spec import Answers, CodeInput, Question, ReproSpec, SpecOrigin, brief

DRAFTS = RUNS / "demo_drafts"
ARXIV = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.I)
MATCH_REL, CLOSE_REL = 0.02, 0.10  # relative gap to the paper's value: within 2% matches, within 10% is close
ABS_TOL = 1e-8  # floating-point noise around a reference of 0 (numpy.isclose's atol)
OBJECTIVE = "Reproduce what the user asked for: run the code and answer the questions from the output."


class DraftQuestion(BaseModel):
    text: str = Field(description="One quantity or fact the run must produce, phrased as a question")
    answer_type: Literal["number", "string", "bool", "list", "any"] = "any"
    locator: str = Field("program output", description="Where the user expects it, e.g. 'Table 2' or 'program output'")


class Draft(BaseModel):
    title: str = Field(description="A short title for the task")
    task_prompt: str = Field(description="What to run, in the user's terms: scripts, notebooks, settings")
    language: str = Field("", description="Python, R, ... if the request or the code makes it clear")
    questions: list[DraftQuestion] = Field(min_length=1, max_length=8)


DRAFT_SYSTEM = """You turn a user's reproduction request into a task for an agent team that will run research code.
Keep to what the user asked for: do not add experiments. Each question names one value or fact the run must
produce (a metric, a table cell, what a figure shows), so that the answer can be read off the run's output. If the
user names figures, keep the word "fig" in that question. Never ask for the paper's reported values, a comparison
with the paper, or whether the reproduction succeeded: the comparison with the paper is done afterwards, outside the
run, and the agents must not see the paper's numbers. Do not write the paper's values into the task either. Write in
English even if the request is in another language. Submit the draft."""


class PaperValue(BaseModel):
    question_id: str
    value: Union[float, str, None] = Field(description="The value exactly as the paper prints it (a number without "
                                                       "its unit, or a name); null if the paper does not report it")
    unit: str = ""
    location: str = Field("", description="Where: e.g. 'Table 2, row ResNet-50, top-1 column'")
    quote: str = Field("", description="The table row or sentence it comes from, copied")


class PaperValues(BaseModel):
    values: list[PaperValue]


EXTRACT_SYSTEM = """You read a research paper and, for each question of a reproduction task, find the value the paper
itself reports for it. `value` is only the value exactly as printed: a number without its unit, or a short name; never
a sentence. `location` is only where it is, e.g. "Table 2, row ResNet-50, top-1 column"; `quote` is the row or sentence
copied. If the user's request states the paper's value, use that. If the paper does not report a value for a question,
give null: do not compute or guess one. Submit one entry per question."""


def find_arxiv(prompt: str, repo_url: str | None) -> str | None:
    """The paper's arXiv id: a link in the request, else the first arXiv link in the repository's README."""
    if m := ARXIV.search(prompt):
        return m.group(1)
    if repo_url:
        from .intent import repo_info
        readme, _, _ = repo_info(repo_url)
        if m := ARXIV.search(readme):
            return m.group(1)
    return None


def paper_values(spec: ReproSpec, model: str = "haiku55", cap_usd: float = 0.5) -> tuple[dict, float]:
    """What the paper reports for each question, by question id, with the paper's arXiv id; and the cost.
    Returns {"arxiv": None, "values": {}} when no paper can be found (a capsule, or no arXiv link anywhere)."""
    from .intent import paper_text, select_pages
    arxiv = find_arxiv(spec.origin.prompt, spec.code.repo_url)
    if arxiv is None:
        return {"arxiv": None, "values": {}}, 0.0
    text = select_pages(paper_text(arxiv, DRAFTS / "papers"), spec.origin.prompt + " " + spec.task_prompt)
    questions = "\n".join(f"- {q.id}: {q.text}" for q in spec.questions)
    trace = Trace(DRAFTS / f"{spec.id}.extract.jsonl")
    agent = Agent("paper_reader", EXTRACT_SYSTEM, [], PaperValues, trace,
                  Budget(profile=get_profile(model), limit_usd=cap_usd), max_turns=3, max_cost_usd=cap_usd)
    out: PaperValues = agent.run(f"The user's request:\n{spec.origin.prompt}\n\nQuestions:\n{questions}\n\n"
                                 f"The paper (arXiv {arxiv}):\n{text}")
    known = {q.id for q in spec.questions}
    values = {v.question_id: v.model_dump() for v in out.values if v.question_id in known and v.value is not None
              and not (isinstance(v.value, str) and len(v.value) > 60)}  # a sentence is not a reported value
    return {"arxiv": arxiv, "values": values}, agent.budget.spent_usd


def save_paper_values(spec_id: str, found: dict) -> None:
    DRAFTS.mkdir(parents=True, exist_ok=True)
    (DRAFTS / f"{spec_id}.paper.json").write_text(json.dumps(found, indent=1, ensure_ascii=False))


def load_paper_values(spec_id: str) -> dict:
    f = DRAFTS / f"{spec_id}.paper.json"
    return json.loads(f.read_text()) if f.is_file() and f.stat().st_size else {"arxiv": None, "values": {}}


def _number(x) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x) if math.isfinite(x) else None
    m = re.search(r"[-+−]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", str(x).replace(",", ""))
    return float(m.group(0).replace("−", "-")) if m else None


def compare(answer, paper) -> dict:
    """match / close / mismatch / unknown, with the gap for numbers."""
    if answer is None or paper is None:
        return {"status": "unknown"}
    a, p = _number(answer), _number(paper)
    if a is not None and p is not None and not isinstance(answer, list):
        diff = a - p
        rel = abs(diff) / abs(p) if p else (0.0 if a == 0 else math.inf)
        status = "match" if rel <= MATCH_REL or abs(diff) <= ABS_TOL else "close" if rel <= CLOSE_REL else "mismatch"
        return {"status": status, "diff": diff, "rel": rel if math.isfinite(rel) else None}
    norm = lambda v: re.sub(r"\s+", " ", json.dumps(v, ensure_ascii=False) if isinstance(v, list) else str(v)).strip().lower()
    return {"status": "match" if norm(answer) == norm(paper) else "mismatch"}


_ID_LOCK = threading.Lock()  # the server drafts on request threads: two in the same second must not share an id


def new_spec_id() -> str:
    """user-<timestamp>, one second later than any spec already drafted in the same second."""
    t = time.time()
    with _ID_LOCK:
        while True:
            sid = "user-" + datetime.fromtimestamp(t).strftime("%Y%m%d-%H%M%S")
            if not any(DRAFTS.glob(f"{sid}*")) and not any(RUNS.glob(f"*_{sid}_*")):
                DRAFTS.mkdir(parents=True, exist_ok=True)
                (DRAFTS / f"{sid}.paper.json").touch()  # claims the id
                return sid
            t += 1


def capsule_path(capsule_id: str) -> Path | None:
    """The archive of a downloaded capsule, test or dev split."""
    for root in (corebench.CAPSULES, corebench.DEV_CAPSULES):
        if (p := root / f"{capsule_id}.tar.gz").is_file():
            return p
    return None


def examples() -> list[dict]:
    """Downloaded capsules with an exported spec: the UI offers them as starting points (title, task, questions)."""
    out = []
    for tasks in (corebench.TASKS, corebench.DEV_TASKS):
        for f in sorted(tasks.glob("cb-*/spec.yaml")):
            spec = yaml.safe_load(f.read_text())
            cid = spec["code"]["capsule"]
            if capsule_path(cid) is None:
                continue
            out.append({"capsule": cid, "title": spec.get("title", ""), "language": spec.get("language", ""),
                        "task_prompt": spec.get("task_prompt", ""),
                        "questions": [q["text"] for q in spec.get("questions", [])]})
    return out


def draft_spec(prompt: str, capsule: str | None = None, repo_url: str | None = None, model: str = "haiku55",
               cap_usd: float = 0.5) -> tuple[ReproSpec, float]:
    """The user's request as a ReproSpec; returns it with the drafting cost."""
    if bool(capsule) == bool(repo_url):
        raise ValueError("give exactly one of capsule and repo_url")
    if capsule and capsule_path(capsule) is None:
        raise ValueError(f"capsule {capsule} is not downloaded")
    sid = new_spec_id()
    trace = Trace(DRAFTS / f"{sid}.draft.jsonl")
    where = f"CORE-Bench capsule {capsule} (its code is extracted into the workspace)" if capsule else \
        f"the repository {repo_url} (the agents clone it)"
    agent = Agent("drafter", DRAFT_SYSTEM, [], Draft, trace, Budget(profile=get_profile(model), limit_usd=cap_usd),
                  max_turns=3, max_cost_usd=cap_usd)
    draft: Draft = agent.run(f"Code: {where}\n\nThe user's request:\n{prompt}")
    spec = ReproSpec(
        id=sid, title=draft.title, objective=OBJECTIVE, task_prompt=draft.task_prompt,
        language=draft.language, code=CodeInput(capsule=capsule, repo_url=repo_url),
        questions=[Question(id=f"q{i}", text=q.text, answer_type=q.answer_type, locator=q.locator)
                   for i, q in enumerate(draft.questions, 1)],
        origin=SpecOrigin(source="user", prompt=prompt, drafted_by=[get_profile(model).name]))
    return spec, agent.budget.spent_usd


def new_run(spec: ReproSpec, workflow: str, model: str | None = None) -> RunContext:
    """A run on a user spec. A capsule is extracted with the Hard-level clean-up; a repository starts empty."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS / f"{stamp}_{spec.id}_{workflow}"
    sb = Sandbox(run_dir)
    removed = 0
    if spec.code.capsule:
        archive = capsule_path(spec.code.capsule)
        if archive is None:
            raise ValueError(f"capsule {spec.code.capsule} is not downloaded")
        ext = capsule.extract(archive, sb.workspace, hard=True)
        capsule.save(run_dir / "capsule_extraction.json", ext)
        removed = len(ext.removed)
    baseline = capsule.snapshot(sb.workspace)
    capsule.save(run_dir / "capsule_snapshot.json", baseline)
    placeholder = Task(id=spec.id, paper_pdf="", repo_url=spec.code.repo_url or "", objective=spec.objective,
                       claims=[], seeds=1)
    ctx = RunContext(spec.id, workflow, placeholder, run_dir, sb, Trace(run_dir / "trace.jsonl"),
                     budget=Budget(profile=get_profile(model)), brief=brief(spec), baseline_files=baseline, spec=spec)
    ctx.save("spec.json", spec)
    ctx.trace.log("runner", "start", case=spec.id, source="user", workflow=workflow, model=ctx.budget.model,
                  profile=ctx.budget.profile.name, provider=ctx.budget.profile.provider,
                  budget_usd=ctx.budget.limit_usd, removed=removed, code=corebench.code_fingerprint())
    return ctx


def finish(ctx: RunContext, started: float, error: str | None = None, answers: Answers | None = None,
           extra: dict | None = None) -> corebench.CapsuleEval:
    """corebench.finish for a user spec: save the answers and their provenance, grade nothing."""
    spec: ReproSpec = ctx.spec
    by_id = {a.question_id: a for a in answers.answers} if answers else {}
    if answers is not None:
        ctx.save("answers.json", answers)
    ctx.save("log_manifest.json", dict(ctx.sandbox.manifest))
    values = {qid: a.value for qid, a in by_id.items() if a.value is not None}
    prov = capsule.provenance(values, ctx.sandbox.workspace, ctx.baseline_files or {}, corebench.trusted_logs(ctx),
                              exclude={"report.json"}, authored=ctx.sandbox.authored)
    questions = [{"id": q.id, "question": q.text, "answer": by_id[q.id].value if q.id in by_id else None,
                  "evidence": by_id[q.id].evidence if q.id in by_id else [],
                  "note": by_id[q.id].note if q.id in by_id else "",
                  "provenance": asdict(prov[q.id]) if q.id in prov else None} for q in spec.questions]
    answered = sum(q["answer"] is not None for q in questions)
    verdict = "answered" if answered == len(questions) else "partial" if answered else "no_answers"
    result = corebench.CapsuleEval(ctx.case_id, verdict, False, None, False, answers is not None, [], [], [], [], [],
                                   questions)
    ctx.save("eval.json", asdict(result))
    summary = {"case": ctx.case_id, "source": "user", "workflow": ctx.workflow, "model": ctx.budget.model,
               "profile": ctx.budget.profile.name, "provider": ctx.budget.profile.provider,
               "code": corebench.code_fingerprint(), "skills": skills.library_version(), "verdict": verdict,
               "answered": answered, "questions": len(questions), "error": error,
               "wall_s": round(time.monotonic() - started, 1),
               "llm": {**ctx.budget.usage.__dict__, "cost_usd": round(ctx.budget.spent_usd, 4),
                       "budget_usd": ctx.budget.limit_usd}}
    summary.update(extra or {})
    ctx.save("summary.json", summary)
    ctx.trace.log("runner", "end", **summary)
    return result


def run(spec_path: Path, workflow: str, model: str | None, keep_workspace: bool = True) -> int:
    """Run one user spec with one workflow version (the demo server's subprocess). The workspace is kept by default,
    so the UI can show the figures and files the run made."""
    from .cli import WORKFLOWS
    import os
    import signal
    spec = ReproSpec.model_validate_json(spec_path.read_text())
    ctx = new_run(spec, workflow, model)
    print(ctx.run_dir.name, flush=True)

    def stopped(signum, frame):
        # Stop on the page sends SIGTERM here. The command being run lives in its own session (and on a server
        # belongs to another user), so this process must kill it on the way out or it would run on unattended.
        ctx.sandbox.kill_live()
        os._exit(128 + signum)

    signal.signal(signal.SIGTERM, stopped)
    try:
        WORKFLOWS[workflow](ctx)
    finally:
        if not keep_workspace:
            ctx.sandbox.discard_workspace()
    return 0
