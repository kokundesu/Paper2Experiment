from pathlib import Path

import pytest

from p2e.evaluator import evaluate
from p2e.runner import parse_metric
from p2e.sandbox import PROJECT_ROOT, Sandbox, file_sha256
from pydantic import ValidationError

from p2e.schemas import (Case, ClaimDiagnosis, ClaimMeasurement, DiscrepancyReport, GroundTruthClaim, Metrics,
                         Tolerance)


def test_tolerance_kinds():
    assert Tolerance(abs=1.5).accepts(81.0, 81.5)
    assert not Tolerance(abs=0.1).accepts(81.0, 81.5)
    assert Tolerance(rel=0.05).accepts(0.95, 1.0)
    assert Tolerance(factor=3).accepts(2e-3, 6.7e-4)
    assert not Tolerance(factor=3).accepts(3e-3, 6.7e-4)
    with pytest.raises(ValueError):
        Tolerance(abs=1, rel=0.1)


def test_parse_metric_takes_last_match_and_scales():
    out = "Epoch 1 val_acc= 0.5\nTest set results: cost= 1.0 accuracy= 0.81800 time= 0.001\n"
    assert parse_metric(out, r"accuracy= ([0-9.]+)", 100) == pytest.approx(81.8)
    assert parse_metric(out, r"nothing (\d)") is None
    assert parse_metric(out, r"(") is None  # invalid regex


def test_sandbox_runs_logs_times_out_and_blocks(tmp_path: Path):
    sb = Sandbox(tmp_path)
    r = sb.run("echo hello; exit 3")
    assert r.exit_code == 3 and "hello" in r.output and r.log_path.exists()
    assert sb.run("sleep 5", timeout_s=1).exit_code is None
    assert "BLOCKED" in sb.run("cat ../../benchmark/gcn/case.yaml").output
    assert "BLOCKED" in sb.run(f"ls {PROJECT_ROOT / 'benchmark'}").output
    assert "ANTHROPIC" not in sb.run("env").output and "OPENAI" not in sb.run("env").output
    for cmd in ("cat .env", "cat ../../../.env", f"cat {PROJECT_ROOT}/.env", "source .env"):
        assert sb.run(cmd).output.startswith("BLOCKED"), cmd
    for cmd in ("uv venv .venv", "source .venv/bin/activate", "cat config.env.example"):
        assert not sb.run(cmd).output.startswith("BLOCKED"), cmd
    with pytest.raises(PermissionError):
        sb.resolve("../outside.txt")


def test_sandbox_records_log_hashes(tmp_path: Path):
    sb = Sandbox(tmp_path)
    ok, blocked = sb.run("echo hi"), sb.run("cat case.yaml")
    assert set(sb.manifest) == {ok.log_path.name, blocked.log_path.name}  # BLOCKED logs too
    assert all(sb.manifest[p.name] == file_sha256(p) for p in (ok.log_path, blocked.log_path))
    assert not list(tmp_path.glob("**/*manifest*"))  # never on disk during the run


def test_evaluator_log_integrity(tmp_path: Path):
    sb = Sandbox(tmp_path)
    # a program that computes the values (an echo of them would be the agent's own text, see test_typed_evidence)
    genuine = sb.run("python3 -c \"import sys; sys.stdout.write('accuracy= %.3f\\naccuracy= %.3f\\n' % (0.808 + 0.01, 0.821))\"").log_path
    (tmp_path / "logs/cmd_099_shell.log").write_text("accuracy= 0.818\naccuracy= 0.821\n")  # agent's own tee
    (tmp_path / "copy.log").write_text(genuine.read_text())

    def run(ev):
        m = Metrics(claims=[ClaimMeasurement(claim_id="a", values=[81.8, 82.1], evidence=[ev])])
        return evaluate(_case(), m, tmp_path, "w", manifest=sb.manifest).claims[0]

    assert run(f"logs/{genuine.name}").evidence_ok
    for ev in ("logs/cmd_099_shell.log", "copy.log", f"logs/../logs/{genuine.name}"):
        v = run(ev)
        assert not v.evidence_ok and "log not written by the sandbox" in v.reason, ev
    m = Metrics(claims=[ClaimMeasurement(claim_id="a", values=[81.8, 82.1], evidence=["logs/cmd_099_shell.log"])])
    assert evaluate(_case(), m, tmp_path, "w").verdict == "full"  # manifest=None skips the check
    genuine.write_text(genuine.read_text() + "edited\n")
    v = run(f"logs/{genuine.name}")
    assert not v.evidence_ok and "log modified after it was written" in v.reason


def test_typed_evidence(tmp_path: Path):
    sb = Sandbox(tmp_path)
    typed = sb.run("echo 'accuracy= 0.818'; echo 'accuracy= 0.821'").log_path
    m = Metrics(claims=[ClaimMeasurement(claim_id="a", values=[81.8, 82.1], evidence=[f"logs/{typed.name}"])])
    v = evaluate(_case(), m, tmp_path, "w", manifest=sb.manifest).claims[0]
    assert not v.evidence_ok and "typed into the command" in v.reason


def _case() -> Case:
    return Case(id="t", claims=[GroundTruthClaim(id="a", metric="acc", setting="x", value=81.5,
                                                 tolerance=Tolerance(abs=1.5))],
                rubric={"min_seeds": 2})


def test_evaluator_requires_evidence(tmp_path: Path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/run1.log").write_text("accuracy= 0.81800\naccuracy= 0.82100\n")
    ok = Metrics(claims=[ClaimMeasurement(claim_id="a", values=[81.8, 82.1], evidence=["logs/run1.log"])])
    assert evaluate(_case(), ok, tmp_path, "w").verdict == "full"

    fabricated = Metrics(claims=[ClaimMeasurement(claim_id="a", values=[81.5, 81.6], evidence=["logs/run1.log"])])
    res = evaluate(_case(), fabricated, tmp_path, "w")
    assert res.verdict == "fail" and not res.claims[0].evidence_ok

    one_seed = Metrics(claims=[ClaimMeasurement(claim_id="a", values=[81.8], evidence=["logs/run1.log"])])
    assert evaluate(_case(), one_seed, tmp_path, "w").verdict == "fail"


def test_benchmark_cases_load():
    for case_dir in (PROJECT_ROOT / "benchmark").iterdir():
        if (case_dir / "case.yaml").exists() and (case_dir / "task.yaml").exists():
            from p2e.schemas import Task
            case, task = Case.load(case_dir), Task.load(case_dir)
            assert {c.id for c in case.claims} == {c.id for c in task.claims}, case_dir.name
            assert (case_dir / task.paper_pdf).exists(), case_dir.name
            # agents must not learn which claims are known not to reproduce
            assert "diagnostic" not in (case_dir / "task.yaml").read_text(), case_dir.name


def test_evaluator_median_aggregate(tmp_path: Path):
    """Heavy-tailed errors: one bad seed sinks the mean but not the median."""
    (tmp_path / "log.txt").write_text("err 6.0e-4\nerr 8.0e-4\nerr 1.1e-2\n")
    case = Case(id="t", claims=[GroundTruthClaim(id="e", metric="l2", setting="x", value=6.7e-4,
                                                 tolerance=Tolerance(factor=3))],
                rubric={"min_seeds": 3, "aggregate": "median"})
    m = Metrics(claims=[ClaimMeasurement(claim_id="e", values=[6.0e-4, 8.0e-4, 1.1e-2], evidence=["log.txt"])])
    res = evaluate(case, m, tmp_path, "w")
    assert res.verdict == "full" and res.claims[0].measured_agg == pytest.approx(8.0e-4)
    case.rubric["aggregate"] = "mean"
    assert evaluate(case, m, tmp_path, "w").verdict == "fail"


def test_evaluator_evidence_pattern(tmp_path: Path):
    """A shipped checkpoint evaluated without training must not count."""
    (tmp_path / "trained.log").write_text("epoch:0, train:12%\ntraining time: 600 s\nratio= 97.85\n")
    (tmp_path / "checkpoint.log").write_text("restored model\nratio= 97.85\n")
    gt = GroundTruthClaim(id="k", metric="r", setting="x", value=98.33, tolerance=Tolerance(abs=2),
                          evidence_pattern=r"(?s)epoch:\d+.*training time:")
    case = Case(id="t", claims=[gt], rubric={"min_seeds": 1})
    ok = Metrics(claims=[ClaimMeasurement(claim_id="k", values=[97.85], evidence=["trained.log"])])
    bad = Metrics(claims=[ClaimMeasurement(claim_id="k", values=[97.85], evidence=["checkpoint.log"])])
    assert evaluate(case, ok, tmp_path, "w").verdict == "full"
    res = evaluate(case, bad, tmp_path, "w")
    assert res.verdict == "fail" and "a cited log that shows the run" in res.claims[0].reason


def _gt(claim_id, category, confidence="confirmed", **kw):
    return {"claim_id": claim_id, "category": category, "summary": "s", "confidence": confidence, **kw}


def test_case_discrepancies_validate_claim_ids():
    claims = [{"id": "a", "metric": "m", "setting": "x", "value": 1.0, "tolerance": {"abs": 0.1}}]
    case = Case.model_validate({"id": "t", "claims": claims, "discrepancies": [
        _gt("a", "underspecified_paper", also_acceptable=["paper_code_mismatch"], key_evidence=["e"],
            confirmed_by="manual run")]})
    assert case.discrepancies[0].also_acceptable == ["paper_code_mismatch"]
    with pytest.raises(ValidationError, match="unknown claim ids"):
        Case.model_validate({"id": "t", "claims": claims, "discrepancies": [_gt("nope", "randomness")]})
    with pytest.raises(ValidationError):
        Case.model_validate({"id": "t", "claims": claims, "discrepancies": [_gt("a", "cosmic_rays")]})
    with pytest.raises(ValidationError):
        Case.model_validate({"id": "t", "claims": claims, "discrepancies": [_gt("a", "randomness", "maybe")]})


def test_claim_diagnosis_category_only_for_discrepancy():
    ClaimDiagnosis(claim_id="a", status="discrepancy", category="randomness", conclusion="seed spread", confidence="low")
    ClaimDiagnosis(claim_id="a", status="reproduced", confidence="low")  # conclusion optional otherwise
    with pytest.raises(ValidationError):
        ClaimDiagnosis(claim_id="a", status="discrepancy", conclusion="c", confidence="low")
    with pytest.raises(ValidationError, match="conclusion is required"):
        ClaimDiagnosis(claim_id="a", status="discrepancy", category="randomness", conclusion=" \n", confidence="low")
    with pytest.raises(ValidationError):
        ClaimDiagnosis(claim_id="a", status="reproduced", category="randomness", confidence="low")


def _diag_case() -> Case:
    def claim(cid, value):
        return {"id": cid, "metric": "m", "setting": "x", "value": value, "tolerance": {"abs": 1.0}}
    return Case.model_validate({"id": "t", "rubric": {"min_seeds": 1},
                                "claims": [claim("ok", 10.0), claim("miss1", 20.0), claim("miss2", 30.0),
                                           claim("miss3", 40.0), claim("gone", 50.0)],
                                "discrepancies": [
                                    _gt("miss1", "underspecified_paper", also_acceptable=["paper_code_mismatch"],
                                        key_evidence=["learning rate schedule is not stated", "Adam optimizer"]),
                                    _gt("miss2", "environment", "likely"),
                                    _gt("miss3", "paper_error", "unresolved"),
                                    _gt("ok", "randomness")]})  # passes in this run: not scored


def _diag_metrics(tmp_path: Path) -> Metrics:
    (tmp_path / "log.txt").write_text("v 10.2\nv 25.0\nv 35.0\nv 47.0\n")
    return Metrics(claims=[ClaimMeasurement(claim_id=c, values=[v], evidence=["log.txt"])
                           for c, v in (("ok", 10.2), ("miss1", 25.0), ("miss2", 35.0), ("miss3", 47.0))])


def _d(cid, status, category=None, conclusion=""):
    return ClaimDiagnosis(claim_id=cid, status=status, category=category, conclusion=conclusion, confidence="medium")


def test_evaluator_grades_diagnosis(tmp_path: Path):
    case, metrics = _diag_case(), _diag_metrics(tmp_path)
    report = DiscrepancyReport(claims=[
        _d("ok", "discrepancy", "randomness", "seed noise"),                     # false alarm
        _d("miss1", "discrepancy", "paper_code_mismatch",                        # also_acceptable
           "The learning-rate schedule is not stated; code uses Adam with step decay"),
        _d("miss2", "reproduced"),                                               # false success
        _d("miss3", "discrepancy", "unknown", "no idea"),                        # unresolved: not scored
        _d("gone", "not_measured"),                                              # no value: honest flag
    ])
    res = evaluate(case, metrics, tmp_path, "w", report)
    assert res.verdict == "partial"  # verdict logic unchanged by the diagnosis
    dg = res.diagnosis
    assert dg.present and sorted(dg.failing) == ["gone", "miss1", "miss2", "miss3"]
    assert sorted(dg.detected) == ["gone", "miss1", "miss3"] and dg.detection == 0.75
    assert dg.false_success == ["miss2"] and dg.false_alarm == ["ok"]
    by_id = {a.claim_id: a for a in dg.attributions}
    assert by_id["miss1"].correct and by_id["miss1"].scored
    assert not by_id["miss2"].correct and by_id["miss2"].scored
    assert not by_id["miss3"].scored and not by_id["ok"].scored
    assert dg.attribution == 0.5 and dg.strict_attribution == 0.5  # no decisive_evidence: strict == loose
    assert by_id["miss1"].evidence_hits == 2 and dg.evidence_recall == 1.0  # miss2 has no key_evidence

    # not_measured hides a miss when a value exists
    report.claims[1] = _d("miss1", "not_measured")
    assert "miss1" not in evaluate(case, metrics, tmp_path, "w", report).diagnosis.detected


def test_evaluator_without_report_scores_no_diagnosis(tmp_path: Path):
    res = evaluate(_diag_case(), _diag_metrics(tmp_path), tmp_path, "w")
    dg = res.diagnosis
    assert not dg.present and dg.note == "no diagnosis"
    assert dg.detection == 0.0 and dg.attribution == 0.0 and dg.attributions == []
    assert res.verdict == "partial"
    assert DiscrepancyReport.load(tmp_path) is None
    (tmp_path / "discrepancy_report.json").write_text("{not json")
    assert DiscrepancyReport.load(tmp_path) is None


def test_diagnostic_only_claims_skip_verdict_but_count_in_diagnosis(tmp_path: Path):
    def claim(cid, value, **kw):
        return {"id": cid, "metric": "m", "setting": "x", "value": value, "tolerance": {"abs": 1.0}, **kw}
    case = Case.model_validate({"id": "t", "rubric": {"min_seeds": 1},
                                "claims": [claim("ok", 10.0), claim("known_gap", 20.0, diagnostic_only=True)],
                                "discrepancies": [_gt("known_gap", "paper_code_mismatch")]})
    (tmp_path / "log.txt").write_text("v 10.2\nv 26.0\n")
    metrics = Metrics(claims=[ClaimMeasurement(claim_id="ok", values=[10.2], evidence=["log.txt"]),
                              ClaimMeasurement(claim_id="known_gap", values=[26.0], evidence=["log.txt"])])
    report = DiscrepancyReport(claims=[_d("ok", "reproduced"),
                                       _d("known_gap", "discrepancy", "paper_code_mismatch", "code differs")])
    res = evaluate(case, metrics, tmp_path, "w", report)
    assert res.verdict == "full"  # the known gap does not cost the verdict
    gap = next(v for v in res.claims if v.claim_id == "known_gap")
    assert gap.diagnostic_only and not gap.within_tolerance  # still measured and reported
    assert res.diagnosis.failing == ["known_gap"] and res.diagnosis.detection == 1.0 and res.diagnosis.attribution == 1.0
    # calling the known gap "reproduced" is still a false success
    report.claims[1] = _d("known_gap", "reproduced")
    assert evaluate(case, metrics, tmp_path, "w", report).diagnosis.false_success == ["known_gap"]
    # a failing verdict claim still decides the verdict
    metrics.claims[0].values = [15.0]
    (tmp_path / "log.txt").write_text("v 15.0\nv 26.0\n")
    assert evaluate(case, metrics, tmp_path, "w", report).verdict == "fail"


def test_diagnostic_only_needs_root_cause_and_a_verdict_claim():
    def claim(cid, **kw):
        return {"id": cid, "metric": "m", "setting": "x", "value": 1.0, "tolerance": {"abs": 0.1}, **kw}
    with pytest.raises(ValidationError, match="need a discrepancies entry"):
        Case.model_validate({"id": "t", "claims": [claim("a"), claim("b", diagnostic_only=True)]})
    with pytest.raises(ValidationError, match="at least one claim must count"):
        Case.model_validate({"id": "t", "claims": [claim("b", diagnostic_only=True)],
                             "discrepancies": [_gt("b", "randomness")]})


def test_evidence_only_failure_is_not_a_diagnosis_miss(tmp_path: Path):
    # Number within tolerance but the cited log does not prove the run: the verdict fails, yet the agent
    # calling it "reproduced" is not a false success (the diagnosis compares against the paper).
    gt = GroundTruthClaim(id="a", metric="acc", setting="x", value=81.5, tolerance=Tolerance(abs=1.0),
                          evidence_pattern=r"Epoch \d+")
    case = Case(id="t", claims=[gt], rubric={"min_seeds": 1})
    (tmp_path / "log.txt").write_text("mse: 81.4\n")  # final value only, no training output
    metrics = Metrics(claims=[ClaimMeasurement(claim_id="a", values=[81.4], evidence=["log.txt"])])
    res = evaluate(case, metrics, tmp_path, "w", DiscrepancyReport(claims=[_d("a", "reproduced")]))
    assert res.verdict == "fail" and "a cited log that shows the run" in res.claims[0].reason
    assert res.diagnosis.failing == [] and res.diagnosis.false_success == [] and res.diagnosis.detection is None


def test_strict_attribution_needs_decisive_evidence(tmp_path: Path):
    from p2e.schemas import Hypothesis
    decisive = [{"fact": "older code version", "any_of": ["older version of the code", "pre-August-2022"]},
                {"fact": "drop_last", "any_of": ["drop_last"]}]
    case = Case.model_validate({"id": "t", "rubric": {"min_seeds": 1}, "claims": [
        {"id": c, "metric": "m", "setting": "x", "value": 20.0, "tolerance": {"abs": 1.0}} for c in ("a", "b", "c")],
        "discrepancies": [_gt("a", "paper_code_mismatch", decisive_evidence=decisive),
                          _gt("b", "paper_code_mismatch", decisive_evidence=decisive),
                          _gt("c", "randomness")]})  # no decisive list: strict == loose
    (tmp_path / "log.txt").write_text("v 25.0\n")
    metrics = Metrics(claims=[ClaimMeasurement(claim_id=c, values=[25.0], evidence=["log.txt"]) for c in "abc"])
    right = ClaimDiagnosis(claim_id="a", status="discrepancy", category="paper_code_mismatch", confidence="medium",
                           conclusion="The numbers come from an OLDER   version\nof the code.",  # case + whitespace
                           hypotheses=[Hypothesis(hypothesis="seeds", evidence_against="DROP_LAST differs")])
    lucky = _d("b", "discrepancy", "paper_code_mismatch", "the paper does not report seeds")
    report = DiscrepancyReport(claims=[right, lucky, _d("c", "discrepancy", "randomness", "seed spread")])
    dg = evaluate(case, metrics, tmp_path, "w", report).diagnosis
    by_id = {a.claim_id: a for a in dg.attributions}
    assert (by_id["a"].decisive_hits, by_id["a"].decisive_total, by_id["a"].strict_correct) == (2, 2, True)
    assert (by_id["b"].decisive_hits, by_id["b"].correct, by_id["b"].strict_correct) == (0, True, False)
    assert by_id["c"].decisive_total == 0 and by_id["c"].strict_correct
    assert dg.attribution == 1.0 and dg.strict_attribution == pytest.approx(2 / 3)
    # a wrong category is never strictly correct, even with the decisive phrase
    report.claims[0] = _d("a", "discrepancy", "randomness", "older version of the code")
    a = evaluate(case, metrics, tmp_path, "w", report).diagnosis.attributions[0]
    assert a.decisive_hits == 1 and not a.correct and not a.strict_correct
    assert evaluate(case, metrics, tmp_path, "w").diagnosis.strict_attribution == 0.0  # no report
    with pytest.raises(ValidationError):
        Case.model_validate({**case.model_dump(), "discrepancies": [
            _gt("a", "randomness", decisive_evidence=[{"fact": "f", "any_of": []}])]})
    with pytest.raises(ValidationError, match="non-empty"):
        Case.model_validate({**case.model_dump(), "discrepancies": [
            _gt("a", "randomness", decisive_evidence=[{"fact": "f", "any_of": ["  "]}])]})


def test_hand_printed_summary_log_cannot_carry_a_value(tmp_path: Path):
    # Seen in a real SGC run: the agent printed the per-seed numbers and their mean from a hand-written python
    # script and cited that log. The mean "appears in a cited log", but no log that shows a training run prints it.
    gt = GroundTruthClaim(id="a", metric="acc", setting="x", value=81.0, tolerance=Tolerance(abs=0.5),
                          evidence_pattern=r"Epoch: \d+.*\nTest Accuracy:")
    case = Case(id="t", claims=[gt], rubric={"min_seeds": 3})
    for seed, acc in ((0, 80.6), (1, 81.4), (2, 81.2)):  # mean 81.067 is not any single run's value
        (tmp_path / f"run{seed}.log").write_text(f"Epoch: 100 loss 0.1\nTest Accuracy: {acc / 100:.4f}\n")
    (tmp_path / "summary.log").write_text("results = [80.6, 81.4, 81.2]; mean=81.066667\n")
    runs = ["run0.log", "run1.log", "run2.log"]
    per_seed = Metrics(claims=[ClaimMeasurement(claim_id="a", values=[80.6, 81.4, 81.2], evidence=runs + ["summary.log"])])
    assert evaluate(case, per_seed, tmp_path, "w").verdict == "full"  # an extra summary log no longer poisons the claim
    mean_only = Metrics(claims=[ClaimMeasurement(claim_id="a", values=[81.066667], evidence=["summary.log"] + runs)])
    res = evaluate(case, mean_only, tmp_path, "w")
    assert res.verdict == "fail" and "a cited log that shows the run" in res.claims[0].reason
    # the mean is within tolerance: too few seeds and weak evidence cost the verdict, not the diagnosis
    rep = DiscrepancyReport(claims=[_d("a", "reproduced")])
    dg = evaluate(case, mean_only, tmp_path, "w", rep).diagnosis
    assert res.claims[0].agg_within and dg.failing == [] and dg.false_success == []


def test_every_benchmark_claim_has_an_evidence_pattern():
    # Without one, a log in which the agent printed a number by hand would be accepted as evidence.
    for case_dir in (PROJECT_ROOT / "benchmark").iterdir():
        if (case_dir / "case.yaml").exists():
            missing = [c.id for c in Case.load(case_dir).claims if not c.evidence_pattern]
            assert not missing, (case_dir.name, missing)


def test_workspace_lives_outside_the_project_and_reaches_logs(tmp_path: Path):
    sb = Sandbox(tmp_path / "run")
    assert not sb.workspace.resolve().is_relative_to(PROJECT_ROOT.resolve())
    first = sb.run("echo first")
    out = sb.run(f"cat ../logs/{first.log_path.name}").output  # the prompts' `../logs/<file>` still works
    assert "first" in out
    assert (tmp_path / "run" / "workspace").resolve() == sb.workspace.resolve()  # link for people inspecting runs
    sb.discard_workspace()
    assert not sb.home.exists() and not (tmp_path / "run" / "workspace").exists()
    assert first.log_path.exists()  # the evidence survives, the link was removed rather than followed
    with pytest.raises(ValueError, match="outside the project"):
        Sandbox(tmp_path / "run2", root=PROJECT_ROOT / "runs")


def test_git_never_finds_a_repository_above_the_run(tmp_path: Path):
    import subprocess
    outer = tmp_path / "outer"  # a git repository that contains the workspace root, like this project did
    outer.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=outer, check=True)
    sb = Sandbox(tmp_path / "run", root=outer / "workspaces")
    assert sb.run("git rev-parse --show-toplevel").exit_code != 0
    sb.run("git init -q repo")  # a repository the agent creates or clones is still found
    top = sb.run("git rev-parse --show-toplevel", workdir="repo").output.strip()
    assert Path(top).resolve() == (sb.workspace / "repo").resolve()


def test_uv_never_adopts_a_project_above_the_run(tmp_path: Path):
    import shutil
    if not shutil.which("uv"):
        pytest.skip("uv not installed")
    outer = tmp_path / "outer"  # a uv project that contains the workspace root
    outer.mkdir()
    (outer / "pyproject.toml").write_text('[project]\nname = "outer"\nversion = "0"\nrequires-python = ">=3.9"\n')
    sb = Sandbox(tmp_path / "run", root=outer / "workspaces")
    env = sb.run("env").output
    assert "UV_NO_PROJECT=1" in env and "UV_NO_CONFIG=1" in env
    res = sb.run("uv run --offline python -c 'print(41 + 1)'")
    assert "42" in res.output, res.output
    assert not (outer / "uv.lock").exists() and not (outer / ".venv").exists()
