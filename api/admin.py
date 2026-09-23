"""/admin: the owner's page for access passes. Server-rendered forms; the only script is the copy button.

Behind ADMIN_PASSWORD (constant-time compare, rate-limited) and a signed admin cookie that is
SameSite=Strict, so another site cannot post these forms with it. Each pass's current link is shown
in its row with a copy button; a pass whose code was stored only hashed (before codes were kept)
says so and needs a regenerate. A red banner shows when the pass database is not on a persistent disk.
"""
from html import escape
from typing import Optional
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import access

router = APIRouter()

STYLE = """
:root { --bg: #f6f7f9; --card: #fff; --ink: #1d2330; --muted: #5f6b7a; --border: #dde2e8;
        --accent: #3056d3; --on-accent: #fff; --warn: #b42318; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #14171c; --card: #1c2027; --ink: #e8ecf1; --muted: #9aa5b3; --border: #2e3440;
          --accent: #7c9bff; --on-accent: #0b1020; --warn: #ff8a80; } }
body { margin: 0; background: var(--bg); color: var(--ink);
       font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 24px 16px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px;
        margin-bottom: 16px; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: 13px; }
.muted { color: var(--muted); font-size: 13px; }
.warn { color: var(--warn); }
form { display: inline-flex; gap: 6px; align-items: center; margin: 2px 0; }
input { font: inherit; padding: 4px 6px; border: 1px solid var(--border); border-radius: 4px;
        background: var(--card); color: var(--ink); }
input[type=number] { width: 5.5em; }
button { font: inherit; padding: 4px 10px; border-radius: 4px; border: 1px solid var(--accent);
         background: var(--accent); color: var(--on-accent); cursor: pointer; }
button.quiet { background: transparent; color: var(--accent); }
button.danger { border-color: var(--warn); background: transparent; color: var(--warn); }
.alert { border-color: var(--warn); color: var(--warn); }
.link { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all;
        user-select: all; padding: 8px; border: 1px dashed var(--accent); border-radius: 4px; }
"""


def page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><html lang=en><head><meta charset=utf-8>"
                        f"<meta name=viewport content='width=device-width, initial-scale=1'>"
                        f"<title>Pass admin</title><style>{STYLE}</style></head>"
                        f"<body><main><h1>Access passes</h1>{body}</main></body></html>", status,
                        headers={"Cache-Control": "no-store"})


def login_page(message: Optional[str] = None, status: int = 200) -> HTMLResponse:
    note = f"<p class=warn>{escape(message)}</p>" if message else ""
    return page(f"<div class=card>{note}<form method=post action=/admin/login>"
                f"<input type=password name=password placeholder=Password autofocus required>"
                f"<button>Sign in</button></form></div>", status)


def when(iso: Optional[str]) -> str:
    return escape(iso.replace("T", " ").removesuffix("+00:00") + " UTC") if iso else "—"


def action(pass_id: str, name: str, label: str, css: str = "quiet", extra: str = "") -> str:
    return (f"<form method=post action=/admin/action><input type=hidden name=pass_id value='{escape(pass_id)}'>"
            f"<input type=hidden name=do value={name}>{extra}<button class={css}>{label}</button></form>")


def link_cell(p: dict, base: str) -> str:
    if p["revoked"] or not p["code_hash"]:
        return ""
    if not p["code"]:
        return "<div class=muted>link hidden - regenerate to see it</div>"
    url = escape(f"{base}/?pass={p['code']}")
    return (f"<div class=link>{url}</div><button class=quiet type=button "
            f"onclick=\"navigator.clipboard.writeText(this.previousElementSibling.textContent)"
            f".then(() => this.textContent = 'Copied')\">Copy link</button>")


def dashboard(request: Request, note: str = "") -> HTMLResponse:
    base = f"{request.headers.get('x-forwarded-proto', request.url.scheme)}://{request.headers.get('host', request.url.netloc)}"
    store = access.storage()
    alert = ("" if store["persistent"] else
             f"<div class='card alert'><strong>Passes and runs are not on a persistent disk — the next deploy will "
             f"delete every pass, link, spend record and every pass holder's History.</strong><p>{escape(store['reason'])} "
             f"{escape(access.STORAGE_FIX)}</p></div>")
    rows = []
    for p in access.all_passes():
        state = ("<span class=warn>revoked</span>" if p["revoked"]
                 else "link active" if p["code_hash"] else "<span class=muted>no link yet</span>")
        runs = f"{p['runs']} run{'s' * (p['runs'] != 1)}"
        companies = escape(", ".join(p["companies"])) or "—"
        cap = f"<input type=number name=cap min=0 step=0.5 value='{p['cap_usd']:g}' aria-label='New cap'>"
        rows.append(
            f"<tr><td><strong>{escape(p['label'])}</strong><div class=muted>{escape(p['id'])}</div></td>"
            f"<td>{state}{link_cell(p, base)}</td><td>${p['spent_usd']:.2f} of ${p['cap_usd']:.2f}</td>"
            f"<td>{runs}<div class=muted>{companies}</div></td>"
            f"<td>{when(p['first_visit'])}</td><td>{when(p['last_visit'])}</td><td>"
            + action(p["id"], "link", "Regenerate link" if p["code_hash"] else "Generate link", "")
            + action(p["id"], "cap", "Set cap", extra=cap)
            + ("" if p["revoked"] or not p["code_hash"] else action(p["id"], "revoke", "Revoke", "danger"))
            + "</td></tr>")
    visits = "".join(f"<tr><td>{when(v['at'])}</td><td>{escape(v['label'])}</td><td>{escape(v['event'])}</td></tr>"
                     for v in access.recent_visits())
    return page(
        alert + (f"<p class=warn>{escape(note)}</p>" if note else "")
        + "<div class=card><table><tr><th>Pass</th><th>Link</th><th>Spent</th><th>Runs · companies</th>"
          "<th>First visit</th><th>Last visit</th><th></th></tr>" + "".join(rows) + "</table></div>"
        + "<div class=card><h2>New pass</h2><form method=post action=/admin/action>"
          "<input type=hidden name=do value=create><input name=label placeholder=Name required maxlength=80>"
          "<input type=number name=cap min=0 step=0.5 value=5 aria-label=Cap> USD <button>Create</button></form>"
          "<p class=muted>Names from <code>passes.json</code> are seeded on start; a name set there wins.</p></div>"
        + f"<div class=card><h2>Recent visits</h2><table><tr><th>When</th><th>Pass</th><th>Event</th></tr>{visits}</table></div>"
        + "<form method=post action=/admin/logout><button class=quiet>Sign out</button></form>")


async def form(request: Request) -> dict[str, str]:
    """application/x-www-form-urlencoded, parsed with the stdlib rather than adding python-multipart."""
    return {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}


def signed_in(request: Request) -> bool:
    return access.is_admin(request.cookies.get(access.ADMIN_COOKIE))


@router.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    return dashboard(request) if signed_in(request) else login_page()


@router.post("/admin/login")
async def login(request: Request):
    refused = access.admin_login((await form(request)).get("password", ""))
    if refused:
        return login_page(refused, 429 if "Too many" in refused else 403)
    r = RedirectResponse("/admin", 303)
    r.set_cookie(access.ADMIN_COOKIE, access.admin_cookie(), max_age=access.ADMIN_TTL_S, httponly=True,
                 secure=True, samesite="strict", path="/admin")
    return r


@router.post("/admin/logout")
def logout():
    r = RedirectResponse("/admin", 303)
    r.delete_cookie(access.ADMIN_COOKIE, path="/admin")
    return r


def cap_value(raw: Optional[str]) -> Optional[float]:
    try:
        cap = round(float(raw or ""), 2)
    except ValueError:
        return None
    return cap if 0 <= cap <= 1000 else None


@router.post("/admin/action")
async def act(request: Request):
    if not signed_in(request):
        return login_page("Sign in first.", 403)
    f = await form(request)
    do, pass_id = f.get("do"), f.get("pass_id", "")
    if do == "create":
        label, cap = f.get("label", "").strip()[:80], cap_value(f.get("cap"))
        if not label or cap is None:
            return dashboard(request, note="A pass needs a name and a cap between $0 and $1000.")
        pass_id = access.create_pass(label, cap)
        do = "link"                      # a new pass is only useful with its link
    p = access.get_pass(pass_id)
    if p is None:
        return dashboard(request, note="No such pass.")
    if do == "link":                     # the old link and its sessions stop working
        access.issue_code(pass_id)
    elif do == "cap":
        cap = cap_value(f.get("cap"))
        if cap is None:
            return dashboard(request, note="A cap is a number of dollars between 0 and 1000.")
        access.set_cap(pass_id, cap)
    elif do == "revoke":
        access.revoke(pass_id)
    return RedirectResponse("/admin", 303)
