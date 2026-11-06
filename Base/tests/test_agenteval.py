"""Agent evaluation report (p2e.agenteval), offline."""
import pytest

from p2e import agenteval


def test_wilson_and_mcnemar():
    lo, hi = agenteval.wilson(10, 20)
    assert lo == pytest.approx(0.299, abs=0.01) and hi == pytest.approx(0.701, abs=0.01)
    assert agenteval.mcnemar_exact(0, 0) == 1.0
    assert agenteval.mcnemar_exact(6, 0) == pytest.approx(0.03125)


@pytest.mark.parametrize("summary, answered, cat", [
    ({"verdict": "full"}, 3, None),
    ({"verdict": "fail", "error": "BudgetExceeded: environment not ready: no wheel"}, 0, "setup_failed"),
    ({"verdict": "fail", "error": "BudgetExceeded: a: no submission after 80 turns"}, 0, "budget_or_turns"),
    ({"verdict": "fail", "error": "RuntimeError: boom"}, 0, "error"),
    ({"verdict": "fail", "valid_report": True}, 0, "no_answers"),
    ({"verdict": "partial", "valid_report": True, "shortcut": ["q"]}, 2, "provenance"),
    ({"verdict": "partial", "valid_report": True}, 2, "partial"),
    ({"verdict": "fail", "valid_report": True}, 2, "wrong_answers"),
])
def test_categorize(summary, answered, cat):
    assert agenteval.categorize(summary, {}, answered) == cat


def test_a_batch_mixing_models_and_skills_is_collected_one_group_at_a_time(tmp_path):
    import json
    for name, profile, enabled in [("20261101-0900_cb-1_single_haiku55", "haiku55", True),
                                   ("20261101-0901_cb-1_single_sonnet55", "sonnet55", True),
                                   ("20261101-0902_cb-1_single_haiku55_noskills", "haiku55", False)]:
        d = tmp_path / name
        d.mkdir()
        (d / "summary.json").write_text(json.dumps({"case": "cb-1", "workflow": "single", "split": "dev",
                                                    "verdict": "full", "profile": profile,
                                                    "skills": {"enabled": enabled}}))
        (d / "eval.json").write_text(json.dumps({"questions": []}))
    names = lambda **kw: [r.dir.name.split("_", 3)[3] for r in agenteval.collect(tmp_path, **kw)]
    assert names(profiles=["haiku55"], skills=True) == ["haiku55"]
    assert names(profiles=["haiku55"], skills=False) == ["haiku55_noskills"]
    assert names(profiles=["sonnet55"]) == ["sonnet55"]
    assert len(names()) == 3
