"""ReproSpec: what a run must reproduce, independent of where the task came from.

Three sources produce the same spec: a user's prompt (the intent stage, later), CORE-Bench (a deterministic
conversion, p2e.corebench) and the hand-built paper cases (to be migrated). The workflow versions read the spec's
brief and submit `Answers`; only the evaluator knows the answers.

Why one layer: every source answers the same question (which results, of what type, proven by what evidence). A
branch per source in every version would cost sources x versions; with the spec each source needs one converter.
The A-D comparison uses only the deterministic entries (spec given), so errors of the intent stage do not mix into
the comparison of architectures. Design sources: CORE-Bench (answer keys must match the questions exactly) and
ReplicationBench (fixed answer structure; scores rise from 0.19 to 0.46 when answers are not masked).
"""
from __future__ import annotations

import json
from typing import Literal, Union

from pydantic import BaseModel, Field

from .sandbox import MACHINE

AnswerType = Literal["number", "string", "bool", "list", "any"]
Scalar = Union[bool, int, float, str]


class Question(BaseModel):
    id: str = Field(description="Short id, e.g. q1")
    text: str = Field(description="The question as the agent sees it")
    answer_type: AnswerType = "any"  # CORE-Bench does not say; its questions usually make it clear
    metric: str = ""
    direction: Literal["higher", "lower", ""] = ""
    unit: str = ""
    locator: str = Field("", description="Where the paper reports it (e.g. Table 2, row 3), or 'program output'")
    setting: str = ""
    runs: int = Field(1, ge=1, description="Independent runs (seeds) to submit; 1 for CORE-Bench")
    evidence: Literal["log", "output_file", "either"] = "either"


class PaperInput(BaseModel):
    url: str | None = None
    pdf: str | None = None


class CodeInput(BaseModel):
    repo_url: str | None = None  # cloned by the agent
    capsule: str | None = None  # extracted into the workspace before the run (Hard-level clean-up)


class SpecOrigin(BaseModel):
    source: Literal["user", "corebench", "case"]
    reference: str = ""  # e.g. the dataset and its sha256
    prompt: str = ""  # the user's request (source=user)
    owner: str = ""  # on a shared server, the signed-in name that started the run (set by the server, not the page)
    drafted_by: list[str] = Field(default_factory=list)  # models of the intent stage
    checked_by: list[str] = Field(default_factory=list)
    user_confirmed: bool = False


class ReproSpec(BaseModel):
    """The agent-visible part of a task. Never holds an answer."""
    id: str
    title: str = ""
    objective: str
    task_prompt: str = ""
    language: str = ""
    paper: PaperInput | None = None
    code: CodeInput
    questions: list[Question]
    origin: SpecOrigin

    def question(self, qid: str) -> Question | None:
        return next((q for q in self.questions if q.id == qid), None)


class AnswerItem(BaseModel):
    question_id: str
    value: Union[Scalar, list[Scalar], None] = Field(description="The answer as the run printed or wrote it: a "
                                                                 "number, a string, true/false or a list")
    evidence: list[str] = Field(default_factory=list, description="Where the run printed or wrote it: "
                                                                  "logs/<name> or a workspace path")
    note: str = ""


class Answers(BaseModel):
    """What a run submits on a spec."""
    answers: list[AnswerItem]
    notes: str = ""


def _type_ok(answer_type: AnswerType, value) -> bool:
    if value is None:
        return False
    if answer_type == "any":
        return True
    if answer_type == "list":
        return isinstance(value, list)
    if answer_type == "bool":
        return isinstance(value, bool) or str(value).strip().lower() in ("true", "false", "yes", "no")
    if answer_type == "number":
        if isinstance(value, bool):
            return False
        try:
            float(str(value).strip().rstrip("%"))
            return True
        except ValueError:
            return False
    return isinstance(value, str)


def answer_problems(spec: ReproSpec, answers: list[AnswerItem], not_measured: dict[str, str] | None = None
                    ) -> list[str]:
    """Structural problems of a set of answers: unknown or repeated ids, missing questions, wrong types."""
    not_measured = not_measured or {}
    problems, seen = [], set()
    for a in answers:
        q = spec.question(a.question_id)
        if q is None:
            problems.append(f"{a.question_id}: no such question (ids: {[q.id for q in spec.questions]})")
            continue
        if a.question_id in seen:
            problems.append(f"{a.question_id}: answered twice")
        seen.add(a.question_id)
        if not _type_ok(q.answer_type, a.value):
            problems.append(f"{a.question_id}: expected a {q.answer_type} answer, got {json.dumps(a.value)}")
    for q in spec.questions:
        if q.id not in seen and q.id not in not_measured:
            problems.append(f"{q.id}: no answer and no not-measured reason")
    return problems


def brief(spec: ReproSpec) -> str:
    """The task as every workflow version presents it to its agents."""
    parts = [f"Objective: {spec.objective}"]
    if spec.paper is not None:
        parts.append("Paper: `paper/paper.pdf` (extracted text: `paper/paper.txt`)")
    if spec.code.capsule:
        parts.append(
            "The code is already in your workspace: `code/` (the authors' code and README) and `data/` where present. "
            "Results, the run script, the environment specification and the reproduction instructions were removed. "
            "Install the requirements the README or the code names, then run the commands needed to answer the "
            "questions. Do not clone or download the code from elsewhere.")
    elif spec.code.repo_url:
        parts.append(f"Official repository: {spec.code.repo_url} (not cloned yet)")
    if spec.task_prompt:
        parts.append(f"Specifically, you need to: {spec.task_prompt}")
    if spec.language:
        parts.append(f"Language: {spec.language}.")
    parts.append(f"Machine: {MACHINE}, CPU only, no CUDA. `uv`, `micromamba` (R and other non-Python environments) and `git` are available. Keep any single "
                 "command under 20 minutes.")
    qs = "\n".join(f"- `{q.id}`" + (f" ({q.answer_type})" if q.answer_type != "any" else "") + f": {q.text}"
                   for q in spec.questions)
    parts.append(f"Questions, by id:\n{qs}")
    parts.append(
        "Answer every question by its id. An answer counts only if a run you made in this sandbox printed it (a "
        "command's log) or wrote it (a file the run created or changed); cite that log or file as evidence. "
        "Answers found only in files that were in the workspace before you started, numbers you typed or computed "
        "by hand, and values looked up elsewhere do not count. Give numbers as numbers, without units or %, unless "
        "the question asks otherwise.")
    return "\n\n".join(parts)
