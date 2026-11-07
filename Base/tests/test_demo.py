"""The demo: a user's request as a spec, a run on it without grading, and the live graph the page draws from a trace."""
from __future__ import annotations

import json
import time

import pytest

from p2e import corebench, demo
from p2e.spec import AnswerItem, Answers, CodeInput, Question, ReproSpec, SpecOrigin
from p2e.web import demo_server
from tests.test_capsule import make_capsule


def _user_spec(capsule_id="capsule-0000001") -> ReproSpec:
    return ReproSpec(id="user-20261106-120000", title="t", objective=demo.OBJECTIVE, task_prompt="Run main.py.",
                     code=CodeInput(capsule=capsule_id), origin=SpecOrigin(source="user", prompt="run main.py"),
                     questions=[Question(id="q1", text="What is the AUC?", answer_type="number"),
                                Question(id="q2", text="Which model is best?")])


def test_drafting_needs_exactly_one_code_source():
    with pytest.raises(ValueError, match="exactly one"):
        demo.draft_spec("reproduce table 2")
    with pytest.raises(ValueError, match="exactly one"):
        demo.draft_spec("reproduce table 2", capsule="capsule-0000001", repo_url="https://github.com/a/b")
    with pytest.raises(ValueError, match="not downloaded"):
        demo.draft_spec("reproduce table 2", capsule="capsule-9999999")


def test_a_user_spec_runs_and_finishes_with_its_answers_and_no_grade(tmp_path, monkeypatch):
    archive = tmp_path / "capsule-0000001.tar.gz"
    make_capsule(archive, {"code/main.py": "print('best CatBoost'); print('auc 0.957')\n",
                           "results/output": "auc 0.957"})
    monkeypatch.setattr(demo, "capsule_path", lambda cid: archive)
    monkeypatch.setattr(demo, "RUNS", tmp_path / "runs")
    ctx = demo.new_run(_user_spec(), "single")
    assert "Run main.py." in ctx.task_brief() and not (ctx.sandbox.workspace / "results").exists()
    assert ctx.sandbox.run("python3 code/main.py").ok
    answers = Answers(answers=[AnswerItem(question_id="q1", value=0.957, evidence=["logs/cmd_001_shell.log"])])
    result = corebench.finish(ctx, time.monotonic(), answers=answers)  # the workflows call this; it hands over

    assert result.verdict == "partial" and not result.full
    q1, q2 = result.questions
    assert q1["answer"] == 0.957 and q1["provenance"]["status"] == "produced" and q2["answer"] is None
    summary = json.loads((ctx.run_dir / "summary.json").read_text())
    assert summary["source"] == "user" and summary["answered"] == 1 and summary["questions"] == 2
    assert not (ctx.run_dir / "report.json").exists()  # nothing to grade against


def _event(agent, event, t, **kw):
    return json.dumps({"t": t, "agent": agent, "event": event, **kw}) + "\n"


def test_the_graph_of_a_planner_run_nests_retries_and_maps_workers_onto_their_tasks(tmp_path, monkeypatch):
    d = tmp_path / "20261106-120000_user-20261106-120000_planner_workers"
    d.mkdir()
    (d / "spec.json").write_text(_user_spec().model_dump_json())
    t = time.time() - 100
    plan = {"add_tasks": [{"task_id": "setup", "kind": "agent", "objective": "Make an R environment"},
                          {"task_id": "run", "kind": "run", "command": "Rscript main.R", "purpose": "Run the script"}]}
    (d / "trace.jsonl").write_text("".join([
        _event("runner", "start", t, profile="luna", model="gpt-6-luna"),
        _event("planner", "start", t + 1, task="Objective: ..."),
        _event("planner", "response", t + 2, tool_calls=[{"name": "list_dir", "input": "{\"path\": \"code\"}"}],
               usage=[{"prompt": 1000, "cached": 0, "written": 0, "output": 100}]),
        _event("planner", "tool_result", t + 2.1, tool="list_dir", is_error=False, output="main.R"),
        _event("planner", "submit", t + 3, output=plan),
        _event("planner", "end", t + 3),
        _event("runtime", "task/added", t + 3, task_id="setup", kind="agent", lineage="setup", attempt=1),
        _event("runtime", "task/added", t + 3, task_id="run", kind="run", lineage="run", attempt=1),
        _event("runtime", "task/running", t + 4, task_id="setup"),
        _event("setup_setup", "start", t + 4, task="Task setup (setup)."),
        _event("setup_setup", "response", t + 5, tool_calls=[{"name": "run_shell", "input": "{\"command\": \"micromamba create\"}"}]),
        _event("runtime", "task/done", t + 9, task_id="setup", summary="R 4.5 ready"),
        _event("runtime", "task/running", t + 10, task_id="run"),
        _event("runtime", "task/failed", t + 11, task_id="run", problems=["exit code 1"], signature="Error in dtw()"),
        _event("runtime", "task/added", t + 12, task_id="run2", kind="run", lineage="run", attempt=2),
        _event("runtime", "task/running", t + 12, task_id="run2"),
    ]))
    monkeypatch.setattr(demo_server, "run_dir_of", lambda key: d)
    state = demo_server.build_state("user-20261106-120000_planner_workers")
    nodes = {n["id"]: n for n in state["nodes"]}

    assert state["phase"] == "running" and list(nodes) == ["planner", "task:setup", "task:run", "task:run2"]
    assert nodes["planner"]["status"] == "waiting" and nodes["planner"]["cost"] > 0
    assert nodes["planner"]["steps"][0] | {"status": "done", "label": "List directory", "target": "code"} == nodes["planner"]["steps"][0]
    setup = nodes["task:setup"]
    assert setup["status"] == "done" and setup["task"] == "Make an R environment" and setup["steps"][0]["name"] == "run_shell"
    assert nodes["task:run"]["status"] == "failed" and nodes["task:run"]["summary"] == "Error in dtw()"
    assert nodes["task:run2"]["parent"] == "task:run" and nodes["task:run2"]["attempt"] == 2
    assert nodes["task:run"]["steps"][0]["args"]["command"] == "Rscript main.R" and nodes["task:run2"]["status"] == "running"


def test_answers_are_compared_with_the_paper_by_relative_gap():
    assert demo.compare(-21.887, "-21.92")["status"] == "match"
    assert demo.compare(-21.0, -21.92)["status"] == "close"
    gap = demo.compare(-1.9214, -21.92)
    assert gap["status"] == "mismatch" and round(gap["diff"], 4) == 19.9986
    assert demo.compare("SCZ ", "scz")["status"] == "match" and demo.compare("HC", "SCZ")["status"] == "mismatch"
    assert demo.compare(None, 1.0)["status"] == "unknown" and demo.compare("12.5%", 12.5)["status"] == "match"
    assert demo.compare(4.4e-16, 0.0)["status"] == "match"  # floating-point noise around a reference of 0


def test_the_paper_comes_from_the_request_or_else_the_readme(monkeypatch):
    from p2e import intent
    assert demo.find_arxiv("see https://arxiv.org/abs/2107.10043v3 table 1", None) == "2107.10043"
    monkeypatch.setattr(intent, "repo_info", lambda url: ("Paper: [arXiv](https://arxiv.org/pdf/1705.09412)", [], []))
    assert demo.find_arxiv("reproduce table 1", "https://github.com/a/b") == "1705.09412"
    assert demo.find_arxiv("reproduce table 1", None) is None


def test_a_demo_runs_answers_carry_the_papers_value_and_the_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "DRAFTS", tmp_path / "drafts")
    spec = _user_spec()
    demo.save_paper_values(spec.id, {"arxiv": "2107.10043", "values": {
        "q1": {"question_id": "q1", "value": 0.95, "unit": "", "location": "Table 2", "quote": ""}}})
    d = tmp_path / "run"
    d.mkdir()
    (d / "eval.json").write_text(json.dumps({"questions": [
        {"id": "q1", "question": "What is the AUC?", "answer": 0.957, "evidence": [], "note": "", "provenance": None},
        {"id": "q2", "question": "Which model is best?", "answer": "CatBoost", "evidence": [], "note": "", "provenance": None}]}))
    q1, q2 = demo_server.answers_of(d, spec.model_dump())
    assert q1["reference"]["value"] == 0.95 and q1["reference"]["source"] == "paper" and q1["comparison"]["status"] == "match"
    assert q2["reference"] is None and q2["comparison"]["status"] == "unknown"


def test_a_request_without_code_is_answered_with_a_question_not_a_draft(monkeypatch):
    def no_llm(*a, **k):
        raise AssertionError("no LLM call before the user names the code")
    monkeypatch.setattr(demo, "draft_spec", no_llm)
    assert demo_server.draft({"prompt": "reproduce KalmanNet table 1"}) == {"need": "repo_url"}
    assert demo_server.repo_url_in("reproduce KalmanNet table 1") is None
    assert demo_server.repo_url_in("code: https://github.com/KalmanNet/KalmanNet_TSP.git.") == \
        "https://github.com/KalmanNet/KalmanNet_TSP"


def test_an_example_is_every_quick_task_once_and_runs_as_a_fresh_spec(tmp_path, monkeypatch):
    runs, drafts = tmp_path / "runs", tmp_path / "runs" / "demo_drafts"
    monkeypatch.setattr(demo_server, "RUNS", runs)
    monkeypatch.setattr(demo, "RUNS", runs)
    monkeypatch.setattr(demo, "DRAFTS", drafts)
    old = _user_spec().model_copy(update={"code": CodeInput(repo_url="https://github.com/a/b")})
    for name, wf, wall, verdict in (("20261106-120000", "single", 300, "answered"), ("20261106-121000", "fixed", 90, "answered"),
                                    ("20261106-122000", "planner_workers", 30, "no_answers")):
        d = runs / f"{name}_{old.id}_{wf}"
        d.mkdir(parents=True)
        (d / "spec.json").write_text(old.model_dump_json())
        (d / "summary.json").write_text(json.dumps({"case": old.id, "source": "user", "workflow": wf, "wall_s": wall,
                                                    "verdict": verdict}))
    demo.save_paper_values(old.id, {"arxiv": "1705.09412", "values": {"q1": {"question_id": "q1", "value": 0.95}}})
    [ex] = demo_server.list_examples()
    assert ex["case"] == old.id and ex["fastest_s"] == 90 and ex["workflows"] == ["fixed", "single"]  # no_answers is no example
    got = demo_server.example_spec(old.id)
    assert got["spec"]["id"] != old.id and got["spec"]["origin"]["source"] == "user"
    assert [q["text"] for q in got["spec"]["questions"]] == [q.text for q in old.questions]
    assert demo.load_paper_values(got["spec"]["id"])["values"]["q1"]["value"] == 0.95


def test_the_run_folder_is_outside_the_project_and_reaches_the_runs(tmp_path, monkeypatch):
    from p2e.sandbox import PROJECT_ROOT
    monkeypatch.setattr(demo_server, "SETTINGS", tmp_path / "settings.json")
    with pytest.raises(ValueError, match="outside the project"):
        demo_server.set_run_folder(str(PROJECT_ROOT / "runs" / "x"))
    with pytest.raises(ValueError, match="absolute"):
        demo_server.set_run_folder("relative/dir")
    state = demo_server.set_run_folder(str(tmp_path / "reproductions"))
    assert state["chosen"] and state["name"] == "reproductions" and (tmp_path / "reproductions").is_dir()
    assert demo_server.run_folder() == (tmp_path / "reproductions").resolve()
