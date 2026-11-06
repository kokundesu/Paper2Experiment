"""CORE-Bench v1.1 graded with our tolerance rule (docs/benchmark-redesign.md section 3.3)."""
import json

import pytest

from p2e import cli, corebench


def task(results, cid="capsule-0000000"):
    return {"capsule_id": cid, "language": "Python", "field": "Computer Science", "task_prompt": "Run x.py",
            "results": results}


def test_tolerance_terms():
    # the worked example in the design doc: n=5 re-runs, m=3 agent seeds
    tol = corebench.tolerance([92.31, 92.58, 92.12, 92.44, 92.27], m=3, places=1)
    assert tol["noise"] == pytest.approx(0.353, abs=1e-3) and tol["term"] == "noise" and not tol["stochastic"]
    # deterministic re-runs: the printed precision decides
    tol = corebench.tolerance([0.98, 0.98, 0.98])
    assert tol["h"] == pytest.approx(0.005) and tol["term"] == "precision"
    # full-precision floats: numpy.isclose's allowance decides
    tol = corebench.tolerance([0.9157952669235003] * 3)
    assert tol["term"] == "floor" and tol["h"] == pytest.approx(1e-5 * 0.9157952669235003)
    # m=1, n=3 is CORE-Bench's own prediction interval: 4.303 * s * sqrt(4/3)
    vals = [87.516, 86.578, 86.186]
    import statistics
    assert corebench.tolerance(vals)["noise"] == pytest.approx(4.303 * statistics.stdev(vals) * (4 / 3) ** 0.5)
    assert corebench.tolerance([1.0, 1.5, 2.0])["stochastic"]


def test_floor_scales_with_tiny_values():
    tol = corebench.tolerance([2.341092434893948e-10] * 3)
    assert tol["h"] < 1e-14 and not tol["stochastic"]  # an absolute 1e-8 would accept any p-value below 1e-8
    assert corebench.tolerance([0.0] * 3, places=0)["h"] == 0.5
    assert corebench.tolerance([0.0, 0.0, 0.0])["floor"] == 1e-8


def test_decimals():
    assert corebench.decimals(0.98) == 2 and corebench.decimals(280000) == 0
    assert corebench.decimals("2.341092434893948e-10") == 25 and corebench.decimals(1e-5) == 5


def test_numeric_answers_accept_unrounded_values_and_percent_strings():
    t = task([{"Report the AUC.": 0.98, "Report the rate.": 97.82}] * 3)
    assert corebench.grade_task(t, {"Report the AUC.": 0.9823, "Report the rate.": "97.82%"}).full
    assert not corebench.grade_task(t, {"Report the AUC.": 0.9861, "Report the rate.": 97.82}).full
    # a rounded answer to a full-precision ground truth is not accepted (as in CORE-Bench)
    t = task([{"Report the AUC.": 0.9157952669235003}] * 3)
    assert not corebench.grade_task(t, {"Report the AUC.": 0.916}).full
    assert corebench.grade_task(t, {"Report the AUC.": 0.91579}).full


def test_stochastic_questions_are_reported_but_not_scored():
    t = task([{"Noisy?": 1.0, "Stable?": 3.0}, {"Noisy?": 1.5, "Stable?": 3.0}, {"Noisy?": 2.0, "Stable?": 3.0}])
    r = corebench.grade_task(t, {"Noisy?": 100.0, "Stable?": 3.0})
    assert r.full and [q.scored for q in r.questions] == [False, True]
    assert corebench.grade_task(task([{"Noisy?": 1.0}, {"Noisy?": 1.5}, {"Noisy?": 2.0}]), {"Noisy?": 1}).full is None


def test_strings_booleans_and_numbers_in_strings():
    t = task([{"Which model?": "CatBoost", "IsNGGMatch?": "True", "p-value?": "2.341092434893948e-10"}] * 3)
    assert corebench.grade_task(t, {"Which model?": "catboost", "IsNGGMatch?": True,
                                    "p-value?": 2.341092434893948e-10}).full
    # the original HAL rule turns True into 1.0 before comparing strings (the bug v1.1 fixed)
    assert not corebench.hal_grade(t, {"Which model?": "catboost", "IsNGGMatch?": True,
                                       "p-value?": "2.341092434893948e-10"})


def test_lists_and_missing_or_invalid_answers():
    q = "Give a list of 2 integers."
    t = task([{q: [196000, 364000]}] * 3)
    assert corebench.grade_task(t, {q: [196000, 364000]}).full
    assert not corebench.grade_task(t, {q: [364000, 196000]}).full
    noisy = task([{q: [87.516, 79.813]}, {q: [86.578, 79.426]}, {q: [86.186, 78.673]}])
    assert corebench.grade_task(noisy, {q: [86.0, 79.0]}).full
    assert not corebench.grade_task(t, {}).full
    bad = corebench.grade_task(t, "not json")
    assert not bad.valid and not bad.full


def test_table_11_alternates():
    auc = "Report the overall AUC from the PR curve generated with the CTRPv2 sensitivity dataset"
    t = task([{auc: 0.4929241}] * 3, cid="capsule-4252248")
    assert corebench.grade_task(t, {auc: 0.493}).full and corebench.grade_task(t, {auc: 0.4929241}).full
    pearson = "Pearson correlation coefficients between cell types"
    t = task([{pearson: ["Smooth.1", "Endo.1"]}] * 3, cid="capsule-9477017")
    assert corebench.grade_task(t, {pearson: ["endo.1", "Smooth.1"]}).full
    t = task([{"Given the Kruskal-Wallis for Group 0-2?": "0.01"}] * 3, cid="capsule-0152700")
    assert "all accepted" in corebench.grade_task(t, {"Given the Kruskal-Wallis for Group 0-2?": "0.02"}).questions[0].note


def test_ground_truth_mean_passes_every_v11_task():
    tasks = corebench.load_tasks()
    assert len(tasks) == 39
    for t in tasks:
        answer = {}
        for q, first in t["results"][0].items():
            if isinstance(first, (int, float)) and not isinstance(first, bool):
                answer[q] = sum(r[q] for r in t["results"]) / len(t["results"])
            else:
                answer[q] = first
        assert corebench.grade_task(t, answer).full is not False, t["capsule_id"]


def test_cli_overview_and_grade(tmp_path, capsys):
    assert cli.main(["corebench", "overview"]) == 0
    assert "39 tasks" in capsys.readouterr().out
    t = next(t for t in corebench.load_tasks() if t["capsule_id"] == "capsule-7800694")
    report = tmp_path / "report.json"
    report.write_text(json.dumps({q: v for q, v in t["results"][0].items()}))
    assert cli.main(["corebench", "grade", "capsule-7800694", str(report)]) == 0
    assert "full: True" in capsys.readouterr().out


def test_capsules_named_after_options_are_not_rejected(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "cmd_corebench", lambda a: seen.append([a.capsule, *a.more]) or 0)
    cli.main(["corebench", "download", "--split", "dev", "capsule-1", "capsule-2"])
    cli.main(["corebench", "download", "capsule-1", "--split", "dev", "capsule-2"])
    assert seen == [[None, "capsule-1", "capsule-2"], ["capsule-1", "capsule-2"]]
    with pytest.raises(SystemExit):
        cli.main(["corebench", "download", "--split", "dev", "not-a-capsule"])


def test_finished_runs_are_found_by_task_workflow_and_tag(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "RUNS", tmp_path)
    for name, wf in (("20261020-100000_cb-1_single_haiku55", "single"),
                     ("20261020-110000_cb-1_fixed_haiku55_r1_noskills", "fixed"),
                     ("20261001-090000_cb-1_planner_workers_haiku55", "planner_workers")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "summary.json").write_text(json.dumps({"case": "cb-1", "workflow": wf}))
    (tmp_path / "20261020-120000_cb-1_planner_workers_haiku55").mkdir()  # interrupted: no summary
    assert cli._finished_runs("20261020-0000") == {("cb-1", "single", "haiku55"),
                                                   ("cb-1", "fixed", "haiku55_r1_noskills")}
