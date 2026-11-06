"""Reference re-runs (p2e.reference), offline: a toy script stands in for the official code."""
import pytest
import yaml

from p2e import reference

SCRIPT = """import sys, os
seed = int(sys.argv[sys.argv.index('--seed') + 1])
print(f'epoch 1 loss 0.5')
print(f'Test accuracy: {0.80 + 0.001 * seed:.4f}')
print(f'threads={os.environ.get("OMP_NUM_THREADS", "default")}')
"""


def recipe(tmp_path, **kw):
    (tmp_path / "toy.py").write_text(SCRIPT)
    return reference.Recipe(id="toy", repo="local", setup=[f"cp {tmp_path / 'toy.py'} ."],
                            command="python3 toy.py --seed {seed}",
                            metrics={"acc": reference.MetricRule(regex=r"Test accuracy: ([0-9.]+)", scale=100)}, **kw)


def test_recipe_problems():
    r = reference.Recipe(id="x", repo="r", command="python run.py", metrics={"a": reference.MetricRule(regex="(a)(b)")})
    problems = r.problems(["a", "b"])
    assert any("{seed}" in p for p in problems) and any("['b']" in p for p in problems)
    assert any("exactly one capture group" in p for p in problems)


def test_run_alternates_threads_and_parses_values(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    ref = reference.run(recipe(tmp_path), ["acc"], out, runs_root=tmp_path / "runs")
    assert ref["values"]["acc"] == pytest.approx([80.0, 80.1, 80.2, 80.3, 80.4])
    assert [r["threads"] for r in ref["runs"]] == ["default", "1", "default", "1", "default"]
    assert ref["printed_places"]["acc"] == 4 and (out / "reference_values.yaml").exists()
    assert not (tmp_path / "runs" / ref["run_dir"].split("/")[-1] / "workspace").exists()  # environment discarded
    assert len(list((tmp_path / "runs").glob("*/logs/*.log"))) == 6  # the logs stay


def test_finalize_scored_mismatch_and_stochastic(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    ref = reference.run(recipe(tmp_path), ["acc"], out, runs_root=tmp_path / "runs")
    case = reference.finalize("toy", ref, {"acc": {"paper_value": 80.3, "precision": 1}})
    q = case["questions"]["acc"]
    # s = 0.158, t(4) = 2.776, sqrt(1/3 + 1/5) = 0.730: noise ~ 0.32 > precision 0.05
    assert q["status"] == "scored" and q["term"] == "noise" and q["h"] == pytest.approx(0.320, abs=0.01)
    far = reference.finalize("toy", ref, {"acc": {"paper_value": 85.0, "precision": 1}})
    assert far["questions"]["acc"]["status"] == "paper_mismatch"
    noisy = dict(ref, values={"acc": [1.0, 2.0, 3.0, 1.5, 2.5]})
    assert reference.finalize("toy", noisy, {"acc": {"paper_value": 2.0, "precision": 1}}
                              )["questions"]["acc"]["status"] == "stochastic"
    one = dict(ref, values={"acc": [80.0]})
    assert reference.finalize("toy", one, {"acc": {"paper_value": 80.0}})["questions"]["acc"]["status"] == \
        "no_reference"


def test_paper_spread_widens_the_mismatch_check():
    g = {"reported_spread": 0.4, "spread_over": "splits", "n_runs": 100}
    assert reference.paper_half_width(g, noise=0.1, precision=0.005) == pytest.approx(0.08)
    assert reference.paper_half_width({}, noise=0.1, precision=0.005) == pytest.approx(0.105)


def test_failed_setup_stops(tmp_path):
    r = recipe(tmp_path).model_copy(update={"setup": ["exit 3"]})
    with pytest.raises(RuntimeError, match="setup failed"):
        reference.run(r, ["acc"], tmp_path, runs_root=tmp_path / "runs")
