"""Version A on a spec run (a CORE-Bench-shaped capsule), offline with a scripted model."""
from p2e import corebench
from p2e.testing import FakeClient, make_spec_case, use_fake
from p2e.versions import load

single = load("SingleAgent")
KEY = single.SYSTEM_SPEC[:30]


def test_single_answers_a_capsule(tmp_path, monkeypatch):
    cid = make_spec_case(tmp_path, monkeypatch)
    fake = FakeClient({KEY: [
        [("run_shell", {"command": "python3 code/main.py"})],
        [("submit", {"answers": [{"question_id": "q1", "value": "CatBoost", "evidence": ["logs/cmd_001_shell.log"]},
                                 {"question_id": "q2", "value": 0.957, "evidence": ["logs/cmd_001_shell.log"]},
                                 {"question_id": "q3", "value": 0.9506, "evidence": ["data/old_results.txt"]}]})],
    ]})
    use_fake(monkeypatch, fake)
    ctx = corebench.new_run(cid, "single")
    result = single.run(ctx)
    # the third answer is right but came from a file the capsule shipped with: a shortcut, not a reproduction
    assert result.verdict == "partial" and result.full_tolerance_only and result.shortcut == ["Old accuracy?"]
    assert "`q1`" in ctx.task_brief()
