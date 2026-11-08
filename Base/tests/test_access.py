"""The shared demo server: the access code and its sessions, who is online, and the queue of runs."""
import pytest

from p2e.web import access


@pytest.fixture
def code(tmp_path, monkeypatch):
    monkeypatch.setenv("P2E_DEMO_CODE", "2468")
    monkeypatch.setenv("P2E_DEMO_CODE_EXPIRES", "2999-01-01T00:00:00+00:00")
    monkeypatch.setenv("P2E_DEMO_SECRET_FILE", str(tmp_path / "secret"))


def cookie(value: str) -> str:
    return f"theme=dark; {access.COOKIE}={value}"


def test_without_a_code_everyone_is_in(monkeypatch):
    monkeypatch.delenv("P2E_DEMO_CODE", raising=False)
    assert access.valid_session(None)
    assert access.check_code(access.Guard(), "1.2.3.4", "anything", None)[0] == 200


def test_a_session_carries_the_name_and_only_a_signed_one_counts(code):
    value, age = access.new_session("小明 Allen")
    assert age > 0
    assert access.session_name(cookie(value)) == "小明 Allen"
    until, nonce, who, sig = value.split(".")
    forged = ".".join([until, nonce, who, "0" * len(sig)])
    assert access.session_name(cookie(forged)) is None
    assert access.session_name(None) is None


def test_changing_the_code_ends_the_old_sessions(code, monkeypatch):
    value, _ = access.new_session("Allen")
    monkeypatch.setenv("P2E_DEMO_CODE", "1111")
    assert access.session_name(cookie(value)) is None


def test_the_code_and_its_sessions_stop_at_the_expiry(code, monkeypatch):
    value, _ = access.new_session("Allen")
    monkeypatch.setenv("P2E_DEMO_CODE_EXPIRES", "2000-01-01T00:00:00+00:00")
    assert access.session_name(cookie(value)) is None
    assert access.check_code(access.Guard(), "1.2.3.4", "2468", "Allen") == (403, {"ok": False, "reason": "expired"})


def test_a_name_is_needed_and_cleaned(code):
    assert access.check_code(access.Guard(), "1.2.3.4", "2468", None)[1]["reason"] == "name"
    assert access.clean_name("  Al\x00len   Hu  ") == "Allen Hu"
    assert access.clean_name("   ") is None
    assert len(access.clean_name("x" * 100)) == access.NAME_MAX


def test_wrong_codes_lock_an_address_out_then_let_it_back(code):
    guard = access.Guard()
    for left in range(access.FAILS_PER_ADDRESS - 1, -1, -1):
        status, body = access.check_code(guard, "1.2.3.4", "0000", "Allen")
        assert status == 401 and body["tries_left"] == left
    status, body = access.check_code(guard, "1.2.3.4", "2468", "Allen")  # even the right code waits
    assert status == 429 and body["retry_after"] > 0
    assert access.check_code(guard, "5.6.7.8", "2468", "Bea")[0] == 200  # another address is not affected
    assert guard.retry_after("1.2.3.4", now=__import__("time").time() + access.FAIL_WINDOW_S + 1) == 0


def test_presence_counts_each_name_once_and_forgets_closed_pages():
    p = access.Presence()
    p.ping("tab-a", "Allen", now=100)
    p.ping("tab-b", "Allen", now=100)  # a second tab of the same person
    p.ping("tab-c", "Bea", now=110)
    p.ping("tab-d", None, now=110)
    assert p.people(now=115) == ["Allen", "Bea", None]
    assert p.people(now=100 + access.PRESENCE_TTL_S + 1) == ["Bea", None]


def test_runs_beyond_the_limit_wait_in_line_and_start_in_order(tmp_path, monkeypatch):
    from p2e import demo
    from p2e.spec import ReproSpec
    from p2e.web import demo_server

    monkeypatch.setenv("P2E_DEMO_MAX_RUNS", "1")
    monkeypatch.setenv("P2E_WORKSPACE_ROOT", str(tmp_path / "work"))
    monkeypatch.setattr(demo, "DRAFTS", tmp_path)

    class FakeProc:
        def __init__(self, *a, **k):
            self.done = False

        def poll(self):
            return 0 if self.done else None

    started = []
    monkeypatch.setattr(demo_server.subprocess, "Popen", lambda cmd, **k: started.append(cmd) or FakeProc())
    jobs = demo_server.Jobs.__new__(demo_server.Jobs)  # without the dispatch thread: dispatch by hand
    jobs.procs, jobs.queue, jobs.cancelled = {}, [], set()
    jobs.lock = demo_server.threading.Lock()

    def spec(i):
        return ReproSpec.model_validate({"id": f"user-2026010{i}-000000", "title": "t", "objective": "o", "task_prompt": "p",
                                         "language": "Python", "code": {"repo_url": "https://github.com/a/b"},
                                         "questions": [{"id": "q1", "text": "q", "answer_type": "number"}],
                                         "origin": {"source": "user", "prompt": "p"}})

    a, b, c = (jobs.start(spec(i), "single", "haiku55") for i in (1, 2, 3))
    assert len(started) == 1 and jobs.counts() == {"running": 1, "queued": 2, "max_running": 1}
    assert jobs.position(a) is None and jobs.position(b) == 1 and jobs.position(c) == 2
    assert jobs.stop(c) and jobs.was_cancelled(c) and jobs.position(c) is None  # leaving the line
    jobs.procs[a].done = True
    with jobs.lock:
        jobs._dispatch()
    assert len(started) == 2 and jobs.position(b) is None and jobs.counts()["queued"] == 0


def test_each_person_runs_in_a_folder_named_after_them(code, tmp_path, monkeypatch):
    from p2e.web import demo_server

    monkeypatch.setenv("P2E_WORKSPACE_ROOT", str(tmp_path / "work"))
    monkeypatch.delenv("P2E_DEMO_FIXED_WORKDIR", raising=False)
    monkeypatch.setattr(demo_server, "SETTINGS", tmp_path / "settings.json")
    assert demo_server.run_folder("Allen") == tmp_path / "work"  # on one's own machine: one folder for every run
    assert demo_server.cleanup_after_s() is None
    monkeypatch.setenv("P2E_DEMO_FIXED_WORKDIR", "1")
    assert demo_server.run_folder("Allen Hu") == tmp_path / "work" / "Allen_Hu"
    assert demo_server.run_folder("张三").name == "张三"
    assert demo_server.run_folder("../../etc").parent == tmp_path / "work"  # a name never leads out of the root
    assert demo_server.cleanup_after_s() == 30 * 60
    state = demo_server.workdir_state("Allen Hu", with_runs=True)
    assert state["fixed"] and state["name"] == "Allen_Hu" and state["cleanup_min"] == 30 and state["runs"] == []
    assert "runs" not in demo_server.workdir_state("Allen Hu")  # the page load does not walk the folders
    with pytest.raises(ValueError, match="fixed"):
        demo_server.set_run_folder(str(tmp_path / "elsewhere"))


def test_a_finished_runs_workspace_is_cleaned_after_the_delay_and_a_live_one_never(tmp_path, monkeypatch):
    import os
    import time

    from p2e.web import demo_server

    work, runs = tmp_path / "work", tmp_path / "runs"
    monkeypatch.setenv("P2E_WORKSPACE_ROOT", str(work))
    monkeypatch.setenv("P2E_DEMO_FIXED_WORKDIR", "1")
    monkeypatch.setattr(demo_server, "RUNS", runs)
    live_key = "user-20261108-120000_planner_workers"

    class Alive:
        def alive(self, key):
            return key == live_key

    monkeypatch.setattr(demo_server, "JOBS", Alive())
    now = time.time()

    def run(folder, name, idle_min):
        home = folder / name
        (home / "workspace" / ".venv").mkdir(parents=True)
        (home / "workspace" / ".venv" / "big.bin").write_bytes(b"x" * 2_000_000)
        d = runs / name
        d.mkdir(parents=True)
        (d / "spec.json").write_text('{"title": "Some task"}')
        (d / "trace.jsonl").write_text("{}")
        os.utime(d / "trace.jsonl", (now - idle_min * 60,) * 2)
        (d / "workspace").symlink_to(home / "workspace")
        return home, d

    old, old_dir = run(work / "Allen", "20261108-100000_user-20261108-100000_planner_workers", idle_min=45)
    recent, _ = run(work / "Allen", "20261108-110000_user-20261108-110000_planner_workers", idle_min=10)
    live, _ = run(work / "Bo", f"20261108-120001_{live_key}", idle_min=90)  # a long silent training step
    flat, _ = run(work, "20261107-090000_user-20261107-090000_single", idle_min=600)  # from before per-person folders
    # a person whose name looks like a run name: their folder is not a run's workspace, so never cleaned as one
    odd_person = work / "20261108-130000_x"
    odd, _ = run(odd_person, "20261108-130001_user-20261108-130001_single", idle_min=10)
    os.utime(odd_person, (now - 600 * 60,) * 2)
    stray = work / "Allen" / "20261108-140000_user-20261108-140000_single"  # no run record: not ours to judge
    stray.mkdir()

    listed = demo_server.workdir_state("Allen", with_runs=True)["runs"]
    assert [r["run"] for r in listed] == [recent.name, old.name] and listed[0]["size_mb"] == 2.0
    assert 19 * 60 < listed[0]["cleans_in_s"] <= 20 * 60 and listed[1]["cleans_in_s"] == 0
    assert demo_server.workdir_state("Bo", with_runs=True)["runs"][0]["live"] is True

    cleaned = demo_server.clean_workspaces(now)
    assert sorted(cleaned) == sorted([old.name, flat.name])
    assert not old.exists() and not flat.exists() and recent.exists() and live.exists()
    assert odd.exists() and odd_person.exists() and stray.exists()
    assert old_dir.is_dir() and not (old_dir / "workspace").exists()  # the record stays, only the workspace goes
    assert sorted(demo_server.clean_workspaces(now + 25 * 60)) == sorted([recent.name, odd.name])  # both 35 min idle now


def test_history_shows_ones_own_runs_unless_everyones_is_asked_for(tmp_path, monkeypatch):
    import json

    from p2e.web import demo_server

    runs = tmp_path / "runs"
    monkeypatch.setattr(demo_server, "RUNS", runs)
    monkeypatch.setattr(demo_server, "JOBS", type("J", (), {"alive": lambda self, k: False})())
    for stamp, owner in (("20261108-100000", "Allen"), ("20261108-110000", "Bea"), ("20261107-090000", "")):
        d = runs / f"{stamp}_user-{stamp}_single"
        d.mkdir(parents=True)
        (d / "spec.json").write_text(json.dumps({"id": f"user-{stamp}", "title": f"run of {owner or 'nobody'}",
                                                 "questions": [], "origin": {"source": "user", "owner": owner}}))
    own = demo_server.list_history(user="Allen")
    assert [r["title"] for r in own] == ["run of Allen"] and own[0]["owner"] == "Allen"
    everyone = demo_server.list_history(user="Allen", everyone=True)
    assert [r["owner"] for r in everyone] == ["Bea", "Allen", ""]  # newest first; the unowned run from before names
    assert len(demo_server.list_history()) == 3  # one's own machine: no names, every run
