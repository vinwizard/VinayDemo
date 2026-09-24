"""Access passes on the public demo: the code exchange, the admin page, the spend meter and who sees
which run. No key and no network: `access._create`, the one line that talks to OpenAI, is replaced
by a fake that returns a usage payload, or by one that fails the test if it is ever reached.
"""
import json

import pytest
from fastapi.testclient import TestClient

import access
import api.main as main
import reports
from providers import live

CO = "abcdef0123"        # a copy of the seed company, owned by the first pass in these tests
USAGE = {"input_tokens": 1_000_000, "output_tokens": 100_000}   # gpt-4o-mini: $0.15 + $0.06


def fake_response(**kw):
    """A measured answer that names Notion and ran one search; the evaluator gets the same text,
    which is not JSON, so its labels fail and the answer is left for review — fine for metering."""
    return {"output": [{"type": "web_search_call"},
                       {"type": "message", "content": [{"type": "output_text",
                                                        "text": "Notion is a connected workspace."}]}],
            "usage": {"input_tokens": 1000, "output_tokens": 200}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    companies, runs = tmp_path / "companies", tmp_path / "runs"
    companies.mkdir()
    runs.mkdir()
    seed = json.loads((reports.BUNDLED / "companies" / f"{main.SEED_COMPANY}.json").read_text())
    (companies / f"{CO}.json").write_text(json.dumps(seed | {"id": CO}))
    monkeypatch.setattr(reports, "DATA", tmp_path)
    monkeypatch.setattr(reports, "COMPANIES", companies)
    monkeypatch.setattr(reports, "RUNS", runs)
    monkeypatch.setattr(main, "RUNS", runs)
    monkeypatch.setenv(access.PUBLIC_ENV, "1")
    monkeypatch.setenv(access.SECRET_ENV, "test-secret")
    monkeypatch.setenv(access.ADMIN_ENV, "hunter2-long-password")
    monkeypatch.setenv(live.KEY_ENV, "sk-fake-never-sent")
    monkeypatch.delenv(main.OFFLINE_ENV, raising=False)
    monkeypatch.setattr(access, "_failures", [])
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: pytest.fail(f"unexpected model call {kw}"))
    access.seed_passes()


def browser():
    return TestClient(main.app, base_url="https://testserver", raise_server_exceptions=False)


def with_pass(pass_id="person-1"):
    code = access.issue_code(pass_id)
    c = browser()
    r = c.post("/api/access/exchange", json={"code": code})
    assert r.status_code == 200, r.text
    return c, code, r


def events(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


# --- the code exchange ----------------------------------------------------------------------------

def test_seeded_passes_come_from_the_tracked_file_with_labels_and_caps_only(env):
    seeded = json.loads(access.SEED_FILE.read_text())
    assert {p["label"] for p in seeded} == {f"person {n}" for n in range(1, 6)}
    assert all(set(p) == {"id", "label", "cap_usd"} for p in seeded)       # never a code
    assert all(p["code_hash"] is None for p in access.all_passes())       # no link until generated


def test_a_code_becomes_an_httponly_secure_session_and_the_meter_reads_it(env):
    c, code, r = with_pass()
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert code not in r.headers["set-cookie"] and code not in r.text   # the code is never echoed
    assert r.json()["pass"] == {"label": "person 1", "spent_usd": 0, "cap_usd": 5.0, "capped": False}
    assert c.get("/api/access").json()["pass"]["label"] == "person 1"
    assert c.get("/api/health").json()["live_available"] is True
    assert browser().get("/api/health").json()["live_available"] is False
    assert access.all_passes()[0]["first_visit"] is not None


def test_unknown_and_revoked_codes_get_a_plain_message_and_no_session(env):
    r = browser().post("/api/access/exchange", json={"code": "not-a-real-code"})
    assert r.status_code == 403 and "not valid" in r.json()["detail"]
    c, code, _ = with_pass()
    access.revoke("person-1")
    assert c.get("/api/access").json()["pass"] is None                   # the open session ends too
    r = browser().post("/api/access/exchange", json={"code": code})
    assert r.status_code == 403 and "switched off" in r.json()["detail"]


def test_regenerating_a_link_kills_the_old_code_and_its_sessions(env):
    c, old, _ = with_pass()
    access.issue_code("person-1")
    assert c.get("/api/access").json()["pass"] is None
    assert browser().post("/api/access/exchange", json={"code": old}).status_code == 403


def test_a_forged_cookie_is_no_pass(env):
    with_pass()
    c = browser()
    c.cookies.set(access.PASS_COOKIE, "person-1." + "0" * 64, domain="testserver")
    assert c.get("/api/access").json()["pass"] is None


# --- admin ----------------------------------------------------------------------------------------

def test_admin_needs_the_password_and_is_rate_limited(env):
    c = browser()
    assert "Sign in" in c.get("/admin").text and "person 1" not in c.get("/admin").text
    r = c.post("/admin/action", data={"do": "create", "label": "x", "cap": "5"})
    assert r.status_code == 403 and len(access.all_passes()) == 5
    for _ in range(access.LOGIN_MAX_FAILURES):
        assert c.post("/admin/login", data={"password": "wrong"}).status_code == 403
    # locked out: even the right password waits
    assert c.post("/admin/login", data={"password": "hunter2-long-password"}).status_code == 429


def admin():
    c = browser()
    assert c.post("/admin/login", data={"password": "hunter2-long-password"}).status_code == 200
    return c


def test_admin_creates_a_pass_keeps_showing_its_link_and_tops_up(env):
    c = admin()
    page = c.post("/admin/action", data={"do": "create", "label": "Ada", "cap": "10"}).text
    code = page.split("/?pass=")[1].split("<")[0]
    ada = next(p for p in access.all_passes() if p["label"] == "Ada")
    assert ada["cap_usd"] == 10 and ada["code_hash"] == access._hash(code)
    shown = c.get("/admin")
    assert f"https://testserver/?pass={code}" in shown.text and "Copy link" in shown.text
    assert shown.headers["cache-control"] == "no-store"
    assert browser().post("/api/access/exchange", json={"code": code}).status_code == 200
    c.post("/admin/action", data={"do": "cap", "pass_id": ada["id"], "cap": "12.5"})
    c.post("/admin/action", data={"do": "revoke", "pass_id": "person-2"})
    passes = {p["id"]: p for p in access.all_passes()}
    assert passes[ada["id"]]["cap_usd"] == 12.5 and passes["person-2"]["revoked"] == 1
    assert "opened link" in c.get("/admin").text


def test_regenerate_replaces_the_shown_link_and_a_hash_only_pass_says_regenerate(env):
    c, old, _ = with_pass()
    page = admin().post("/admin/action", data={"do": "link", "pass_id": "person-1"}).text
    new = page.split("/?pass=")[1].split("<")[0]
    assert new != old and old not in page and c.get("/api/access").json()["pass"] is None
    assert browser().post("/api/access/exchange", json={"code": new}).status_code == 200
    with access.db() as db:                          # a pass made before codes were kept
        db.execute("UPDATE passes SET code = NULL WHERE id = 'person-1'")
    assert "link hidden - regenerate to see it" in admin().get("/admin").text


def test_seeding_on_start_never_touches_admin_made_passes_their_spend_or_links(env, monkeypatch):
    c = admin()
    c.post("/admin/action", data={"do": "create", "label": "test", "cap": "7"})
    mine = next(p for p in access.all_passes() if p["label"] == "test")
    access.issue_code("person-1")
    access.set_cap("person-1", 9)
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: {"usage": USAGE, "output": []})
    with access.spending(mine["id"]):
        access.openai_response(30, model="gpt-4o-mini", input="hi")
    before = {p["id"]: p for p in access.all_passes()}
    access.seed_passes()
    access.seed_passes()
    assert {p["id"]: p for p in access.all_passes()} == before
    assert before[mine["id"]]["code"] and before[mine["id"]]["spent_usd"] > 0


def test_storage_is_persistent_only_on_a_writable_mounted_disk(env, monkeypatch, tmp_path):
    disk = tmp_path / "disk"
    disk.mkdir()
    monkeypatch.delenv("DATA_DIR", raising=False)
    assert "DATA_DIR is not set" in access.storage()["reason"]
    monkeypatch.setenv("DATA_DIR", str(disk / "data"))
    monkeypatch.setattr(access.os.path, "ismount", lambda p: False)
    assert not access.storage()["persistent"] and "not on a mounted disk" in access.storage()["reason"]
    page = admin().get("/admin").text
    assert "not on a persistent disk" in page and "set DATA_DIR to exactly that mount path" in page
    monkeypatch.setattr(access.os.path, "ismount", lambda p: str(p) == str(disk))  # a parent is the mount
    assert access.storage()["persistent"]
    assert browser().get("/api/health").json()["storage"]["persistent"] is True
    assert "not on a persistent disk" not in admin().get("/admin").text
    monkeypatch.setattr(access.os, "access", lambda p, mode: False)
    assert "not writable" in access.storage()["reason"]


# --- metering -------------------------------------------------------------------------------------

def test_usage_is_charged_from_the_response_and_estimated_when_missing(env, monkeypatch):
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: {"usage": USAGE, "output": []})
    with access.spending("person-1"):
        access.openai_response(30, model="gpt-4o-mini", input="hi")
    assert access.get_pass("person-1")["spent_usd"] == pytest.approx(0.21)
    usd, f = access.cost("some-new-model", {"output": [{"type": "web_search_call"}]})
    assert f["estimated"] and usd >= access.UNKNOWN_USAGE[0] * access.UNKNOWN_PRICE[0] / 1e6
    assert usd > access.cost("gpt-4o-mini", {"usage": USAGE})[0] / 10     # never counted as zero


def test_a_capped_pass_is_refused_before_the_call(env, monkeypatch):
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: {"usage": USAGE, "output": []})
    access.set_cap("person-1", 0.2)
    with access.spending("person-1"):
        access.openai_response(30, model="gpt-4o-mini", input="hi")         # $0.21: now over
        monkeypatch.setattr(access, "_create", lambda *a, **k: pytest.fail("called past the cap"))
        with pytest.raises(access.Refused, match=r"\$0.20 limit"):
            access.openai_response(30, model="gpt-4o-mini", input="hi")


def test_a_call_with_no_pass_on_the_public_demo_fails_closed(env):
    with pytest.raises(access.Refused):
        access.openai_response(30, model="gpt-4o-mini", input="hi")


# --- live runs on a pass ------------------------------------------------------------------------

def test_a_pass_runs_live_is_charged_and_only_it_sees_the_run(env, monkeypatch):
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: fake_response())
    access.own("company", CO, "person-1", "Notion")
    c, _, _ = with_pass()
    got = events(c.get(f"/api/stream?company={CO}&mode=live").text)
    assert got[-1][0] == "done", got[-1]
    run_id = got[-1][1]["run_id"]
    spent = c.get("/api/access").json()["pass"]["spent_usd"]
    assert spent > 0
    assert access.owner("run", run_id) == "person-1"
    assert run_id in [r["id"] for r in c.get("/api/runs").json()]
    other, _, _ = with_pass("person-2")
    for viewer in (other, browser()):
        assert run_id not in [r["id"] for r in viewer.get("/api/runs").json()]
        assert viewer.get(f"/api/runs/{run_id}").status_code == 404
        assert CO not in [x["id"] for x in viewer.get("/api/companies").json()]
    assert other.patch(f"/api/companies/{CO}", json={"weights": {}}).status_code == 403
    admin_row = next(p for p in access.all_passes() if p["id"] == "person-1")
    assert admin_row["runs"] == 1 and admin_row["companies"] == ["Notion"]


def test_a_run_that_hits_the_cap_stops_with_a_message_and_saves_nothing(env, monkeypatch):
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: fake_response())
    access.own("company", CO, "person-1", "Notion")
    access.set_cap("person-1", 0.06)     # preflight fits; the run's searches do not
    c, _, _ = with_pass()
    kind, data = events(c.get(f"/api/stream?company={CO}&mode=live").text)[-1]
    assert kind == "error" and "limit" in data["message"]
    assert list(reports.RUNS.glob("*.json")) == []
    assert c.get("/api/access").json()["pass"]["capped"] is True
    kind, data = events(c.get(f"/api/stream?company={CO}&mode=live").text)[-1]
    assert kind == "error" and "limit" in data["message"]                # refused before preflight
    assert access.CONTACT_DEFAULT in data["message"]                     # and says who raises it


def test_a_visitor_without_a_pass_is_replay_only_with_zero_model_calls(env):
    c = browser()
    kind, data = events(c.get(f"/api/stream?company={CO}&mode=live").text)[-1]
    assert kind == "error" and "public demo" in data["message"]
    assert access.CONTACT_DEFAULT in data["message"]                     # invited to ask for a pass
    refused = c.get("/api/onboard?url=https://example.com")
    assert refused.status_code == 403 and access.CONTACT_DEFAULT in refused.json()["detail"]
    assert c.patch(f"/api/companies/{CO}", json={"weights": {}}).status_code == 403
    kind, _ = events(c.get(f"/api/stream?company={main.SEED_COMPANY}&mode=live").text)[-1]
    assert kind == "done"                                                # the seed still replays


def preload_examples(tmp_path):
    """The preloaded Notion company, the committed live example and its company, as a deploy's DATA_DIR has them."""
    for kind, item in (("companies", main.SEED_COMPANY), ("companies", main.SHOWCASE_COMPANY),
                       ("runs", main.SHOWCASE_RUN)):
        (tmp_path / kind / f"{item}.json").write_bytes((reports.BUNDLED / kind / f"{item}.json").read_bytes())


def test_a_pass_sees_none_of_the_preloaded_examples_and_a_visitor_still_does(env, tmp_path):
    preload_examples(tmp_path)
    access.own("company", CO, "person-1", "Notion")
    c, _, _ = with_pass()
    public = browser()
    for viewer, shown in ((public, True), (c, False)):
        assert (main.SHOWCASE_RUN in [r["id"] for r in viewer.get("/api/runs").json()]) is shown
        assert (viewer.get(f"/api/runs/{main.SHOWCASE_RUN}").status_code == 200) is shown
        companies = {x["id"] for x in viewer.get("/api/companies").json()}
        assert {main.SEED_COMPANY, main.SHOWCASE_COMPANY} <= companies if shown else \
            companies == {CO}                                            # only what the pass onboarded


def test_a_pass_holders_runs_survive_a_restart_and_a_new_session(env, tmp_path):
    """The reproduction: a pass holder's replay was shown and never saved, so it was gone from History
    by their next visit. Every run a pass makes is now on disk under DATA_DIR, owned by that pass."""
    preload_examples(tmp_path)
    c, code, _ = with_pass()
    made = [events(c.get(q).text)[-1][1]["run_id"]                       # replays: no model is called
            for q in ("/api/stream?scenario=A", f"/api/stream?company={main.SEED_COMPANY}&mode=live")]
    for run_id in made:
        assert (tmp_path / "runs" / f"{run_id}.json").exists()           # under DATA_DIR, not the image
        assert access.owner("run", run_id) == "person-1"                 # in DATA_DIR/access.db
    assert access.db_path() == tmp_path / "access.db"
    main.seed_data_dir()                                                 # what a restart or redeploy runs
    main.seed_public_runs()
    access.seed_passes()
    again = browser()                                                    # a new browser, the same link
    assert again.post("/api/access/exchange", json={"code": code}).status_code == 200
    assert {r["id"] for r in again.get("/api/runs").json()} == set(made)
    other, _, _ = with_pass("person-2")
    for viewer in (other, browser()):
        assert not set(made) & {r["id"] for r in viewer.get("/api/runs").json()}


@pytest.mark.parametrize("public", [True, False])
def test_the_retired_profound_showcase_left_on_a_disk_is_never_listed_or_served(env, tmp_path, monkeypatch, public):
    if not public:
        monkeypatch.delenv(access.PUBLIC_ENV)
    preload_examples(tmp_path)
    old_run, old_company = sorted(access.RETIRED)
    for kind, item, like in (("runs", old_run, main.SHOWCASE_RUN), ("companies", old_company, main.SHOWCASE_COMPANY)):
        body = json.loads((reports.BUNDLED / kind / f"{like}.json").read_text())
        (tmp_path / kind / f"{item}.json").write_text(json.dumps(body | {"id": item}))
    main.seed_data_dir()
    c = browser()
    assert old_run not in {r["id"] for r in c.get("/api/runs").json()}
    assert c.get(f"/api/runs/{old_run}").status_code == 404
    assert old_company not in {x["id"] for x in c.get("/api/companies").json()}
    assert c.get(f"/api/companies/{old_company}").status_code == 404
    assert main.SHOWCASE_RUN in {r["id"] for r in c.get("/api/runs").json()}
    kept = {p: p.read_bytes() for p in (tmp_path / "runs" / f"{old_run}.json", tmp_path / "companies" / f"{old_company}.json")}
    for method, url, body in (("POST", f"/api/companies/{old_company}/audit", None),
                              ("PATCH", f"/api/companies/{old_company}", {"weights": {}}),
                              ("DELETE", f"/api/companies/{old_company}/attributes/anything", None),
                              ("POST", f"/api/runs/{old_run}/rescore", {"weights": {}})):
        assert c.request(method, url, json=body).status_code in (403, 404), url
    assert all(p.read_bytes() == b for p, b in kept.items())            # left on disk, untouched


def test_a_fresh_data_dir_gets_every_committed_company_and_run(env, tmp_path):
    stale = tmp_path / "runs" / f"{main.SHOWCASE_RUN}.json"
    stale.write_text("{}")
    main.seed_data_dir()
    assert stale.read_bytes() == (reports.BUNDLED / "runs" / stale.name).read_bytes()
    for kind in ("companies", "runs"):
        bundled = {p.name for p in (reports.BUNDLED / kind).glob("*.json")}
        assert bundled and bundled <= {p.name for p in (tmp_path / kind).glob("*.json")}
    assert main.load_run(main.SHOWCASE_RUN).id == main.SHOWCASE_RUN


def test_health_names_the_contact_address_and_it_can_be_overridden(env, monkeypatch):
    assert browser().get("/api/health").json()["contact_email"] == access.CONTACT_DEFAULT
    monkeypatch.setenv(access.CONTACT_ENV, "someone@example.com")
    assert browser().get("/api/health").json()["contact_email"] == "someone@example.com"
    kind, data = events(browser().get(f"/api/stream?company={CO}&mode=live").text)[-1]
    assert "someone@example.com" in data["message"]
