"""The shared demo server: the access code and its sessions, who is online, and the queue of runs."""
import pytest

from p2e.web import access


@pytest.fixture
def code(tmp_path, monkeypatch):
    monkeypatch.setenv("P2E_DEMO_CODE", "6008")
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
    assert access.check_code(access.Guard(), "1.2.3.4", "6008", "Allen") == (403, {"ok": False, "reason": "expired"})


def test_a_name_is_needed_and_cleaned(code):
    assert access.check_code(access.Guard(), "1.2.3.4", "6008", None)[1]["reason"] == "name"
    assert access.clean_name("  Al\x00len   Hu  ") == "Allen Hu"
    assert access.clean_name("   ") is None
    assert len(access.clean_name("x" * 100)) == access.NAME_MAX


def test_wrong_codes_lock_an_address_out_then_let_it_back(code):
    guard = access.Guard()
    for left in range(access.FAILS_PER_ADDRESS - 1, -1, -1):
        status, body = access.check_code(guard, "1.2.3.4", "0000", "Allen")
        assert status == 401 and body["tries_left"] == left
    status, body = access.check_code(guard, "1.2.3.4", "6008", "Allen")  # even the right code waits
    assert status == 429 and body["retry_after"] > 0
    assert access.check_code(guard, "5.6.7.8", "6008", "Bea")[0] == 200  # another address is not affected
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
