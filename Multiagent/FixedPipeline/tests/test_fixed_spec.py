"""Version B on a spec run (a CORE-Bench-shaped capsule), offline with a scripted model: environment -> plan ->
executor (+ debugger) -> answerer (+ one hand-back) -> p2e.corebench scoring."""
import json

from p2e import corebench
from p2e.testing import FakeClient, make_spec_case, use_fake
from p2e.versions import load

fixed = load("FixedPipeline")
ENV = {"repo_dir": "code", "python": "python3", "entrypoint": "code/main.py", "setup_log": [],
       "smoke_test": "python3 code/main.py runs in under a second", "ok": True}


def test_fixed_answers_a_capsule_with_debug_and_one_hand_back(tmp_path, monkeypatch):
    cid = make_spec_case(tmp_path, monkeypatch)
    fake = FakeClient({
        fixed.ENV_SPEC[:60]: [[("submit", ENV)]],
        fixed.PLANNER_SPEC[:60]: [[("submit", {"rationale": "main.py prints both", "runs": [
            {"run_id": "main", "command": "python3 code/mian.py", "questions": ["q1", "q2"]}]})]],
        fixed.DEBUGGER_SPEC[:60]: [[("submit", {"diagnosis": "typo in the script name", "changes": [],
                                                "revised_runs": [{"run_id": "main", "command": "python3 code/main.py",
                                                                  "questions": ["q1", "q2"]}]})]],
        fixed.ANSWERER[:60]: [
            [("submit", {"answers": [{"question_id": "q1", "value": "CatBoost", "evidence": ["logs/cmd_002_exp_main.log"]}],
                         "rerun_reasons": ["q2 needs a second run"],
                         "revised_runs": [{"run_id": "again", "command": "python3 code/main.py"}]})],
            [("submit", {"answers": [
                {"question_id": "q1", "value": "CatBoost", "evidence": ["logs/cmd_002_exp_main.log"]},
                {"question_id": "q2", "value": 0.957, "evidence": ["logs/cmd_003_exp_again.log"]},
                {"question_id": "q3", "value": 0.9506, "evidence": ["data/old_results.txt"]}]})],
        ],
    })
    use_fake(monkeypatch, fake)
    ctx = corebench.new_run(cid, "fixed")
    result = fixed.run(ctx)
    assert result.verdict == "partial" and result.full_tolerance_only and result.shortcut == ["Old accuracy?"]
    summary = json.loads((ctx.run_dir / "summary.json").read_text())
    assert summary["answerer_reruns"] == 1 and summary["workflow"] == "fixed"
    runs = [json.loads(l) for l in (ctx.run_dir / "trace.jsonl").read_text().splitlines()]
    executed = [e["command"] for e in runs if e["agent"] == "executor" and e["event"] == "run"]
    assert executed == ["python3 code/mian.py", "python3 code/main.py", "python3 code/main.py"]


def test_failed_environment_still_reaches_the_answerer(tmp_path, monkeypatch):
    cid = make_spec_case(tmp_path, monkeypatch)
    fake = FakeClient({
        fixed.ENV_SPEC[:60]: [[("submit", {**ENV, "ok": False, "smoke_test": "dependency cannot be built"})]],
        fixed.ANSWERER[:60]: [[("submit", {"answers": [], "notes": "nothing ran"})]],
    })
    use_fake(monkeypatch, fake)
    ctx = corebench.new_run(cid, "fixed")
    result = fixed.run(ctx)
    assert result.verdict == "fail"
    assert "environment not ready" in json.loads((ctx.run_dir / "summary.json").read_text())["error"]
