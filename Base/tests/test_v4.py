"""v4 dataset in the run format (p2e.v4) and the shortcut check for cloned repositories (p2e.capsule), offline."""
import subprocess

import pytest
import yaml

from p2e import capsule, runner, v4
from p2e.evaluator import evaluate
from p2e.schemas import Case, Metrics, Task


@pytest.mark.parametrize("command, hit", [
    ("cat repo/result.txt", True),
    ("cd repo && grep mse result.txt", True),
    ("python -c \"print(open('repo/result.txt').read())\"", True),
    ("jupyter nbconvert --to html repo/run.ipynb", True),
    ("jupyter nbconvert --to html --execute repo/run.ipynb", False),
    ("cd repo && python3 result.txt.py | tail -n 3", False),
    ("cd repo && python3 train.py --seed 0 | tail -n 3", False),  # runs the shipped script, reads its output
    ("OMP_NUM_THREADS=1 head -5 repo/result.txt", True),
])
def test_shortcut_read_segments(tmp_path, command, hit):
    (tmp_path / "result.txt").write_text("mse:0.158, mae:0.203\n")
    (tmp_path / "train.py").write_text("print('mse:0.158')\n")
    (tmp_path / "run.ipynb").write_text('{"outputs": ["mse:0.158"]}')
    shipped = {"repo/result.txt": tmp_path / "result.txt", "repo/train.py": tmp_path / "train.py",
               "repo/run.ipynb": tmp_path / "run.ipynb"}
    log = f"$ cd . && {command}\n# exit=0 duration=0.1s\nmse:0.158, mae:0.203\n"
    assert bool(capsule.shortcut_read(log, 0.158, shipped)) == hit


def _repo(path):
    path.mkdir()
    (path / "result.txt").write_text("Test accuracy: 0.8100\n")
    (path / "train.py").write_text("print('Test accuracy: 0.8100')\n")
    subprocess.run("git init -q && git add . && git -c user.email=t@t -c user.name=t commit -qm init", shell=True,
                   cwd=path, check=True)


def test_shipped_files_are_tracked_and_unchanged(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _repo(ws / "repo")
    (ws / "repo" / "train.py").write_text("print('changed')\n")
    (ws / "repo" / "new.txt").write_text("untracked\n")
    assert set(capsule.shipped_files(ws)) == {"repo/result.txt"}


def test_evaluator_rejects_values_read_from_a_shipped_file(toy_case, tmp_path):
    case = Case.load(runner.BENCHMARK / "toy")
    ctx = runner.new_run("toy", "single")
    _repo(ctx.sandbox.workspace / "clone")
    honest = [ctx.sandbox.run("python3 clone/train.py") for _ in range(2)]
    lazy = [ctx.sandbox.run("cat clone/result.txt") for _ in range(2)]
    case.claims[0].value = 81.0
    for logs, ok in ((honest, True), (lazy, False)):
        metrics = Metrics.model_validate({"claims": [{"claim_id": "acc", "values": [81.0, 81.0],
                                                      "evidence": [str(r.log_path.relative_to(ctx.run_dir)) for r in logs]}]})
        verdict = evaluate(case, metrics, ctx.run_dir, "single", manifest=dict(ctx.sandbox.manifest)).claims[0]
        assert verdict.evidence_ok == ok
        if not ok:
            assert "shipped with the repository" in verdict.reason and "clone/result.txt" in verdict.reason


def test_convert_ready_papers(tmp_path):
    pids = v4.ready()
    assert {"ecod", "fairbatch"} <= set(pids)  # ngboost is absent while its reference is being rebuilt
    for pid in [p for p in ("ecod", "ngboost") if p in pids]:
        out = v4.convert(pid, out_root=tmp_path)
        task = Task.load(out)
        case = Case.load(out)
        task_text = (out / "task.yaml").read_text()
        for c in case.claims:
            assert c.target == "reference" and f"{c.value}" not in task_text and f"{c.paper_value}" not in task_text
        assert task.seeds == 3 and case.min_seeds == 3 and (out / task.paper_pdf).exists()
    if "ngboost" in pids:  # NLL varies too much between split sets to score
        ng = {c.id: c for c in Case.load(tmp_path / "v4-ngboost").claims}
        assert not ng["concrete_ngboost_rmse"].diagnostic_only
    ecod = Case.load(tmp_path / "v4-ecod")
    assert {d.claim_id for d in ecod.discrepancies} == {"cardio_ecod_roc_auc", "mammography_ecod_roc_auc"}
    assert yaml.safe_load((tmp_path / "v4-ecod" / "case.yaml").read_text())["source"]["split"] == "dev"


def test_criteria_name_the_reference_target(tmp_path):
    out = v4.convert("ecod", out_root=tmp_path)
    crit = runner._criteria(out, Task.load(out))
    assert all("official code gives on this machine" in c and "paper value" not in c for c in crit.values())


def test_split_is_15_dev_5_test_and_disjoint():
    dev, test = set(v4.members("dev")), set(v4.members("test"))
    assert len(dev) == 15 and len(test) == 5 and not dev & test


def test_shortcut_check_survives_a_discarded_workspace(toy_case):
    case = Case.load(runner.BENCHMARK / "toy")
    case.claims[0].value = 81.0
    ctx = runner.new_run("toy", "single")
    _repo(ctx.sandbox.workspace / "clone")
    lazy = [ctx.sandbox.run("cat clone/result.txt") for _ in range(2)]
    honest = ctx.sandbox.run("python3 clone/train.py")
    reads = capsule.save_shipped_reads(ctx.run_dir, ctx.sandbox.workspace,
                                       [ctx.sandbox.log_dir / n for n in ctx.sandbox.manifest])
    assert set(reads) == {f"logs/{r.log_path.name}" for r in lazy} and honest.log_path.name not in str(reads)
    ctx.sandbox.discard_workspace()
    assert not (ctx.run_dir / "workspace").exists()
    metrics = Metrics.model_validate({"claims": [{"claim_id": "acc", "values": [81.0, 81.0],
                                                  "evidence": [str(r.log_path.relative_to(ctx.run_dir)) for r in lazy]}]})
    verdict = evaluate(case, metrics, ctx.run_dir, "single", manifest=dict(ctx.sandbox.manifest)).claims[0]
    assert not verdict.evidence_ok and "shipped with the repository" in verdict.reason


def test_identical_values_do_not_count_when_the_official_code_varies(tmp_path):
    from p2e.sandbox import Sandbox
    from p2e.schemas import ClaimMeasurement, GroundTruthClaim
    sb = Sandbox(tmp_path)
    log = sb.run("python3 -c \"print('epoch 1 loss 0.5'); print('acc', 0.9 + 0.0364)\"").log_path
    ev = [f"logs/{log.name}"] * 3
    for spread, ok in ((0.002, False), (0.0, True)):
        case = Case(id="t", rubric={"min_seeds": 3}, claims=[GroundTruthClaim(
            id="a", metric="acc", setting="x", value=0.9364, tolerance={"abs": 0.004}, target="reference",
            ref_spread=spread)])
        m = Metrics(claims=[ClaimMeasurement(claim_id="a", values=[0.9364] * 3, evidence=ev)])
        v = evaluate(case, m, tmp_path, "w", manifest=sb.manifest).claims[0]
        assert v.within_tolerance == ok, spread
        assert ("seeds did not change the run" in v.reason) == (not ok)
