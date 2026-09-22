"""Access passes for the hosted demo: who may spend the owner's OpenAI key, and how much.

A visitor without a pass gets the public replay and nothing else. A pass holder opens a personal
link (<site>/?pass=<code>); the web app trades the code for a signed session cookie and can then
onboard and measure live, up to the pass's dollar cap.

Every OpenAI call in the app goes through `openai_response`, which refuses before the call when the
acting pass is capped or revoked and charges the usage the response reports afterwards. The acting
pass travels in a ContextVar; on the public demo a call with no pass set is refused, so a code path
that forgot to say who is paying fails closed instead of spending unmetered.

A code is looked up by its SHA-256 hash (32 random bytes, so a slow KDF adds nothing). The current
code is also kept, so the admin page can show each pass's link again; it is never logged or put in
the repo. Passes, the spend ledger, the visit log and which pass owns which run live in one SQLite
file under DATA_DIR — the persistent disk on Render, so a redeploy wipes none of it, provided DATA_DIR
is the disk's mount path (`storage` checks that). No IP address is stored.
"""
import contextlib
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import reports

KEY_ENV = "OPENAI_API_KEY"
PUBLIC_ENV = "VISEXP_PUBLIC_DEMO"
SECRET_ENV = "SESSION_SECRET"
ADMIN_ENV = "ADMIN_PASSWORD"
CONTACT_ENV = "CONTACT_EMAIL"          # where visitors ask for a pass or a higher cap
CONTACT_DEFAULT = "vinaynair2k@gmail.com"
SEED_FILE = Path(__file__).resolve().parent / "passes.json"
PASS_COOKIE, ADMIN_COOKIE = "vd_pass", "vd_admin"
ADMIN_TTL_S = 12 * 3600

# USD per 1M tokens (input, output), OpenAI list prices as of 2026-09-21 for the models this app
# uses or documents (providers/live.py, agents/evaluator_model.py, agents/onboarding_model.py).
# Cached input is charged at the full input price: overcounting is the safe direction.
PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    # OpenAI list prices read from the model reference on 2026-09-22, added with the move to a newer,
    # cheaper measured model (providers/live.py). gpt-6-luna is the default for both the measured
    # model and the judge; gpt-5-nano is the preflight fallback for both; the rest are the ones the
    # docs and the preflight message name, so a run on any of them is metered exactly, not estimated.
    "gpt-6-luna": (0.10, 0.50),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.5": (5.00, 30.00),
    "text-embedding-3-small": (0.02, 0.00),   # demand.py groups real buyer searches with it
}
UNKNOWN_PRICE = (10.00, 60.00)       # a model missing from the table is charged above all of them
# Per web_search_call. OpenAI lists two tiers (pricing page, read 2026-09-22): `web_search` at
# "$10.00 / 1k calls + Search content tokens billed at model rates", and `web_search_preview`
# (non-reasoning models) at "$25.00 / 1k calls + Search content tokens are free". This app sends
# `web_search` (providers/live.SEARCH_TOOL) and already charges the search content it pulls in as
# input_tokens, so $0.025 was the preview tier's per-call rate charged on top of the standard tier's
# tokens — the same search billed twice. A live run on 2026-09-22 made it the dominant error: 35
# searches charged $0.875 against $0.35 of real usage. Conservatism belongs in UNKNOWN_PRICE and
# UNKNOWN_USAGE, which are guesses; this is a published number.
SEARCH_CALL_USD = 0.01
UNKNOWN_USAGE = (30_000, 4_000)      # tokens charged when a response reports no usage

CAP_MESSAGE = ("This pass has used its ${cap:.2f} limit, so nothing more can run on it. The saved "
               "reports are still open. Email {email} if you would like a higher limit.")
REVOKED_MESSAGE = "This pass has been switched off. The saved reports are still open."
UNKNOWN_CODE = "That link is not valid any more. You can still browse the saved reports."

SPENDER: ContextVar[Optional[str]] = ContextVar("spender", default=None)


class Refused(BaseException):
    """A model call refused before it was made: capped, revoked, or no pass on the public demo.

    BaseException on purpose: the engine turns an `Exception` from a model call into a failed
    answer and carries on, which here would finish and save a run that silently stopped measuring.
    This has to stop the whole run or onboarding, so nothing half-done is saved.
    """
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def public_demo() -> bool:
    return bool(os.environ.get(PUBLIC_ENV))


def contact_email() -> str:
    return os.environ.get(CONTACT_ENV) or CONTACT_DEFAULT


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path() -> Path:
    return reports.DATA / "access.db"


@contextlib.contextmanager
def db():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS passes (id TEXT PRIMARY KEY, label TEXT NOT NULL,
                    cap_usd REAL NOT NULL, code_hash TEXT UNIQUE, revoked INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ledger (pass_id TEXT NOT NULL, at TEXT NOT NULL,
                    model TEXT, input_tokens INTEGER, output_tokens INTEGER, searches INTEGER,
                    usd REAL NOT NULL, estimated INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS visits (pass_id TEXT NOT NULL, label TEXT NOT NULL,
                    event TEXT NOT NULL, at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS owned (kind TEXT NOT NULL, item_id TEXT NOT NULL,
                    pass_id TEXT NOT NULL, name TEXT, at TEXT NOT NULL, PRIMARY KEY (kind, item_id));
            """)
            if "code" not in {r["name"] for r in conn.execute("PRAGMA table_info(passes)")}:
                conn.execute("ALTER TABLE passes ADD COLUMN code TEXT")   # databases made before it
            yield conn
    finally:
        conn.close()


def storage() -> dict:
    """Whether the pass database survives a redeploy: DATA_DIR set, on a mounted disk, writable.
    Names no path but DATA_DIR's own value, so it is safe in /api/health."""
    data_dir = os.environ.get("DATA_DIR")
    if not data_dir:
        return dict(persistent=False, reason="DATA_DIR is not set, so passes are kept inside the "
                                             "container and a redeploy wipes them.")
    path = Path(data_dir).resolve()
    # "/" is always a mount point, and inside a container it is the image itself, not a disk
    if not any(os.path.ismount(d) for d in [path, *path.parents] if d != Path(d.anchor)):
        return dict(persistent=False, reason=f"DATA_DIR={data_dir} is not on a mounted disk, so a "
                                             "redeploy wipes it.")
    if not os.access(path if path.exists() else path.parent, os.W_OK):
        return dict(persistent=False, reason=f"DATA_DIR={data_dir} is not writable.")
    return dict(persistent=True, reason=f"DATA_DIR={data_dir} is on a mounted disk.")


STORAGE_FIX = ("In Render, open the service's Disks and add a disk mounted at a path such as /var/data, "
               "then under Environment set DATA_DIR to exactly that mount path and redeploy.")


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


# ---------------------------------------------------------------- passes
def seed_passes(path: Path = SEED_FILE) -> None:
    """Labels live in git (passes.json); codes never do. The file's label wins on every
    start, so renaming a person is a commit. Its cap applies only when the pass is first created —
    after that the admin page owns the cap, so a top-up survives a redeploy."""
    if not path.exists():
        return
    with db() as c:
        for p in json.loads(path.read_text()):
            c.execute("INSERT INTO passes (id, label, cap_usd, created_at) VALUES (?, ?, ?, ?) "
                      "ON CONFLICT(id) DO UPDATE SET label = excluded.label",
                      (p["id"], p["label"], float(p["cap_usd"]), now()))


def create_pass(label: str, cap_usd: float) -> str:
    pass_id = secrets.token_hex(4)
    with db() as c:
        c.execute("INSERT INTO passes (id, label, cap_usd, created_at) VALUES (?, ?, ?, ?)",
                  (pass_id, label, cap_usd, now()))
    return pass_id


def issue_code(pass_id: str) -> str:
    """A fresh code for the pass. The old code and every session opened with it stop working."""
    code = secrets.token_urlsafe(32)
    with db() as c:
        c.execute("UPDATE passes SET code_hash = ?, code = ?, revoked = 0 WHERE id = ?",
                  (_hash(code), code, pass_id))
    return code


def set_cap(pass_id: str, cap_usd: float) -> None:
    with db() as c:
        c.execute("UPDATE passes SET cap_usd = ? WHERE id = ?", (cap_usd, pass_id))


def revoke(pass_id: str) -> None:
    with db() as c:
        c.execute("UPDATE passes SET revoked = 1 WHERE id = ?", (pass_id,))


def get_pass(pass_id: str) -> Optional[dict]:
    with db() as c:
        row = c.execute("SELECT p.*, COALESCE((SELECT SUM(usd) FROM ledger WHERE pass_id = p.id), 0) "
                        "AS spent_usd FROM passes p WHERE id = ?", (pass_id,)).fetchone()
    return dict(row) if row else None


def all_passes() -> list[dict]:
    with db() as c:
        passes = [dict(r) for r in c.execute(
            "SELECT p.*, COALESCE((SELECT SUM(usd) FROM ledger WHERE pass_id = p.id), 0) AS spent_usd, "
            "(SELECT MIN(at) FROM visits WHERE pass_id = p.id) AS first_visit, "
            "(SELECT MAX(at) FROM visits WHERE pass_id = p.id) AS last_visit "
            "FROM passes p ORDER BY created_at, id")]
        for p in passes:
            owned = c.execute("SELECT kind, name FROM owned WHERE pass_id = ? ORDER BY at",
                              (p["id"],)).fetchall()
            p["runs"] = sum(o["kind"] == "run" for o in owned)
            p["companies"] = list(dict.fromkeys(o["name"] for o in owned if o["name"]))
    return passes


def recent_visits(limit: int = 50) -> list[dict]:
    with db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM visits ORDER BY at DESC, rowid DESC LIMIT ?",
                                           (limit,))]


def log(pass_id: str, event: str) -> None:
    p = get_pass(pass_id)
    with db() as c:
        c.execute("INSERT INTO visits VALUES (?, ?, ?, ?)", (pass_id, p["label"] if p else "?", event, now()))


def status(p: dict) -> dict:
    """What the pass holder sees: the meter."""
    return dict(label=p["label"], spent_usd=round(p["spent_usd"], 4), cap_usd=p["cap_usd"],
                capped=p["spent_usd"] >= p["cap_usd"])


# ---------------------------------------------------------------- sessions
def _sign(value: str) -> str:
    secret = os.environ.get(SECRET_ENV)
    if not secret:
        raise RuntimeError(f"{SECRET_ENV} is not set")
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def configured() -> bool:
    return bool(os.environ.get(SECRET_ENV))


def exchange(code: str) -> tuple[Optional[dict], str]:
    """-> (pass, cookie value) for a live code, else (None, message)."""
    with db() as c:
        row = c.execute("SELECT id, revoked FROM passes WHERE code_hash = ?", (_hash(code),)).fetchone()
    if row is None:
        return None, UNKNOWN_CODE
    if row["revoked"]:
        return None, REVOKED_MESSAGE
    log(row["id"], "opened link")
    # the code hash is in the signature, so issuing a new code ends every session of the old one
    return get_pass(row["id"]), f"{row['id']}.{_sign('pass:' + row['id'] + ':' + _hash(code))}"


def holder(cookie: Optional[str]) -> Optional[dict]:
    """The pass behind a session cookie, if it is signed, current and not revoked."""
    if not cookie or not configured() or "." not in cookie:
        return None
    pass_id, sig = cookie.rsplit(".", 1)
    p = get_pass(pass_id)
    if not p or p["revoked"] or not p["code_hash"]:
        return None
    return p if hmac.compare_digest(sig, _sign(f"pass:{pass_id}:{p['code_hash']}")) else None


def admin_cookie() -> str:
    expires = str(int(time.time()) + ADMIN_TTL_S)
    return f"{expires}.{_sign('admin:' + expires)}"


def is_admin(cookie: Optional[str]) -> bool:
    if not cookie or not configured() or not os.environ.get(ADMIN_ENV) or "." not in cookie:
        return False
    expires, sig = cookie.split(".", 1)
    return (expires.isdigit() and int(expires) > time.time()
            and hmac.compare_digest(sig, _sign("admin:" + expires)))


# ponytail: one global window, so a stranger guessing can also lock the owner out for 10 minutes;
# per-client limits need a trusted client address, which the proxy would have to supply.
_failures: list[float] = []
LOGIN_WINDOW_S, LOGIN_MAX_FAILURES = 600, 5


def admin_login(password: str) -> Optional[str]:
    """-> None on success, else why not."""
    expected = os.environ.get(ADMIN_ENV)
    if not expected or not configured():
        return f"Admin is switched off: set {ADMIN_ENV} and {SECRET_ENV} on the server."
    cutoff = time.time() - LOGIN_WINDOW_S
    _failures[:] = [t for t in _failures if t > cutoff]
    if len(_failures) >= LOGIN_MAX_FAILURES:
        return "Too many wrong passwords. Try again in a few minutes."
    if hmac.compare_digest(password.encode(), expected.encode()):
        return None
    _failures.append(time.time())
    return "Wrong password."


# ---------------------------------------------------------------- ownership
def own(kind: str, item_id: str, pass_id: str, name: str) -> None:
    with db() as c:
        c.execute("INSERT OR REPLACE INTO owned VALUES (?, ?, ?, ?, ?)", (kind, item_id, pass_id, name, now()))


def owner(kind: str, item_id: str) -> Optional[str]:
    with db() as c:
        row = c.execute("SELECT pass_id FROM owned WHERE kind = ? AND item_id = ?", (kind, item_id)).fetchone()
    return row["pass_id"] if row else None


def visible(kind: str, item_id: str, pass_id: Optional[str]) -> bool:
    """Off the public demo everything is visible. On it: the shared demo items (owned by nobody)
    and the viewer's own."""
    if not public_demo():
        return True
    o = owner(kind, item_id)
    return o is None or o == pass_id


# ---------------------------------------------------------------- metering
@contextlib.contextmanager
def spending(pass_id: Optional[str]):
    token = SPENDER.set(pass_id)
    try:
        yield
    finally:
        SPENDER.reset(token)


def check(pass_id: Optional[str]) -> None:
    """Raises Refused unless a model call may be made now."""
    if pass_id is None:
        if public_demo():
            raise Refused("This is the public demo: model calls need a pass.")
        return
    p = get_pass(pass_id)
    if p is None or p["revoked"]:
        raise Refused(REVOKED_MESSAGE)
    if p["spent_usd"] >= p["cap_usd"]:
        raise Refused(CAP_MESSAGE.format(cap=p["cap_usd"], email=contact_email()))


def _get(obj, key):
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def cost(model: str, response) -> tuple[float, dict]:
    """-> (usd, ledger fields) from the usage the response reports; estimated when it reports none."""
    usage = _get(response, "usage") if response is not None else None
    tin, tout = (_get(usage, "input_tokens"), _get(usage, "output_tokens")) if usage is not None else (None, None)
    if tin is None and isinstance(_get(usage, "prompt_tokens"), int):   # an embedding reports only its input
        tin, tout = _get(usage, "prompt_tokens"), 0
    estimated = not isinstance(tin, int) or not isinstance(tout, int) or model not in PRICES
    if not isinstance(tin, int) or not isinstance(tout, int):
        tin, tout = UNKNOWN_USAGE
    pin, pout = PRICES.get(model, UNKNOWN_PRICE)
    searches = sum(_get(i, "type") == "web_search_call" for i in (_get(response, "output") or [])) \
        if response is not None else 0
    usd = tin * pin / 1e6 + tout * pout / 1e6 + searches * SEARCH_CALL_USD
    return usd, dict(model=model, input_tokens=tin, output_tokens=tout, searches=searches,
                     estimated=int(estimated))


def charge(pass_id: str, model: str, response) -> float:
    usd, f = cost(model, response)
    with db() as c:
        c.execute("INSERT INTO ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (pass_id, now(), f["model"], f["input_tokens"], f["output_tokens"], f["searches"],
                   usd, f["estimated"]))
    return usd


def _create(timeout: int, **kwargs):
    """The one line in the app that talks to OpenAI. Tests replace it."""
    from openai import OpenAI  # lazy: the offline demo must not need the SDK
    return OpenAI(api_key=os.environ[KEY_ENV], timeout=timeout).responses.create(**kwargs)


def _embed(timeout: int, **kwargs):
    """The one line in the app that asks OpenAI for embeddings. Tests replace it."""
    from openai import OpenAI
    return OpenAI(api_key=os.environ[KEY_ENV], timeout=timeout).embeddings.create(**kwargs)


def openai_embedding(timeout: int, **kwargs):
    """embeddings.create, metered exactly like openai_response."""
    return _metered(_embed, timeout, kwargs)


def openai_response(timeout: int, **kwargs):
    """responses.create, metered: see _metered."""
    return _metered(_create, timeout, kwargs)


def _metered(call, timeout: int, kwargs: dict):
    """A model call refused before the call when the acting pass may not spend, and charged
    to it after. A call that fails without an HTTP status (a timeout, a dropped connection) may
    still have been billed, so it is charged the unknown-usage estimate."""
    pass_id = SPENDER.get()
    check(pass_id)
    try:
        response = call(timeout, **kwargs)
    except Exception as e:
        if pass_id and getattr(e, "status_code", None) is None:
            charge(pass_id, kwargs["model"], None)
        raise
    if pass_id:
        charge(pass_id, kwargs["model"], response)
    return response
