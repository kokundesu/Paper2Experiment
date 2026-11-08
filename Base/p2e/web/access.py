"""Who may use the demo server, and who is on it now.

Access code: with P2E_DEMO_CODE set (a shared server), every /api/ call except the code check needs a session cookie,
which POST /api/auth gives for the right code and a name the visitor picks (shown to the others as who is online).
The cookie stays in the browser, so the next visit goes straight in under that name. The code stops working at
P2E_DEMO_CODE_EXPIRES (ISO time), and so do the sessions it gave. A 4-digit code is guessed in 10,000 tries, so wrong tries are limited per address and in total.
Without P2E_DEMO_CODE (a researcher's own machine) nothing is asked.

Presence: each open page says it is there every few seconds (POST /api/presence with a random id per browser); the
people online are the ids heard from in the last PRESENCE_TTL_S seconds.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

from ..runner import RUNS

COOKIE = "p2e_session"
FAILS_PER_ADDRESS = 5          # wrong codes from one address ...
FAIL_WINDOW_S = 15 * 60        # ... within this window lock that address out until the window passes
FAILS_TOTAL_PER_HOUR = 60      # all addresses together: a distributed guesser gets at most this many tries an hour
PRESENCE_TTL_S = 40
NAME_MAX = 24


def code() -> str | None:
    return os.environ.get("P2E_DEMO_CODE") or None


def expires_at() -> float | None:
    raw = os.environ.get("P2E_DEMO_CODE_EXPIRES")
    return datetime.fromisoformat(raw).timestamp() if raw else None


def required() -> bool:
    return code() is not None


def expired(now: float | None = None) -> bool:
    exp = expires_at()
    return exp is not None and (now or time.time()) >= exp


def _secret() -> bytes:
    """The key that signs sessions; kept on disk so a restart does not sign everyone out."""
    path = Path(os.environ.get("P2E_DEMO_SECRET_FILE", RUNS / ".demo_secret"))
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip().encode()


def _sign(payload: str) -> str:
    # the code is part of what is signed: changing P2E_DEMO_CODE ends every session the old code gave
    return hmac.new(_secret(), f"{payload}|{code()}".encode(), hashlib.sha256).hexdigest()


def clean_name(raw: str) -> str | None:
    """The name as shown to others: trimmed, single spaces, no control characters; None when empty."""
    name = " ".join("".join(c for c in str(raw) if c.isprintable()).split())[:NAME_MAX]
    return name or None


def new_session(name: str) -> tuple[str, int]:
    """A cookie value carrying the visitor's name, and its max-age in seconds: valid until the code expires (30 days
    if it never does)."""
    until = int(expires_at() or time.time() + 30 * 86400)
    who = base64.urlsafe_b64encode(name.encode()).decode().rstrip("=")
    payload = f"{until}.{secrets.token_hex(8)}.{who}"
    return f"{payload}.{_sign(payload)}", max(0, until - int(time.time()))


def session_name(cookie_header: str | None) -> str | None:
    """The name of a valid session in these cookies, else None. Without an access code, everyone is "me"."""
    if not required():
        return "me"
    if expired():
        return None
    for part in (cookie_header or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key != COOKIE:
            continue
        payload, _, sig = value.rpartition(".")
        until, _, rest = payload.partition(".")
        _nonce, _, who = rest.partition(".")
        if until.isdigit() and int(until) > time.time() and who and hmac.compare_digest(sig, _sign(payload)):
            try:
                return base64.urlsafe_b64decode(who + "=" * (-len(who) % 4)).decode()
            except (ValueError, UnicodeDecodeError):
                return None
    return None


def valid_session(cookie_header: str | None) -> bool:
    return session_name(cookie_header) is not None


class Guard:
    """Limits on wrong codes, per address and in total."""

    def __init__(self):
        self.lock = threading.Lock()
        self.fails: dict[str, list[float]] = {}
        self.total: list[float] = []

    def retry_after(self, address: str, now: float | None = None) -> int:
        """Seconds until this address may try again (0: now)."""
        now = now or time.time()
        with self.lock:
            mine = [t for t in self.fails.get(address, []) if now - t < FAIL_WINDOW_S]
            self.fails[address] = mine
            self.total = [t for t in self.total if now - t < 3600]
            waits = [0]
            if len(mine) >= FAILS_PER_ADDRESS:
                waits.append(int(mine[0] + FAIL_WINDOW_S - now) + 1)
            if len(self.total) >= FAILS_TOTAL_PER_HOUR:
                waits.append(int(self.total[0] + 3600 - now) + 1)
            return max(waits)

    def failed(self, address: str, now: float | None = None) -> None:
        now = now or time.time()
        with self.lock:
            self.fails.setdefault(address, []).append(now)
            self.total.append(now)

    def tries_left(self, address: str, now: float | None = None) -> int:
        now = now or time.time()
        with self.lock:
            return max(0, FAILS_PER_ADDRESS - len([t for t in self.fails.get(address, []) if now - t < FAIL_WINDOW_S]))


def check_code(guard: Guard, address: str, given: str, name: str | None = "me") -> tuple[int, dict]:
    """(HTTP status, body) for an attempt; 200 means the caller sets the session cookie."""
    if not required():
        return 200, {"ok": True}
    if not name:
        return 400, {"ok": False, "reason": "name"}
    if expired():
        return 403, {"ok": False, "reason": "expired"}
    if (wait := guard.retry_after(address)) > 0:
        return 429, {"ok": False, "reason": "too_many", "retry_after": wait}
    if hmac.compare_digest(str(given).strip(), code() or ""):
        return 200, {"ok": True}
    guard.failed(address)
    return 401, {"ok": False, "reason": "wrong", "tries_left": guard.tries_left(address)}


def status(cookie_header: str | None) -> dict:
    exp = expires_at()
    name = session_name(cookie_header)
    return {"required": required(), "ok": name is not None, "name": name if required() else None,
            "expired": required() and expired(), "expires": datetime.fromtimestamp(exp).astimezone().isoformat() if exp else None}


class Presence:
    """Open pages by browser id, with the name each is signed in under; one person with two tabs counts once."""

    def __init__(self):
        self.lock = threading.Lock()
        self.seen: dict[str, tuple[float, str | None]] = {}

    def ping(self, client: str, name: str | None = None, now: float | None = None) -> None:
        now = now or time.time()
        with self.lock:
            self.seen[client[:64]] = (now, name)

    def people(self, now: float | None = None) -> list[str | None]:
        """Who is online: each name once, plus None for every page without one; names in order of arrival."""
        now = now or time.time()
        with self.lock:
            self.seen = {c: v for c, v in self.seen.items() if now - v[0] < PRESENCE_TTL_S}
            named = list(dict.fromkeys(n for _, n in self.seen.values() if n))
            return named + [None] * sum(1 for _, n in self.seen.values() if not n)

    def online(self, now: float | None = None) -> int:
        return len(self.people(now))
