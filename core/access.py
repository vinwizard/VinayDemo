"""Access passes for the hosted demo: who may spend the owner's OpenAI key, and how much.

A visitor without a pass gets the public replay and nothing else. A pass holder opens a personal
link (<site>/?pass=<code>); the web app trades the code for a signed session cookie and can then
onboard and measure live, up to the pass's dollar cap.

Every OpenAI call in the app goes through `core/llm.py`, which asks this module before the call
whether the acting pass may spend (`hold`) and charges the usage the response reports afterwards. The acting
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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from pathlib import Path
from typing import Optional

from core import reports
from core.schemas import utc_now

KEY_ENV = "OPENAI_API_KEY"
PUBLIC_ENV = "VISEXP_PUBLIC_DEMO"
SECRET_ENV = "SESSION_SECRET"
ADMIN_ENV = "ADMIN_PASSWORD"
CONTACT_ENV = "CONTACT_EMAIL"          # where visitors ask for a pass or a higher cap
CONTACT_DEFAULT = "vinaynair2k@gmail.com"
SEED_FILE = Path(__file__).resolve().parent / "passes.json"
PASS_COOKIE, ADMIN_COOKIE = "vd_pass", "vd_admin"
ADMIN_TTL_S = 12 * 3600

CAP_MESSAGE = ("This pass has used its ${cap:.2f} limit, so nothing more can run on it. The saved "
               "reports are still open. Email {email} if you would like a higher limit.")
REVOKED_MESSAGE = "This pass has been switched off. The saved reports are still open."
UNKNOWN_CODE = "That link is not valid any more. You can still browse the saved reports."

SPENDER: ContextVar[Optional[str]] = ContextVar("spender", default=None)


def pmap(fn, items, workers: int) -> list:
    """fn over items, `workers` at a time, results in order. Each call runs in a copy of the CALLER's
    context, taken here: a pool thread starts with an empty one, so a copy taken inside it would drop
    the paying pass (SPENDER) and a fleet's purse, and every call would go unmetered or be refused."""
    with ThreadPoolExecutor(workers) as pool:
        return [f.result() for f in [pool.submit(copy_context().run, fn, x) for x in items]]


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


def db_path() -> Path:
    return reports.DATA / "access.db"


@contextlib.contextmanager
def db():
    with reports.sqlite(db_path(), """
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
            """) as conn:
        conn.row_factory = sqlite3.Row
        if "code" not in {r["name"] for r in conn.execute("PRAGMA table_info(passes)")}:
            conn.execute("ALTER TABLE passes ADD COLUMN code TEXT")   # databases made before it
        yield conn


def storage() -> dict:
    """Whether DATA_DIR survives a redeploy: set, on a mounted disk, writable. It holds the pass
    database and every saved run and company, so this is also whether a pass holder's History lasts.
    Names no path but DATA_DIR's own value, so it is safe in /api/health."""
    data_dir = os.environ.get("DATA_DIR")
    if not data_dir:
        return dict(persistent=False, reason="DATA_DIR is not set, so passes, runs and companies "
                                             "are kept inside the container and a redeploy wipes them.")
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
                      (p["id"], p["label"], float(p["cap_usd"]), utc_now()))


def create_pass(label: str, cap_usd: float) -> str:
    pass_id = secrets.token_hex(4)
    with db() as c:
        c.execute("INSERT INTO passes (id, label, cap_usd, created_at) VALUES (?, ?, ?, ?)",
                  (pass_id, label, cap_usd, utc_now()))
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
        c.execute("INSERT INTO visits VALUES (?, ?, ?, ?)", (pass_id, p["label"] if p else "?", event, utc_now()))


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
        c.execute("INSERT OR REPLACE INTO owned VALUES (?, ?, ?, ?, ?)", (kind, item_id, pass_id, name, utc_now()))


def owner(kind: str, item_id: str) -> Optional[str]:
    with db() as c:
        row = c.execute("SELECT pass_id FROM owned WHERE kind = ? AND item_id = ?", (kind, item_id)).fetchone()
    return row["pass_id"] if row else None


# Retired committed examples, each a run then its company: the Profound showcase, and the first Amgen
# run, whose saved rival names had been edited by hand and could not be reproduced by the code.
# Earlier releases copied them into DATA_DIR, and a persistent disk still holds them; they stay on
# disk and are never listed or served.
RETIRED_EXAMPLES = (("8d1d78c3e6", "998420ffae"), ("0c55be2792", "3afc276406"))
RETIRED = {i for pair in RETIRED_EXAMPLES for i in pair}


def visible(kind: str, item_id: str, pass_id: Optional[str]) -> bool:
    """Off the public demo everything is visible. On it: a visitor without a pass sees the shared
    demo items (owned by nobody), and a pass holder sees only their own — the preloaded examples are
    for browsing, not for someone who came to measure their own company. Retired items: nobody."""
    if item_id in RETIRED:
        return False
    if not public_demo():
        return True
    return owner(kind, item_id) == pass_id


# ---------------------------------------------------------------- metering
@contextlib.contextmanager
def _bound(var: ContextVar, value):
    """`var` set to `value` in this thread's context for the block, then back as it was."""
    token = var.set(value)
    try:
        yield value
    finally:
        var.reset(token)


def spending(pass_id: Optional[str]):
    return _bound(SPENDER, pass_id)


def check(pass_id: Optional[str], in_flight: float = 0.0) -> None:
    """Raises Refused unless a model call may be made now. `in_flight` is what the pass's calls
    already under way are estimated to cost: they count against the cap before they are charged."""
    if pass_id is None:
        if public_demo():
            raise Refused("This is the public demo: model calls need a pass.")
        return
    p = get_pass(pass_id)
    if p is None or p["revoked"]:
        raise Refused(REVOKED_MESSAGE)
    if p["spent_usd"] + in_flight >= p["cap_usd"]:
        raise Refused(CAP_MESSAGE.format(cap=p["cap_usd"], email=contact_email()))


# Each pass's calls in flight, at their estimated cost: with LIVE_CONCURRENCY calls under way at once,
# checking the ledger alone would let all of them through on the last cent. A call that would take the
# pass past its cap counting what is under way waits for those to be charged, then checks again: so
# the cap is passed by what it always was, about one call, and a run is never stopped early on an
# estimate (one with search is held at about twice what it usually costs).
_in_flight: dict[str, float] = {}
_settled = threading.Condition()


def hold(pass_id: Optional[str], usd: float) -> float:
    if not pass_id:
        check(pass_id)
        return 0.0
    with _settled:
        while True:
            under_way = _in_flight.get(pass_id, 0.0)
            check(pass_id)                       # spent alone at the cap: refused, as ever
            try:
                check(pass_id, under_way)
                break
            except Refused:
                _settled.wait()                  # room only once the calls under way are charged
        _in_flight[pass_id] = under_way + usd
    started()
    return usd


# A dispatched ask whose first call has not reserved yet, per pass: the dispatcher starts at most one
# at a time, so what a pass has under way is always in _in_flight when it decides whether to start the next.
_starting: dict[str, object] = {}
STARTING: ContextVar[Optional[tuple]] = ContextVar("starting", default=None)


def start(wake) -> bool:
    """For the dispatcher, in an ask's context: whether it may start now without waiting in hold for
    its pass's calls under way to be charged, so one pass at its cap never holds the workers every run
    shares. A pass already at its cap may: its call is refused at once. `wake` is called once the ask
    has reserved its first call or ended (`started`), when the pass may start another."""
    pass_id = SPENDER.get()
    if not pass_id:
        return True
    with _settled:
        if pass_id in _starting:
            return False
        under_way = _in_flight.get(pass_id, 0.0)
    if under_way:
        try:
            p = get_pass(pass_id)
        except Exception:                        # hold decides then, as it always did
            p = None
        if p and not p["revoked"] and p["spent_usd"] < p["cap_usd"] <= p["spent_usd"] + under_way:
            return False
    token = object()
    with _settled:
        _starting[pass_id] = token
    STARTING.set((pass_id, token, wake))
    return True


def started() -> None:
    if not (mark := STARTING.get()):
        return
    pass_id, token, wake = mark
    STARTING.set(None)
    with _settled:
        if _starting.get(pass_id) is token:
            del _starting[pass_id]
    wake()


def release(pass_id: Optional[str], usd: float) -> None:
    if pass_id and usd:
        with _settled:
            if (left := _in_flight.get(pass_id, 0.0) - usd) > 1e-12:
                _in_flight[pass_id] = left
            else:
                _in_flight.pop(pass_id, None)
            _settled.notify_all()


# ---------------------------------------------------------------- a fleet's purse (fix/fleet.py)
class PurseEmpty(BaseException):
    """A fleet call its purse cannot afford. BaseException for the reason Refused is: the evaluator
    turns an Exception into "could not judge" and carries on, which would keep an investigator
    asking after the fleet's money ran out. why.Agent and the fleet loop catch it by name."""

    def __init__(self, limit: float):
        super().__init__(f"the fleet's ${limit:.2f} budget is spent")
        self.limit = limit


class Purse:
    """One fleet's budget (FLEET_BUDGET_USD), shared by every model call any of its agents makes.

    It rides in PURSE, a ContextVar like SPENDER; a context copied into a pool thread carries a
    reference to this same object, so every investigator draws on one purse. `reserve` is kept back
    for the plan's writer until `release_reserve`, so running out never leaves a fleet without its
    plan. `slots` caps the fleet's calls in flight, which is what keeps it under the rate limit.
    A held estimate can be short of the real cost, so the spend can pass the limit by that error."""

    def __init__(self, limit_usd: float, reserve_usd: float = 0.0, in_flight: int = 18):
        self.limit, self.reserve = limit_usd, reserve_usd
        self.spent = self.held = 0.0
        self.slots = threading.BoundedSemaphore(in_flight)
        self._lock = threading.Lock()

    def take(self, usd: float) -> float:
        with self._lock:
            if self.spent + self.held + usd > self.limit - self.reserve:
                raise PurseEmpty(self.limit)
            self.held += usd
        return usd

    def settle(self, held: float, usd: float) -> None:
        with self._lock:
            self.held -= held
            self.spent += usd

    def left(self) -> float:
        """What calls may still hold, the writer's reserve excluded."""
        with self._lock:
            return self.limit - self.reserve - self.spent - self.held

    def release_reserve(self) -> None:
        with self._lock:
            self.reserve = 0.0


PURSE: ContextVar[Optional[Purse]] = ContextVar("purse", default=None)


def drawing(purse: Optional[Purse]):
    return _bound(PURSE, purse)
