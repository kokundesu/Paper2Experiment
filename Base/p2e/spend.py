"""Monthly LLM spend of this installation, across every process (the demo server, each run it starts, batches).

Every billed model response is added to a ledger file per calendar month (UTC), under a file lock so parallel runs and
workers add up correctly. When P2E_MONTHLY_BUDGET_USD is set, Budget.check refuses a request once the month's spend
would leave no room for it, so the API keys on a public demo can never cost more than that per month. The demo server
also refuses to draft or start anything once the month is used up.

The ledger only knows what goes through p2e. A provider-side spend limit on the key itself is the backstop for
anything else (a key copied elsewhere, another program using it).
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def ledger_dir() -> Path:
    return Path(os.environ.get("P2E_SPEND_DIR", PROJECT_ROOT / "runs" / ".spend")).expanduser()


def month() -> str:
    return time.strftime("%Y-%m", time.gmtime())


def monthly_limit(of_month: str | None = None) -> float | None:
    """The cap in USD for a month (default: this one), or None when there is none (local research batches).

    P2E_MONTHLY_BUDGET_USD is the usual cap; P2E_MONTHLY_BUDGET_OVERRIDES raises or lowers it for single months,
    as "2026-11=20,2027-01=10", so a one-off month needs no change to come back afterwards."""
    target = of_month or month()
    for item in os.environ.get("P2E_MONTHLY_BUDGET_OVERRIDES", "").split(","):
        key, _, usd = item.strip().partition("=")
        if key.strip() == target and usd.strip():
            return float(usd)
    raw = os.environ.get("P2E_MONTHLY_BUDGET_USD", "").strip()
    return float(raw) if raw else None


@contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield f
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _read(f) -> dict:
    f.seek(0)
    try:
        return json.loads(f.read() or "{}")
    except json.JSONDecodeError:
        return {}


def record(usd: float) -> None:
    """Add one billed response to this month's ledger."""
    if usd <= 0:
        return
    with _locked(ledger_dir() / f"{month()}.json") as f:
        data = _read(f)
        data["usd"] = round(data.get("usd", 0.0) + usd, 6)
        data["requests"] = data.get("requests", 0) + 1
        f.seek(0)
        f.truncate()
        f.write(json.dumps(data))


def spent(of_month: str | None = None) -> float:
    path = ledger_dir() / f"{of_month or month()}.json"
    if not path.is_file():
        return 0.0
    with _locked(path) as f:
        return float(_read(f).get("usd", 0.0))


# Budget.check keeps one large request's worth of room under the cap (its profile's reserve, up to about $0.50
# for the largest models); the page calls the month exhausted at the same point, so a run it lets start can run.
PAGE_RESERVE_USD = 0.5


def status() -> dict:
    """This month's spend and cap, for the page."""
    limit = monthly_limit()
    used = spent()
    return {"month": month(), "spent_usd": round(used, 4), "limit_usd": limit,
            "exhausted": limit is not None and used >= limit - PAGE_RESERVE_USD}


def exhausted_message() -> str:
    return (f"This month's API budget (${monthly_limit() or 0:.2f}) is used up; it resets on the 1st of next month (UTC).")
