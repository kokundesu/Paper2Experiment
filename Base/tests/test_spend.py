"""The demo's protections for its API keys: the monthly spend cap shared by every process, commands run as another
user on a server, and the run-file endpoint never leaving the run's workspace."""
import pytest

from p2e import sandbox, spend
from p2e.llm import Budget, BudgetExceeded
from p2e.models import get_profile


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("P2E_SPEND_DIR", str(tmp_path / "spend"))
    return tmp_path / "spend"


def test_spend_adds_up_per_month_across_records(ledger):
    spend.record(0.25)
    spend.record(0.5)
    spend.record(0)  # nothing billed, nothing written
    assert spend.spent() == pytest.approx(0.75)
    assert (ledger / f"{spend.month()}.json").is_file()
    assert spend.spent("1999-01") == 0.0


def test_without_a_cap_nothing_is_refused(ledger, monkeypatch):
    monkeypatch.delenv("P2E_MONTHLY_BUDGET_USD", raising=False)
    spend.record(1000.0)
    Budget(profile=get_profile("haiku55")).check("agent")  # no exception
    assert spend.status()["exhausted"] is False


def test_the_monthly_cap_stops_requests_before_they_cross_it(ledger, monkeypatch):
    monkeypatch.setenv("P2E_MONTHLY_BUDGET_USD", "5")
    budget = Budget(profile=get_profile("haiku55"))
    spend.record(1.0)
    budget.check("agent")  # well under the cap
    spend.record(5.0 - 1.0 - spend.PAGE_RESERVE_USD - 0.01)  # just over one large request left
    budget.check("agent")
    assert spend.status()["exhausted"] is False
    spend.record(spend.PAGE_RESERVE_USD + 0.01 - budget.reserve_usd / 2)  # less than one request left: both agree
    with pytest.raises(BudgetExceeded, match="monthly budget exhausted"):
        budget.check("agent")
    assert spend.status()["exhausted"] is True


def test_a_month_can_have_its_own_cap(monkeypatch):
    monkeypatch.setenv("P2E_MONTHLY_BUDGET_USD", "5")
    monkeypatch.setenv("P2E_MONTHLY_BUDGET_OVERRIDES", "2026-11=20, 2027-01=10")
    assert spend.monthly_limit("2026-11") == 20.0
    assert spend.monthly_limit("2027-01") == 10.0
    assert spend.monthly_limit("2026-12") == 5.0  # back to the usual cap by itself
    monkeypatch.delenv("P2E_MONTHLY_BUDGET_USD")
    assert spend.monthly_limit("2026-12") is None


def test_commands_run_as_this_user_unless_a_command_user_is_set(monkeypatch):
    monkeypatch.setattr(sandbox, "RUN_AS", None)
    assert sandbox.as_runner(["git", "status"]) == ["git", "status"]
    monkeypatch.setattr(sandbox, "RUN_AS", "p2e-run")
    argv = sandbox.as_runner(["/bin/bash", "-c", "echo hi"], {"HOME": "/srv/p2e/home", "PATH": "/usr/bin"})
    assert argv[:5] == ["sudo", "-n", "-u", "p2e-run", "--"]
    # the environment is exactly what the sandbox built (env -i): nothing of this process, so no API key, comes along
    assert argv[5:9] == ["/usr/bin/env", "-i", "HOME=/srv/p2e/home", "PATH=/usr/bin"]
    assert argv[-3:] == ["/bin/bash", "-c", "echo hi"]


def test_the_run_file_endpoint_does_not_follow_a_symlink_out_of_the_workspace(tmp_path, monkeypatch):
    from p2e.web import demo_server
    run = tmp_path / "20260101-000000_user-20260101-000000_single"
    (run / "workspace").mkdir(parents=True)
    (run / "workspace" / "plot.txt").write_text("inside")
    secret = tmp_path / ".env"
    secret.write_text("ANTHROPIC_API_KEY=sk-test")
    (run / "workspace" / "leak.txt").symlink_to(secret)
    monkeypatch.setattr(demo_server, "run_dir_of", lambda key: run)

    sent = {}

    class Fake(demo_server.Handler):
        def __init__(self):  # no socket
            pass

        def _json(self, obj, status=200):
            sent.update(status=status, body=obj)

        def _send(self, data, ctype, status=200):
            sent.update(status=status, body=data)

    Fake()._file("k", "plot.txt")
    assert sent == {"status": 200, "body": b"inside"}
    Fake()._file("k", "leak.txt")
    assert sent["status"] == 404 and b"sk-test" not in repr(sent["body"]).encode()


def test_stopping_a_run_kills_the_command_it_is_executing(tmp_path):
    """Stop on the page ends the run process; the command it was running (its own session, another user on a
    server) must go with it, or it would keep a core busy unattended."""
    import threading
    import time

    sb = sandbox.Sandbox(tmp_path / "run", root=tmp_path / "work")
    results = []
    t = threading.Thread(target=lambda: results.append(sb.run("sleep 30; echo survived", timeout_s=60)))
    t.start()
    for _ in range(100):
        if sb._live:
            break
        time.sleep(0.05)
    assert sb._live
    t0 = time.monotonic()
    sb.kill_live()
    t.join(timeout=10)
    assert results and "survived" not in results[0].output and time.monotonic() - t0 < 10
    assert not sb._live
