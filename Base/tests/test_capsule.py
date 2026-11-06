"""CORE-Bench adapter: Hard-level clean-up, safe extraction, snapshot provenance, run setup and scoring (offline)."""
import io
import json
import tarfile
import time

import pytest
import yaml

from p2e import capsule, corebench


def make_capsule(path, files: dict[str, str], top="capsule-0000001", extra=()):
    """A tar.gz shaped like the Hugging Face capsules: one top-level folder; `extra` adds raw TarInfo members."""
    with tarfile.open(path, "w:gz") as tar:
        d = tarfile.TarInfo(top)
        d.type = tarfile.DIRTYPE
        tar.addfile(d)
        for rel, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"{top}/{rel}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for info in extra:
            tar.addfile(info)
    return path


@pytest.mark.parametrize("rel, removed", [
    ("results/output", True), ("code/results/fig.png", True), ("REPRODUCING.md", True),
    ("environment/Dockerfile", True), ("code/run", True), ("code/run.sh", True), ("code/run_all.sh", False),
    ("data/train_x.csv", False), ("data/trainer.py", False), ("data/train.npz", False),  # data stays (paper)
    ("data/cache/big.bin", False), ("code/checkpoint_3.pt", False), ("code/model.ckpt", False),  # unlike HAL
    ("code/__pycache__/a.pyc", True), ("code/main.py", False), ("data/test.csv", False),
    (".codeocean/environment.json", False),
])
def test_hard_cleanup_follows_the_paper(rel, removed):
    assert (capsule.hard_excluded(rel) is not None) == removed


def test_extract_strips_the_top_folder_and_refuses_unsafe_members(tmp_path):
    link = tarfile.TarInfo("capsule-0000001/code/link")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    escape = tarfile.TarInfo("capsule-0000001/../escape.txt")
    archive = make_capsule(tmp_path / "c.tar.gz", {"code/main.py": "print(1)", "results/output": "0.9",
                                                   "REPRODUCING.md": "x"}, extra=[link, escape])
    out = tmp_path / "ws"
    ext = capsule.extract(archive, out)
    assert ext.kept == ["code/main.py"] and set(ext.removed) == {"results/output", "REPRODUCING.md"}
    assert set(ext.refused) == {"code/link", "capsule-0000001/../escape.txt"}
    assert (out / "code/main.py").read_text() == "print(1)" and not (tmp_path / "escape.txt").exists()
    assert not (out / "code/link").exists()


@pytest.mark.parametrize("value, text, found", [
    (96.12, "acc 96.12499135323452", True),   # the answer is a rounding of the printed value
    (96.13, "acc 96.12499135323452", False),
    (85, "macro f1 0.85", True),               # percent of a fraction
    (0.957, "auc=0.957", True),
    (280000, "deaths averted 280000.0", True),
    (0.5, "loss 0.55", False),
])
def test_number_in(value, text, found):
    assert capsule.number_in(value, text) == found


def test_answer_in_strings_lists_and_booleans():
    assert capsule.answer_in("CatBoost", "best model: catboost (macro f1)")
    assert not capsule.answer_in("Boost", "best model: catboost")  # whole words only
    assert capsule.answer_in(True, "IsNGGMatch True") and capsule.answer_in([196000, 364000], "[196000, 364000]")
    assert not capsule.answer_in([196000, 1], "196000")


def test_provenance_separates_run_output_from_files_that_were_already_there(tmp_path):
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    (ws / "data/old_summary.txt").write_text("best accuracy 0.9506\n")
    (ws / "data/notes.txt").write_text("nothing\n")
    before = capsule.snapshot(ws)
    (ws / "results").mkdir()
    (ws / "results/out.txt").write_text("f1 0.81234\n")
    (ws / "data/notes.txt").write_text("rmse 26.21204\n")  # changed during the run: counts as produced
    log = tmp_path / "cmd_001_shell.log"
    log.write_text("Test accuracy: 0.77\n")
    p = capsule.provenance({"f1": 0.8123, "acc": 0.9506, "rmse": 26.21204, "test": 0.77, "x": 0.5}, ws, before, [log])
    assert p["f1"].status == "produced" and p["f1"].produced_in == ["results/out.txt"]
    assert p["acc"].status == "preexisting_only" and p["acc"].preexisting_in == ["data/old_summary.txt"]
    assert p["rmse"].status == "produced" and p["test"].produced_in == ["logs/cmd_001_shell.log"]
    assert p["x"].status == "not_found"


def test_opaque_results_flags_stored_binary_results():
    snap = {"data/Record/ClassificationalResult/musk1+_a_10.npz": {}, "data/Benchmark/musk1+.mat": {},
            "code/model_output.pkl": {}, "data/results_table.csv": {}}
    assert capsule.opaque_results(snap) == ["data/Record/ClassificationalResult/musk1+_a_10.npz"]


ENTRY = {"capsule_id": "capsule-0000001", "capsule_title": "Toy", "field": "Computer Science", "language": "Python",
         "task_prompt": "Run 'main.py'.",
         "results": [{"Which model is best?": "CatBoost", "What is the AUC?": 0.957, "Old accuracy?": 0.9506}] * 3}


def _score(tmp_path, answers, run_output):
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    (ws / "data/old.txt").write_text("accuracy 0.9506\n")
    before = capsule.snapshot(ws)
    log = tmp_path / "cmd_001_shell.log"
    log.write_text(run_output)
    return corebench.score(ENTRY, json.dumps(answers), ws, before, [log])


def test_score_is_full_only_when_every_correct_answer_came_from_the_run(tmp_path):
    answers = {"Which model is best?": "catboost", "What is the AUC?": 0.957, "Old accuracy?": 0.9506}
    r = _score(tmp_path, answers, "best CatBoost auc 0.957 accuracy 0.9506")
    assert r.full and r.verdict == "full" and r.hal_full and not r.shortcut
    r = _score(tmp_path / "b", answers, "best CatBoost auc 0.957")
    assert not r.full and r.full_tolerance_only and r.verdict == "partial"
    assert r.shortcut == ["Old accuracy?"]  # only in a file the capsule shipped with
    r = _score(tmp_path / "c", answers | {"What is the AUC?": 0.95}, "best CatBoost auc 0.957 accuracy 0.9506")
    assert not r.full and not r.full_tolerance_only and r.verdict == "partial"


def test_invalid_report_fails(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r = corebench.score(ENTRY, None, ws, {}, [])
    assert r.verdict == "fail" and not r.valid_report and not r.hal_full


def test_spec_yaml_has_no_answers_and_case_yaml_freezes_tolerances(tmp_path):
    entries = corebench.load_tasks()
    test_ids = corebench.export(entries, out=tmp_path / "test")
    assert test_ids and not {corebench.spec_id(c) for c in corebench.PILOTED} & set(test_ids)  # piloted: not test
    ids = corebench.export(entries, out=tmp_path, split="dev")  # every local task, to check them all
    assert len(ids) == 7 and all(i.startswith("cb-") for i in ids)
    for e in entries:
        if not corebench.suits_local(e):
            continue
        sid = corebench.spec_id(e["capsule_id"])
        spec_text = (tmp_path / sid / "spec.yaml").read_text()
        for run in e["results"]:
            for v in run.values():
                for item in (v if isinstance(v, list) else [v]):
                    if len(str(item)) >= 3:
                        assert str(item) not in spec_text, (sid, item)
        spec = corebench.load_spec(e["capsule_id"], tmp_path)
        assert [q.text for q in spec.questions] == list(e["results"][0]) and spec.origin.source == "corebench"
        case = yaml.safe_load((tmp_path / sid / "case.yaml").read_text())
        assert case["data_sha256"] == corebench.file_sha256(corebench.DATA) and case["split"] == "dev"
        assert [q["id"] for q in case["questions"]] == [q.id for q in spec.questions]
    noisy = yaml.safe_load((tmp_path / "cb-6049678" / "case.yaml").read_text())["questions"][0]["tolerance"]
    assert noisy["term"] == "noise" and noisy["n"] == 3 and noisy["m"] == 1


def test_brief_lists_questions_by_id_without_answers():
    spec = corebench.to_spec(ENTRY)
    text = corebench.brief(spec)
    assert all(f"`{q.id}`" in text and q.text in text for q in spec.questions) and "Run 'main.py'." in text
    assert "0.957" not in text and "CatBoost" not in text and "Do not clone" in text


def test_answer_problems():
    from p2e.spec import AnswerItem, Question, answer_problems
    spec = corebench.to_spec(ENTRY).model_copy(update={"questions": [
        Question(id="q1", text="n?", answer_type="number"), Question(id="q2", text="b?", answer_type="bool"),
        Question(id="q3", text="s?")]})
    ok = [AnswerItem(question_id="q1", value="0.5%"), AnswerItem(question_id="q2", value="True"),
          AnswerItem(question_id="q3", value=[1, "a"])]
    assert answer_problems(spec, ok) == []
    bad = [AnswerItem(question_id="q1", value="high"), AnswerItem(question_id="q9", value=1)]
    problems = answer_problems(spec, bad, not_measured={"q3": "crashed"})
    assert any("expected a number" in p for p in problems) and any("q9" in p for p in problems)
    assert any(p.startswith("q2: no answer") for p in problems) and not any(p.startswith("q3") for p in problems)


def _setup(tmp_path, monkeypatch, files):
    caps, tasks = tmp_path / "capsules", tmp_path / "tasks"
    caps.mkdir()
    make_capsule(caps / "capsule-0000001.tar.gz", files)
    corebench.export([ENTRY], out=tasks)
    data = tmp_path / "core_test.json"
    data.write_text(json.dumps([ENTRY]))
    monkeypatch.setattr(corebench, "RUNS", tmp_path / "runs")
    ctx = corebench.new_run("capsule-0000001", "single", tasks_dir=tasks, capsules=caps)
    return ctx, data


def _answers(**values):
    from p2e.spec import AnswerItem, Answers
    return Answers(answers=[AnswerItem(question_id=k, value=v) for k, v in values.items()])


def test_new_run_and_finish_end_to_end(tmp_path, monkeypatch):
    """Set up a run from a capsule, act as the agent through the sandbox, then score it."""
    ctx, data = _setup(tmp_path, monkeypatch, {
        "code/main.py": "print('best CatBoost'); print('auc 0.957')\n",
        "data/old.txt": "accuracy 0.9506\n", "results/output": "auc 0.957 accuracy 0.9506",
        "REPRODUCING.md": "run main.py", "code/run": "python main.py"})
    assert "`q1`" in ctx.task_brief() and not (ctx.sandbox.workspace / "results").exists()
    assert not (ctx.sandbox.workspace / "REPRODUCING.md").exists() and ctx.baseline_files and ctx.spec
    started = time.monotonic()
    assert ctx.sandbox.run("python3 code/main.py").ok
    result = corebench.finish(ctx, started, answers=_answers(q1="CatBoost", q2=0.957, q3=0.9506), data=data)

    assert result.verdict == "partial" and result.shortcut == ["Old accuracy?"] and result.full_tolerance_only
    summary = json.loads((ctx.run_dir / "summary.json").read_text())
    assert summary["source"] == "corebench" and summary["split"] == "test" and summary["verdict"] == "partial" and summary["code"]
    assert json.loads((ctx.run_dir / "report.json").read_text())["What is the AUC?"] == 0.957
    assert json.loads((ctx.run_dir / "capsule_extraction.json").read_text())["removed"]["results/output"]


def test_a_forged_log_is_not_evidence(tmp_path, monkeypatch):
    ctx, data = _setup(tmp_path, monkeypatch, {"code/main.py": "print('best CatBoost')\n"})
    res = ctx.sandbox.run("python3 code/main.py")
    res.log_path.write_text("best CatBoost auc 0.957 accuracy 0.9506")  # edited after the sandbox wrote it
    result = corebench.finish(ctx, time.monotonic(), answers=_answers(q1="CatBoost", q2=0.957, q3=0.9506), data=data)
    assert set(result.unsupported) == {"What is the AUC?", "Old accuracy?"} and not result.full


def test_no_answers_fails(tmp_path, monkeypatch):
    ctx, data = _setup(tmp_path, monkeypatch, {"code/main.py": "print(1)\n"})
    result = corebench.finish(ctx, time.monotonic(), error="budget", data=data)
    assert result.verdict == "fail" and not result.valid_report


def test_split_log_separates_the_command_from_its_output():
    assert capsule.split_log("$ cd . && echo 0.957\n# exit=0 duration=0.1s\n0.957\n") == ("$ cd . && echo 0.957",
                                                                                           "0.957\n")
    assert capsule.split_log("$ cat x\nBLOCKED: no") == ("$ cat x", "BLOCKED: no")
    assert capsule.split_log("plain text") == ("", "plain text")


def test_answers_the_agent_typed_do_not_count(tmp_path, monkeypatch):
    """An echo into a file, or a script written with write_file that prints a constant, is the agent's own text."""
    from p2e.llm import sandbox_tools
    ctx, data = _setup(tmp_path, monkeypatch, {"code/main.py": "print('best CatBoost')\n"})
    tools = {t.name: t for t in sandbox_tools(ctx.sandbox)}
    assert ctx.sandbox.run("python3 code/main.py").ok
    assert ctx.sandbox.run("mkdir -p results && echo 'auc 0.957' > results/auc.txt").ok
    tools["write_file"].fn({"path": "code/fake.py", "content": "print('accuracy 0.9506')\n"})
    assert ctx.sandbox.authored == {"code/fake.py"}
    assert ctx.sandbox.run("python3 code/fake.py").ok
    result = corebench.finish(ctx, time.monotonic(), answers=_answers(q1="CatBoost", q2=0.957, q3=0.9506), data=data)
    assert set(result.typed) == {"What is the AUC?", "Old accuracy?"} and result.verdict == "partial"
    rows = {r["question"]: r["provenance"] for r in result.questions}
    assert rows["Which model is best?"]["status"] == "produced"
    assert "code/fake.py" in rows["Old accuracy?"]["typed_in"]


def test_installed_packages_are_not_evidence(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    before = capsule.snapshot(ws)
    lib = ws / ".venv/lib/python3.11/site-packages/scipy/tests/data"
    lib.mkdir(parents=True)
    (lib / "iris.arff").write_text("5.1,3.5,1.4,0.2 0.957\n")
    (ws / ".venv/lib/python3.11/site-packages/catboost-1.2.dist-info").mkdir()
    (ws / ".venv/lib/python3.11/site-packages/catboost-1.2.dist-info/METADATA").write_text("Name: CatBoost\n")
    p = capsule.provenance({"auc": 0.957, "model": "CatBoost"}, ws, before, [])
    assert p["auc"].status == "not_found" and p["model"].status == "not_found"


@pytest.mark.parametrize("text, typed", [
    ("$ cd . && uv pip install catboost xgboost", False),  # naming a package is not typing the answer
    ("models = ['CatBoost', 'XGBoost']\nprint(best)\n", False),  # a script that lists candidates
    ("$ cd . && echo 'best: CatBoost'", True),
    ("print('CatBoost')\n", True),
    ("$ cd . && printf 'CatBoost\\n' > answer.txt", True),
])
def test_typed_means_written_out_by_the_agent(text, typed):
    assert capsule.typed_lines(text, "CatBoost") == typed


@pytest.mark.parametrize("text, typed", [
    ("$ cd . && uv venv -p 3.10 .venv 2>&1 | tail -3; uv pip install numpy==1.26.4 catboost==1.2.5 2>&1 | tail -3",
     False),
    ("$ cd . && .venv/bin/python -c \"import sklearn, catboost; print(catboost.__version__)\" 2>&1 | tail -1", False),
    ("$ cd . && python -c \"print('best:', 'CatBoost')\"", True),
    ("$ cd . && echo CatBoost > results/best.txt", True),
])
def test_typed_one_liners(text, typed):
    assert capsule.typed_lines(text, "CatBoost") == typed


def test_a_command_that_echoes_the_answer_does_not_spoil_genuine_output(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    before = capsule.snapshot(ws)
    genuine = tmp_path / "cmd_001_exp.log"
    genuine.write_text("$ cd . && python run.py\n# exit=0 duration=1.0s\nbest model: CatBoost\n")
    echo = tmp_path / "cmd_002_shell.log"
    echo.write_text("$ cd . && echo CatBoost\n# exit=0 duration=0.0s\nCatBoost\n")
    p = capsule.provenance({"m": "CatBoost"}, ws, before, [genuine, echo])
    assert p["m"].status == "produced" and p["m"].produced_in == ["logs/cmd_001_exp.log"]
    p = capsule.provenance({"m": "CatBoost"}, ws, before, [echo])
    assert p["m"].status == "typed"


def test_a_task_with_only_noisy_questions_is_unscored_not_failed(tmp_path):
    entry = {"capsule_id": "capsule-0000009", "results": [{"Noisy AUC?": v} for v in (0.80, 0.95, 1.10)]}
    ws = tmp_path / "ws"
    ws.mkdir()
    r = corebench.score(entry, json.dumps({"Noisy AUC?": 0.95}), ws, {}, [])
    assert r.verdict == "unscored" and not r.full


def test_the_workspace_r_environment_is_never_searched_for_answers():
    assert ".renv" in capsule.ENV_PARTS  # micromamba R environments live at ./.renv (sandbox.py)


def _pdf_with_text(text: str) -> bytes:
    """A one-page PDF whose text layer holds `text` (what R's pdf() device writes for axis labels)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


def test_an_axis_label_read_off_a_produced_pdf_figure_counts_as_produced(tmp_path):
    (tmp_path / "code").mkdir()
    (tmp_path / "code" / "plot.R").write_text('plot(x, y, xlab = "Treatment effect")\n')
    before = capsule.snapshot(tmp_path)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "Figure_A2.pdf").write_bytes(_pdf_with_text("Treatment effect"))
    p = capsule.provenance({"q1": "Treatment effect"}, tmp_path, before, [])["q1"]
    assert p.status == "produced" and "results/Figure_A2.pdf" in p.produced_in


FIG_Q = "fig From the Kitchen plot, report whether humidity and CO2 are positively or negatively correlated."


def _figure_run(tmp_path, preexisting_figure: bool):
    entry = {"capsule_id": "capsule-0000010", "results": [{FIG_Q: "negative", "Mean CO2?": 412.5}] * 3}
    ws = tmp_path / "ws"
    (ws / "results").mkdir(parents=True)
    if preexisting_figure:
        (ws / "results" / "fig5.png").write_bytes(b"\x89PNG shipped")
    before = capsule.snapshot(ws)
    (ws / "results" / "fig5.png").write_bytes(b"\x89PNG shipped" if preexisting_figure else b"\x89PNG made by run")
    (ws / "logs").mkdir()
    log = ws / "logs" / "cmd_001_shell.log"
    log.write_text("$ cd . && Rscript analysis.R\n# exit=0 duration=3.0s\nmean CO2: 412.5\n")
    report = json.dumps({FIG_Q: "negative", "Mean CO2?": 412.5})
    return entry, report, ws, before, [log]


def test_a_figure_answer_read_off_a_figure_the_run_made_counts_as_produced(tmp_path):
    entry, report, ws, before, logs = _figure_run(tmp_path, preexisting_figure=False)
    assert corebench.score(entry, report, ws, before, logs).verdict == "partial"  # the word is in no text
    r = corebench.score(entry, report, ws, before, logs, viewed=["./results/fig5.png"])
    assert r.verdict == "full"
    q = next(q for q in r.questions if q["question"] == FIG_Q)
    assert q["provenance"]["produced_in"] == ["results/fig5.png (viewed figure)"]


def test_looking_at_a_figure_the_capsule_shipped_or_one_that_does_not_exist_proves_nothing(tmp_path):
    entry, report, ws, before, logs = _figure_run(tmp_path, preexisting_figure=True)
    assert corebench.score(entry, report, ws, before, logs, viewed=["results/fig5.png"]).verdict == "partial"
    assert corebench.score(entry, report, ws, before, logs, viewed=["results/fig9.png"]).verdict == "partial"


def test_a_viewed_figure_does_not_credit_a_question_that_is_not_about_a_figure(tmp_path):
    entry = {"capsule_id": "capsule-0000011", "results": [{"Report the accuracy.": 0.91}] * 3}
    ws = tmp_path / "ws"
    ws.mkdir()
    before = capsule.snapshot(ws)
    (ws / "acc.png").write_bytes(b"\x89PNG")
    r = corebench.score(entry, json.dumps({"Report the accuracy.": 0.91}), ws, before, [], viewed=["acc.png"])
    assert r.verdict == "fail" and r.unsupported == ["Report the accuracy."]


def test_after_the_workspace_is_deleted_a_viewed_figure_counts_if_the_snapshot_did_not_have_it(tmp_path):
    gone = tmp_path / "deleted-workspace"
    assert capsule.viewed_figures(["results/fig5.png", "data/map.png", ".renv/x.png"], gone,
                                  {"data/map.png": {"sha256": "x"}}) == ["results/fig5.png"]


def test_viewed_images_are_read_from_the_trace(tmp_path):
    trace = tmp_path / "trace.jsonl"
    calls = [{"name": "view_image", "input": json.dumps({"path": "results/fig5.png"})},
             {"name": "shell", "input": json.dumps({"command": "ls"})},
             {"name": "view_image", "input": {"path": "fig2.png"}}]
    trace.write_text(json.dumps({"event": "response", "tool_calls": calls}) + "\n" + json.dumps({"event": "end"}))
    assert corebench.viewed_images(trace) == ["results/fig5.png", "fig2.png"]
    assert corebench.viewed_images(tmp_path / "missing.jsonl") == []


def test_an_old_run_is_rescored_for_viewed_figures_from_its_saved_files(tmp_path):
    run = tmp_path / "20261031-175815_cb-0000010_single_haiku55"
    run.mkdir()
    fig = {"question": FIG_Q, "vision": True, "correct": True, "scored": True,
           "provenance": {"status": "not_found", "produced_in": []}}
    num = {"question": "Mean CO2?", "vision": False, "correct": True, "scored": True,
           "provenance": {"status": "produced", "produced_in": ["logs/cmd_001_shell.log"]}}
    (run / "eval.json").write_text(json.dumps({"verdict": "partial", "full": False, "unsupported": [FIG_Q],
                                               "questions": [fig, num]}))
    (run / "summary.json").write_text(json.dumps({"verdict": "partial", "unsupported": [FIG_Q]}))
    (run / "capsule_snapshot.json").write_text(json.dumps({"code/analysis.R": {"sha256": "a", "size": 1}}))
    calls = [{"name": "view_image", "input": json.dumps({"path": "results/fig5.png"})}]
    (run / "trace.jsonl").write_text(json.dumps({"event": "response", "tool_calls": calls}) + "\n")
    assert corebench.rescore_viewed_figures(run)
    ev, s = json.loads((run / "eval.json").read_text()), json.loads((run / "summary.json").read_text())
    assert ev["verdict"] == s["verdict"] == "full" and ev["full"] and s["unsupported"] == []
    assert json.loads((run / "summary.pre-figures.json").read_text())["verdict"] == "partial"
    assert not corebench.rescore_viewed_figures(run)  # nothing left to credit
