"""Skill library (p2e.skills), offline: shared read tool, leakage check, versioned apply, freeze, digests, curator."""
import json

import pytest

from p2e import corebench, skills
from p2e.llm import sandbox_tools
from p2e.sandbox import Sandbox
from p2e.skills import Curation, Skill, SkillEdit
from p2e.testing import FakeClient, make_spec_case, use_fake
from p2e.versions import load

TERMS = {"identifier": {"capsule-1234567", "1234567", "ngboost"}, "title": {"a study of everything"},
         "answer": {"0.9123", "catboost"}}
GOOD = SkillEdit(action="create", name="find-entry-point", description="Use when no instructions say how to run.",
                 body="1. Read the README.\n2. Read the shell scripts.", rationale="lost turns", evidence=["run_a"])


def _apply(*edits, root):
    return skills.apply(Curation(assessment="test", edits=list(edits)), root=root, terms=TERMS)


def test_apply_writes_a_version_with_history_and_changelog(tmp_path):
    root = tmp_path / "lib"
    assert _apply(GOOD, root=root) == (1, [])
    revised = GOOD.model_copy(update={"action": "revise", "body": "1. Read the README and the Makefile."})
    assert _apply(revised, root=root) == (2, [])
    s = skills.load(root)[0]
    assert s.version == 2 and "Makefile" in s.body
    assert (root / "history" / "v1" / "find-entry-point.md").read_text().count("shell scripts") == 1
    log = (root / "CHANGELOG.md").read_text()
    assert "## v1" in log and "## v2" in log and "run_a" in log
    assert _apply(GOOD.model_copy(update={"action": "retire"}), root=root) == (3, [])
    assert skills.load(root) == []


@pytest.mark.parametrize("body, hit", [
    ("Run it like capsule-1234567 did.", "identifier"),
    ("The NGBoost script needs --natural.", "identifier"),
    ("Expect 0.9123 at the end.", "answer"),
    ("The best model is CatBoost.", "answer"),
    ("As in A Study of Everything, use ten splits.", "title"),
    ("Search the code for the printed string; expect 0.91 or so.", None),  # dictionary words, short numbers
])
def test_check_rejects_identifiers_and_answers(body, hit):
    problems = skills.check(Skill("some-skill", "Use when testing.", body), TERMS)
    assert (hit is None and problems == []) or (hit is not None and any(hit in p for p in problems))


def test_a_leaking_edit_writes_nothing(tmp_path):
    root = tmp_path / "lib"
    leak = GOOD.model_copy(update={"name": "other-skill", "body": "Use 0.9123."})
    version, problems = _apply(GOOD, leak, root=root)
    assert version == 0 and problems and not root.exists()


def test_freeze_blocks_updates_and_detects_changes(tmp_path):
    root = tmp_path / "lib"
    _apply(GOOD, root=root)
    with pytest.raises(RuntimeError, match="not frozen"):
        skills.require_frozen(root)
    skills.freeze("before test", root)
    skills.require_frozen(root)
    assert _apply(GOOD.model_copy(update={"action": "revise"}), root=root)[1][0].startswith("library is frozen")
    (root / "find-entry-point" / "SKILL.md").write_text((root / "find-entry-point" / "SKILL.md").read_text() + "x")
    with pytest.raises(RuntimeError, match="changed after the freeze"):
        skills.require_frozen(root)


def test_every_agent_gets_the_same_read_tool(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    _apply(GOOD, root=root)
    monkeypatch.setattr(skills, "ROOT", root)
    sb = Sandbox(tmp_path / "run")
    for kw in ({}, {"shell": False, "write": False}):
        tool = {t.name: t for t in sandbox_tools(sb, **kw)}["read_skill"]
        assert "find-entry-point: Use when no instructions" in tool.description
        assert "Read the shell scripts" in tool.fn({"name": "find-entry-point"})
        assert "No skill named" in tool.fn({"name": "nope"})
    monkeypatch.setenv("P2E_SKILLS", "off")
    assert "read_skill" not in {t.name for t in sandbox_tools(sb)}
    assert skills.library_version(root)["enabled"] is False


def test_spec_run_records_the_library_version_and_the_digest_hides_expected_values(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    _apply(GOOD, root=root)
    monkeypatch.setattr(skills, "ROOT", root)
    cid = make_spec_case(tmp_path, monkeypatch, split="dev")
    single = load("SingleAgent")
    use_fake(monkeypatch, FakeClient({single.SYSTEM_SPEC[:30]: [
        [("read_skill", {"name": "find-entry-point"}), ("run_shell", {"command": "python3 code/main.py"})],
        [("run_shell", {"command": "python3 code/missing.py"})],
        [("submit", {"answers": [{"question_id": "q1", "value": "XGBoost", "evidence": ["logs/cmd_001_shell.log"]},
                                 {"question_id": "q2", "value": 0.957, "evidence": ["logs/cmd_001_shell.log"]}]})],
    ]}))
    ctx = corebench.new_run(cid, "single")
    single.run(ctx)
    summary = json.loads((ctx.run_dir / "summary.json").read_text())
    assert summary["skills"]["version"] == 1 and summary["skills"]["enabled"] and summary["split"] == "dev"
    text = skills.digest(ctx.run_dir)
    assert "skills read: find-entry-point" in text and '"XGBoost"' in text and "passed=False" in text
    assert "CatBoost" not in text  # the expected answer of q1 never reaches the curator
    assert "missing.py" in text and "exit" in text
    stats = skills.usage_stats([ctx.run_dir])
    assert stats["find-entry-point"]["1"] == {"runs": 1, "full": 0}


def test_digest_refuses_test_split_runs(tmp_path):
    run = tmp_path / "20261017-000000_v4-x_single"
    run.mkdir()
    (run / "summary.json").write_text(json.dumps({"case": "cb-1", "split": "test", "workflow": "single"}))
    with pytest.raises(ValueError, match="test-split"):
        skills.digest(run)


def test_curator_proposes_edits_that_apply_checks(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    run = tmp_path / "20261017-000000_cb-1_single"
    run.mkdir()
    (run / "summary.json").write_text(json.dumps({"case": "cb-1", "workflow": "single", "verdict": "fail",
                                                  "error": "setup failed"}))
    use_fake(monkeypatch, FakeClient({skills.CURATOR[:30]: [[("submit", {"assessment": "setup failed",
                                                                         "edits": [GOOD.model_dump()]})]]}))
    cur, out = skills.curate([run], model="luna", root=root, out_dir=tmp_path / "cur")
    assert (out / "prompt.md").read_text().count("setup failed") == 1
    assert _apply(*cur.edits, root=root) == (1, [])


def test_live_library_holds_no_benchmark_identifiers_or_answers():
    from p2e.sandbox import PROJECT_ROOT
    terms = skills.forbidden_terms()
    assert terms["identifier"] and terms["answer"]
    for s in skills.load(PROJECT_ROOT.parent / "skills"):
        assert skills.check(s, terms) == [], s.name


def test_identifiers_that_are_english_words_are_not_leaks(monkeypatch):
    monkeypatch.setattr(skills, "_english_words", lambda: {"fits"})
    terms = skills.forbidden_terms()
    assert "fits" not in terms["identifier"]
    assert any(i.startswith("capsule-") for i in terms["identifier"])
