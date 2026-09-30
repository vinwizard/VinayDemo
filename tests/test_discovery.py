"""Onboarding from a name: finding the company, and reading its own pages through search when its site
turns our reader away. Every search response here was recorded from a real call on 2026-09-28
(tests/discovery_fixtures/, result text trimmed), so no test reaches the network."""
import json
from pathlib import Path

import pytest

import discovery
import fetching

FIXTURES = Path(__file__).parent / "discovery_fixtures"


def recorded(name: str):
    response = json.loads((FIXTURES / f"{name}.json").read_text())
    return lambda prompt, model, timeout: response


def blocked(url):
    raise fetching.FetchError(f"{url} turns automated readers away (HTTP 403 for {url})")


def search_result(url, text, title=None):
    return {"type": "web_search_call", "action": {"type": "search", "query": "q"},
            "results": [{"url": url, "title": title, "text": text}]}


def response(*results, answer="{}"):
    return {"output": [*results, {"type": "message", "content": [{"type": "output_text", "text": answer}]}]}


# ---------------------------------------------------------------- find
def test_a_name_alone_finds_the_company_and_its_domain():
    found = discovery.find("Perplexity", transport=recorded("find-perplexity"))
    assert [(c["name"], c["domain"], c["exact"]) for c in found["candidates"]] == \
        [("Perplexity AI, Inc.", "perplexity.ai", True)]
    assert found["candidates"][0]["what"]


def test_a_shared_name_offers_each_company_to_choose_from():
    found = discovery.find("Mercury", transport=recorded("find-mercury"))
    assert [c["domain"] for c in found["candidates"]] == ["mercury.com", "mercuryinsurance.com"]


def test_a_name_no_company_has_is_not_passed_off_as_a_match():
    """Asked about "Vellora Analytics", the search returned near-misses rather than nothing: each
    one is offered as not an exact match, so the customer is warned before picking one."""
    found = discovery.find("Vellora Analytics", transport=recorded("find-vellora"))
    assert found["candidates"] and not found["exact"]
    assert not any(c["exact"] for c in found["candidates"])


def test_a_domain_that_no_search_result_showed_is_never_offered():
    answer = json.dumps({"candidates": [
        {"name": "Acme", "domain": "https://www.acme.example/about", "what": "Makes anvils."},
        {"name": "Acme Invented", "domain": "acme-invented.example", "what": "Made up by the model."},
        {"name": "Acme Local", "domain": "localhost", "what": "Not a public address."}]})
    found = discovery.find("Acme", transport=lambda *a: response(
        search_result("https://acme.example/?trk=ad", "Acme makes anvils."), answer=answer))
    assert [c["domain"] for c in found["candidates"]] == ["acme.example"]


def test_a_search_that_fails_says_so_in_plain_words():
    def down(*a):
        raise ConnectionError("reset")
    with pytest.raises(discovery.SearchFailed, match="Web search is not available right now"):
        discovery.find("Acme", transport=down)


# ---------------------------------------------------------------- gather
def test_a_site_that_turns_us_away_is_read_from_search_copies():
    """perplexity.ai answers every automated reader with a "verify you are human" check."""
    pages, meta, others = discovery.gather("Perplexity", "perplexity.ai", 7,
                                           transport=recorded("gather-perplexity"), fetch=blocked)
    urls = [u for u, _ in pages]
    assert len(pages) == 7 and all(m["source_type"] == "search_copy" for m in meta)
    assert urls[0] == "https://hub-prod.perplexity.ai"                           # the front page ranks first
    assert all(fetching.urlparse(u).hostname.endswith("perplexity.ai") for u in urls)
    assert not any("/es/" in u or "?" in u for u in urls)                        # other languages, tracking: out
    assert all(m["saved"] and m["retrieved_at"] for m in meta)                   # when the search engine saved it
    assert not any(t.startswith(("Crawled:", "Published:")) for _, t in pages)   # its preface is not the page
    assert "https://en.wikipedia.org/wiki/Perplexity_AI" in [o.url for o in others]
    assert {o.source_type for o in others} == {"third_party"}


def test_a_page_that_lets_us_in_is_read_directly_and_one_refusal_per_host_is_enough():
    tried = []

    def fetch(url):
        tried.append(url)
        if "hub-prod" in url:
            return url, "Perplexity hub: everything Perplexity publishes about itself, in full."
        return blocked(url)
    pages, meta, _ = discovery.gather("Perplexity", "perplexity.ai", 7,
                                      transport=recorded("gather-perplexity"), fetch=fetch)
    assert meta[0] == {} and pages[0][1].startswith("Perplexity hub")          # read directly, the whole page
    assert sum("www.perplexity.ai" in u for u in tried) == 1                     # then that host is not retried


def test_only_the_companys_own_pages_that_name_it_count_as_its_own():
    """perplexity.ai also serves other companies' SEC filings: on the domain, not its words."""
    pages, _, others = discovery.gather("Acme", "acme.example", 8, fetch=blocked, transport=lambda *a: response(
        search_result("https://acme.example/about", "Acme makes anvils for cartoon coyotes."),
        search_result("https://docs.acme.example/start", "Getting started with Acme anvils."),
        search_result("https://acme.example/filings/0001", "We are a blank check company incorporated in 2025."),
        search_result("https://acme.example.evil.test/about", "Acme, as told by a lookalike domain."),
        search_result("https://en.wikipedia.org/wiki/Acme", "Acme is a fictional anvil maker."),
        search_result("https://news.example/story", "A story that never names the company.")))
    assert [u for u, _ in pages] == ["https://acme.example/about", "https://docs.acme.example/start"]
    assert [o.url for o in others] == ["https://acme.example.evil.test/about", "https://en.wikipedia.org/wiki/Acme"]


def test_pages_already_read_directly_are_not_read_twice():
    pages, _, _ = discovery.gather("Acme", "acme.example", 8, have=["https://www.acme.example/about/"],
                                   fetch=blocked, transport=lambda *a: response(
                                       search_result("https://acme.example/about", "Acme makes anvils."),
                                       search_result("https://acme.example/pricing", "Acme anvils cost less.")))
    assert [u for u, _ in pages] == ["https://acme.example/pricing"]


@pytest.mark.parametrize("url,foreign", [
    ("https://x.example/ai", False), ("https://x.example/en-GB/hub", False),
    ("https://x.example/solutions/it-teams", False), ("https://x.example/blog/de-risk", False),
    ("https://x.example/es-MX/hub/careers", True), ("https://x.example/help-center/nl/articles/1", True),
])
def test_other_languages_are_told_apart_from_short_words(url, foreign):
    assert discovery.foreign(url) is foreign


def test_the_names_that_mark_a_page_as_the_companys():
    assert discovery.names_of("Perplexity AI, Inc.", "perplexity.ai") == ["Perplexity AI, Inc.", "Perplexity AI", "perplexity"]
    assert discovery.names_company("Built by PERPLEXITY", ["perplexity"])
    assert not discovery.names_company("perplexityish", ["perplexity"])
