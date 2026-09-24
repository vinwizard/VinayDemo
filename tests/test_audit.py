"""The retrievability audit and entity grounding, against recorded HTML, robots.txt and API answers."""
from pathlib import Path

import pytest

import audit
from schemas import Attribute, Company, CompanyProfile

FIX = Path(__file__).parent / "audit_fixtures"


def rec(name, status=200, ctype="text/html"):
    return status, ctype, (FIX / name).read_text()


SITE = {
    "https://www.acme.example/robots.txt": rec("robots.txt", ctype="text/plain"),
    "https://www.acme.example/": rec("home.html"),
    "https://www.acme.example/pricing": rec("pricing.html"),
    "https://www.acme.example/app": rec("app.html"),
    "https://www.acme.example/llms.txt": (404, "text/html", "<h1>Not found</h1>"),
    "https://www.wikidata.org/w/api.php?action=wbsearchentities": rec("wikidata_search.json", ctype="application/json"),
    "https://en.wikipedia.org/w/api.php?action=query": rec("wikipedia_search.json", ctype="application/json"),
    "https://www.wikidata.org/w/api.php?action=wbgetentities": rec("wikidata_entities.json", ctype="application/json"),
    "https://en.wikipedia.org/api/rest_v1/page/summary/Acme_Contracts": rec("wikipedia_summary.json", ctype="application/json"),
    "https://www.linkedin.com/robots.txt": rec("linkedin_robots.txt", ctype="text/plain"),
    "https://www.g2.com/robots.txt": (404, "text/html", ""),
    "https://www.g2.com/products/acme-contracts": (403, "text/html", "blocked"),
}


def recorded(responses):
    calls = []

    def get(url, accept=None):
        calls.append(url)
        for prefix, (status, ctype, body) in responses.items():
            if url == prefix or ("?" in prefix and url.startswith(prefix)):
                return url, status, ctype, body
        raise OSError(f"not recorded: {url}")
    get.calls = calls
    return get


def company(pages=("https://www.acme.example/", "https://www.acme.example/pricing", "https://www.acme.example/app")):
    claim = lambda i, label, quote: Attribute(id=i, label=label, claim_quotes=[quote], claim_evidence_ids=["e"])
    return Company(id="c1", profile=CompanyProfile(name="Acme", domain="acme.example"), pages=list(pages), attributes=[
        claim("search", "Clause search", "Search every clause in seconds."),
        claim("seats", "Unlimited seats", "Unlimited seats on every plan"),
        claim("gone", "Redlining", "Redline with one click"),
        Attribute(id="added", label="Typed by the customer", added_by_user=True, intended_weight=0.5),
    ])


@pytest.fixture
def result(monkeypatch):
    monkeypatch.setattr(audit, "get", recorded(SITE))
    return audit.run(company())


def checks(claim):
    return {c.key: c for c in claim.checks}


def test_a_readable_claim_passes_every_check_that_its_page_earns(result):
    search = checks(result.claims[0])
    assert result.claims[0].page_url == "https://www.acme.example/"
    assert search["crawlers"].status == "pass"
    assert search["raw_text"].status == "pass"
    assert search["markup"].status == "pass" and "Organization" in search["markup"].detail
    assert search["headings"].status == "pass" and "How does Acme find a clause?" in search["headings"].detail
    assert search["speed"].status == "pass"


def test_robots_blocking_ai_crawlers_is_named_per_claim_page(result):
    seats = checks(result.claims[1])
    assert seats["crawlers"].status == "fail"
    assert "GPTBot" in seats["crawlers"].detail and "ClaudeBot" in seats["crawlers"].detail
    assert "PerplexityBot" not in seats["crawlers"].detail
    assert seats["markup"].status == "fail" and seats["headings"].status == "fail"


def test_a_claim_no_longer_in_the_plain_html_is_flagged_with_the_script_heavy_page(result):
    gone = checks(result.claims[2])
    assert result.claims[2].page_url is None
    assert gone["raw_text"].status == "fail" and "/app" in gone["raw_text"].detail
    assert {gone[k].status for k in ("crawlers", "markup", "headings", "speed")} == {"unknown"}


def test_only_claims_the_site_states_are_audited(result):
    assert [c.attribute_id for c in result.claims] == ["search", "seats", "gone"]


def test_site_checks_find_no_llms_txt_and_the_script_only_page(result):
    site = {c.key: c for c in result.site}
    assert site["llms_txt"].status == "fail"          # a 404 served as HTML is not an llms.txt
    assert site["no_js"].status == "fail" and "/app" in site["no_js"].detail


def test_wikidata_is_tied_by_official_website_not_by_name(result):
    by = {e.source: e for e in result.entities}
    assert by["Wikidata"].status == "found" and by["Wikidata"].url.endswith("Q333")
    assert by["Wikidata"].says == "contract management software company"   # not the cartoon Acme
    assert by["Wikipedia"].status == "found"
    assert by["Wikipedia"].says == "Acme Contracts is an American software company that makes contract search tools."


def test_profiles_come_only_from_the_sites_own_links_and_blocked_sources_are_not_checked(result):
    by = {e.source: e for e in result.entities}
    assert by["LinkedIn"].status == "not_checked" and "does not allow" in by["LinkedIn"].summary
    assert by["G2"].status == "not_checked" and "turned our automated check away" in by["G2"].summary
    assert by["Crunchbase"].status == "not_checked" and "do not guess" in by["Crunchbase"].summary


def test_no_wikidata_entry_on_the_domain_is_missing_not_a_lookalike(monkeypatch):
    monkeypatch.setattr(audit, "get", recorded({**SITE, "https://www.wikidata.org/w/api.php?action=wbgetentities":
                                                (200, "application/json", '{"entities":{}}')}))
    by = {e.source: e for e in audit.run(company()).entities}
    assert by["Wikidata"].status == "missing" and by["Wikipedia"].status == "missing"


def test_a_slow_page_fails_speed():
    page = audit.Page("https://www.acme.example/", html=(FIX / "home.html").read_text(), seconds=4.2)
    speed = {c.key: c for c in audit.page_checks(page)}["speed"]
    assert speed.status == "fail" and "4.2 s" in speed.detail


def test_our_own_fetches_honour_robots_txt(monkeypatch):
    get = recorded({**SITE, "https://www.acme.example/robots.txt": (200, "text/plain", "User-agent: OffMessage\nDisallow: /")})
    monkeypatch.setattr(audit, "get", get)
    result = audit.run(company())
    assert not any(u.startswith("https://www.acme.example/") and not u.endswith("robots.txt") for u in get.calls)
    assert all(checks(c)["raw_text"].status == "unknown" for c in result.claims)
    assert "asks automated tools like ours not to read it" in checks(result.claims[0])["raw_text"].detail


def test_nothing_reachable_is_could_not_check_everywhere_never_a_guess():
    result = audit.run(company())                      # conftest: every fetch fails
    assert {c.status for c in result.site} == {"unknown"}
    assert {k.status for c in result.claims for k in c.checks} == {"unknown"}
    assert {e.status for e in result.entities} == {"not_checked"}


def test_a_shell_that_loads_its_code_from_script_files_is_script_only(monkeypatch):
    monkeypatch.setattr(audit, "get", recorded({**SITE, "https://www.acme.example/app": rec("spa.html")}))
    result = audit.run(company())
    assert {c.key: c for c in result.site}["no_js"].status == "fail"
    gone = checks(result.claims[2])
    assert "/app is a near-empty shell" in gone["raw_text"].detail


def test_a_claim_on_several_pages_passes_on_the_readable_one_and_lists_the_blocked_one(monkeypatch):
    pricing = (200, "text/html", "<h1>Plans</h1><p>Search every clause in seconds.</p>")
    monkeypatch.setattr(audit, "get", recorded({**SITE, "https://www.acme.example/pricing": pricing}))
    search = audit.run(company()).claims[0]
    assert search.page_url == "https://www.acme.example/"
    assert checks(search)["crawlers"].status == "pass"
    assert any("/pricing" in a and "GPTBot" in a and "ClaudeBot" in a for a in search.advice)


def test_the_blocked_page_is_checked_when_no_readable_page_states_the_claim(result):
    seats = result.claims[1]
    assert seats.page_url == "https://www.acme.example/pricing" and seats.advice == []


def test_headings_pass_without_question_subheadings_and_questions_are_only_advice():
    html = "<h1>Acme</h1><h2>What we do</h2><p>Search every clause in seconds.</p>"
    page = audit.Page("https://www.acme.example/", html=html, seconds=0.2)
    assert {c.key: c for c in audit.page_checks(page)}["headings"].status == "pass"
    rules = audit.RobotFileParser()
    rules.parse([])
    advice = audit.claim_audit(company().attributes[0], [page], (rules, False)).advice
    assert any("question" in a for a in advice)
    no_sub = audit.Page("https://www.acme.example/", html="<h1>Acme</h1><p>x</p>", seconds=0.2)
    assert {c.key: c for c in audit.page_checks(no_sub)}["headings"].status == "fail"


def test_a_short_server_rendered_page_with_an_analytics_tag_is_not_script_only(monkeypatch):
    monkeypatch.setattr(audit, "get", recorded({**SITE, "https://www.acme.example/app": rec("contact.html")}))
    result = audit.run(company())
    assert {c.key: c for c in result.site}["no_js"].status == "pass"
