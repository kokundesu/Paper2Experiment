"""Intent stage and GT stage (p2e.intent), offline: scripted models, no network."""
import yaml

from p2e import intent
from p2e.testing import FakeClient, use_fake

PAGES = ["Intro text. BSPM blurs and sharpens.", "Table 4: Results on Gowalla.\nBSPM-EM 0.1920 0.1597\nLightGCN 0.1830"]
ENTRY = {"id": "toy", "arxiv": "0000.00000", "repo": "https://github.com/x/y",
         "prompt": "复现 BSPM 在 Gowalla 上 BSPM-EM 的 Recall@20 和 NDCG@20（表 4）"}
Q = [{"id": "recall20", "text": "Recall@20 of BSPM-EM on Gowalla", "metric": "Recall@20", "direction": "higher",
      "locator": "Table 4, row BSPM-EM, column Recall@20", "setting": "Gowalla", "runs": 1},
     {"id": "ndcg20", "text": "NDCG@20 of BSPM-EM on Gowalla", "metric": "NDCG@20", "direction": "higher",
      "locator": "Table 4, row BSPM-EM, column NDCG@20", "setting": "Gowalla", "runs": 1}]


def item(qid, **kw):
    return {"question_id": qid, "in_scope": "yes", "locator_ok": "yes", "underspecified": ["none"],
            "answer_type_ok": "yes", "measurable": "yes", **kw}


def gt(qid, value, quote="BSPM-EM 0.1920 0.1597", page=2):
    return {"question_id": qid, "value": value, "quote": quote, "page": page}


def fake_inputs(entry, out):
    return intent.Inputs(entry, intent.select_pages(PAGES, entry["prompt"]), PAGES, "README: run main.py", ["main.py"])


def test_missing_repository_info_stops_the_paper(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(intent, "gather", lambda e, o: intent.Inputs(e, "p", ["p"], "", [], ["README: HTTP 403"]))
    with pytest.raises(RuntimeError, match="repository info unavailable"):
        intent.run_paper(ENTRY, intent.Roles(), out_root=tmp_path)


def run(tmp_path, monkeypatch, draft_q=Q, checks=None, extracts=None):
    monkeypatch.setattr(intent, "gather", fake_inputs)
    checks = checks or [[item("recall20"), item("ndcg20")], [item("recall20"), item("ndcg20")]]
    extracts = extracts or [[gt("recall20", 0.192), gt("ndcg20", 0.1597)], [gt("recall20", 0.192), gt("ndcg20", 0.1597)]]
    fake = FakeClient({
        intent.DRAFT_SYSTEM[:30]: [[("submit", {"understanding": "u", "questions": draft_q})]],
        intent.CHECK_SYSTEM[:30]: [[("submit", {"items": c})] for c in checks],
        intent.EXTRACT_SYSTEM[:30]: [[("submit", {"items": e})] for e in extracts]})
    use_fake(monkeypatch, fake)
    return intent.run_paper(ENTRY, intent.Roles(), out_root=tmp_path)


def test_agreed_values_and_a_clean_spec(tmp_path, monkeypatch):
    r = run(tmp_path, monkeypatch)
    assert r.queue == [] and r.gt["recall20"]["status"] == "agreed"
    assert r.gt["recall20"]["printed"] == "0.1920" and r.gt["recall20"]["precision"] == 4  # trailing zero kept
    spec_text = (tmp_path / "toy" / "spec.yaml").read_text()
    assert "0.192" not in spec_text and "0.1597" not in spec_text and "recall20" in spec_text
    assert yaml.safe_load((tmp_path / "toy" / "gt.yaml").read_text())["values"]["ndcg20"]["paper_value"] == 0.1597


def test_one_checker_flag_is_a_note_both_flags_go_to_the_user(tmp_path, monkeypatch):
    one = [[item("recall20"), item("ndcg20")],
           [item("recall20"), item("ndcg20", underspecified=["variant"], comment="BSPM-EM or BSPM-LM?")]]
    r = run(tmp_path, monkeypatch, checks=one)
    assert not [i for i in r.queue if i["kind"] == "question"]
    assert r.notes[0]["question_id"] == "ndcg20" and "BSPM-LM" in r.notes[0]["notes"][0]
    both = [[item("recall20"), item("ndcg20", underspecified=["variant", "runs"], comment="EM or LM?")],
            [item("recall20"), item("ndcg20", underspecified=["variant"], comment="BSPM-EM or BSPM-LM?")]]
    r = run(tmp_path / "b", monkeypatch, checks=both)
    q = [i for i in r.queue if i["kind"] == "question"]
    assert [i["question_id"] for i in q] == ["ndcg20"] and "variant" in q[0]["reasons"][0]
    assert "ndcg20" in intent.clarifications_md([r])


def test_out_of_scope_by_one_checker_and_draft_issues_go_to_the_user(tmp_path, monkeypatch):
    checks = [[item("recall20"), item("ndcg20", in_scope="no")], [item("recall20"), item("ndcg20")]]
    draft = [dict(Q[0]), dict(Q[1])]
    r = run(tmp_path, monkeypatch, checks=checks, draft_q=draft)
    assert [i["question_id"] for i in r.queue if i["kind"] == "question"] == ["ndcg20"]


def test_runs_and_cpu_doubts_never_block(tmp_path, monkeypatch):
    checks = [[item("recall20", underspecified=["runs"], measurable="unclear"), item("ndcg20")],
              [item("recall20", underspecified=["runs"]), item("ndcg20")]]
    r = run(tmp_path, monkeypatch, checks=checks)
    assert r.queue == [] and r.notes[0]["question_id"] == "recall20"


def test_disagreeing_or_unverifiable_values_are_not_ground_truth(tmp_path, monkeypatch):
    extracts = [[gt("recall20", 0.192), gt("ndcg20", 0.1597)],
                [gt("recall20", 0.193, quote="BSPM-EM 0.193"), gt("ndcg20", 0.1579, quote="BSPM-EM 0.1920 0.1579")]]
    r = run(tmp_path, monkeypatch, extracts=extracts)
    assert r.gt["recall20"]["status"] == "conflict" and r.gt["ndcg20"]["status"] == "conflict"  # values differ
    assert r.gt["ndcg20"]["votes"]["luna"]["why"] == "quote not found in the paper text"
    assert {i["question_id"] for i in r.queue if i["kind"] == "value"} == {"recall20", "ndcg20"}


def test_same_value_one_good_quote_is_agreed_partial(tmp_path, monkeypatch):
    extracts = [[gt("recall20", 0.192), gt("ndcg20", 0.1597)],
                [gt("recall20", 0.192, quote="LightGCN 0.1920"), gt("ndcg20", 0.1597)]]
    r = run(tmp_path, monkeypatch, extracts=extracts)
    assert r.gt["recall20"]["status"] == "agreed_partial" and r.gt["recall20"]["paper_value"] == 0.192


def test_a_question_that_prints_its_value_is_a_leak(tmp_path, monkeypatch):
    leaky = [dict(Q[0], text="Recall@20 of BSPM-EM on Gowalla (paper: 0.1920)"), Q[1]]
    r = run(tmp_path, monkeypatch, draft_q=leaky)
    assert any(i["kind"] == "leak" and "0.1920" in i["text"] for i in r.queue)


def test_roles_need_other_providers():
    assert intent.Roles().problems() == []
    assert intent.Roles(drafter="sol", checkers=("luna",)).problems()
    assert intent.Roles(extractors=("haiku55", "sonnet55")).problems()


def test_select_pages_keeps_named_tables_first():
    pages = ["a" * 100, "b" * 100, "Table 10: full results " + "c" * 50]
    text = intent.select_pages(pages, "附录表 10", limit=200)
    assert "Table 10" in text and "=== page 1 ===" in text and "=== page 2 ===" not in text


def test_printed_number_and_verify():
    assert intent.printed_number(0.192, "BSPM-EM 0.1920 0.1597") == "0.1920"
    assert intent.printed_number(0.19, "0.1920") is None
    ok, why, tok = intent.verify(intent.GTItem(question_id="q", value=67.48, quote="GPRGNN 67.48±0.40"),
                                 ["Table 2 ... GPRGNN 67.48±0.40 ..."])
    assert ok
    # a row label the PDF text puts elsewhere, written back in front of the row's cells
    ok, _, _ = intent.verify(intent.GTItem(question_id="q", value=71.11, quote="Autoscale Plain Linear 71.11 80.24 88.62"),
                             ["Prediction MLP 71.51\nPlain Linear 71.11 80.24 88.62 76.31\nAutoscale Linear 72.07"])
    assert ok
    ok, why, _ = intent.verify(intent.GTItem(question_id="q", value=71.11, quote="Autoscale Plain Linear 71.11"),
                               ["Plain Linear 71.11"])
    assert not ok  # one number alone is not distinctive enough and tok == "67.48"
    # pypdf quirks: '93 .27', and a quote that joins two table lines
    ok, _, tok = intent.verify(intent.GTItem(question_id="q", value=93.27, quote="79.73 ± 0.31 93 .27 ± 0.08"),
                               ["APPNP 75.73 ± 0.30 79.73 ± 0.31 93 .27 ± 0.08"])
    assert ok and tok == "93.27"
    ok, _, _ = intent.verify(intent.GTItem(question_id="q", value=0.9279, quote="MNIST:1k NN 0.9252\nGP-20 0.9279"),
                             ["MNIST:1k NN 0.9252 NN-2 0.9254\nGP-20 0.9279 GP-20 0.9266"])
    assert ok


def test_revise_reextracts_and_freeze_hashes(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch)
    monkeypatch.setattr(intent, "paper_text", lambda arxiv, d: PAGES)
    fake = FakeClient({intent.EXTRACT_SYSTEM[:30]: [
        [("submit", {"items": [gt("recall20_lm", 0.1830, quote="LightGCN 0.1830")]})],
        [("submit", {"items": [gt("recall20_lm", 0.1830, quote="LightGCN 0.1830")]})]]})
    use_fake(monkeypatch, fake)
    res = intent.revise(ENTRY, {"recall20": {"id": "recall20_lm", "text": "Recall@20 of LightGCN on Gowalla",
                                             "locator": "Table 4, row LightGCN"}}, out_root=tmp_path)
    assert res["values"]["recall20_lm"]["printed"] == "0.1830"
    spec = yaml.safe_load((tmp_path / "toy" / "spec.yaml").read_text())
    assert [q["id"] for q in spec["questions"]] == ["recall20_lm", "ndcg20"]
    manifest = intent.freeze([ENTRY], {"papers": {}}, out_root=tmp_path)
    assert manifest["papers"]["toy"]["questions"] == ["recall20_lm", "ndcg20"]
    assert yaml.safe_load((tmp_path / "toy" / "spec.yaml").read_text())["origin"]["user_confirmed"]
    assert intent.check_frozen(tmp_path) == []
    (tmp_path / "toy" / "gt.yaml").write_text("changed")
    assert intent.check_frozen(tmp_path) == ["toy/gt.yaml"]


def test_freeze_refuses_unresolved_values(tmp_path, monkeypatch):
    import pytest
    extracts = [[gt("recall20", 0.192), gt("ndcg20", 0.1597)], [gt("recall20", 0.193, quote="x 0.193"),
                                                               gt("ndcg20", 0.1597)]]
    run(tmp_path, monkeypatch, extracts=extracts)
    with pytest.raises(ValueError, match="recall20: no agreed value"):
        intent.freeze([ENTRY], {"papers": {}}, out_root=tmp_path)


def test_update_fields_keeps_values_and_refuses_value_fields(tmp_path, monkeypatch):
    import pytest
    run(tmp_path, monkeypatch)
    intent.update_fields(ENTRY, {"runs": 3}, "一次运行 = 完整协议。", out_root=tmp_path)
    intent.update_fields(ENTRY, {"runs": 3}, "一次运行 = 完整协议。", out_root=tmp_path)  # idempotent
    spec = yaml.safe_load((tmp_path / "toy" / "spec.yaml").read_text())
    assert [q["runs"] for q in spec["questions"]] == [3, 3]
    assert spec["questions"][0]["setting"].count("完整协议") == 1
    with pytest.raises(ValueError, match="use revise"):
        intent.update_fields(ENTRY, {"locator": "Table 9"}, out_root=tmp_path)
