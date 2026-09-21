"""Agent 1 model-backed extraction. No key, no network: the transport is injected."""
import json

import pytest

from agents.onboarding_model import OnboardingAgent, _useful_description, build_attributes, parse

PAGES = [
    ("https://example.com/",
     "Acme is the connected workspace where teams keep docs and databases in one place. "
     "Trusted by thousands of teams."),
    ("https://example.com/enterprise",
     "Acme for enterprise offers SAML single sign-on, audit logs and SCIM provisioning so IT can "
     "roll out Acme company-wide."),
]


def payload(**over):
    data = {
        "name": "Acme", "aliases": ["Acme Inc"], "one_liner": "The connected workspace.",
        "customer_types": ["startups"],
        "attributes": [{
            "id": "enterprise_ready", "label": "Enterprise ready",
            "description": "Offers SAML single sign-on, audit logs and SCIM provisioning for "
                           "company-wide IT rollout.",
            "aliases": ["enterprise-grade"],
            "claim_quotes": ["SAML single sign-on, audit logs and SCIM provisioning"],
            "buyer_questions": ["Which workspace tools support SAML and audit logging?"],
        }],
    }
    data.update(over)
    return json.dumps(data)


def agent(raw):
    return OnboardingAgent(model="test", transport=lambda *_: raw)


# --- the page-count fix ------------------------------------------------------
def test_claim_pages_is_counted_from_validated_quotes_not_taken_from_the_model():
    """The old fixtures asserted claim_pages 6/8 with nothing fetched. It must be derived."""
    _, attrs, _ = agent(payload()).run("Acme", "example.com", PAGES)
    a = attrs[0]
    assert a.claim_pages == 1 and a.claim_pages_total == 2   # quote appears on page 2 only
    assert a.claim_evidence_ids == ["pg2"]


def test_model_supplied_page_counts_are_ignored():
    raw = json.loads(payload())
    raw["attributes"][0]["claim_pages"] = 99
    raw["attributes"][0]["claim_pages_total"] = 99
    _, attrs, _ = agent(json.dumps(raw)).run("Acme", "example.com", PAGES)
    assert attrs[0].claim_pages == 1 and attrs[0].claim_pages_total == 2


def test_quote_on_every_page_counts_every_page():
    pages = [("https://example.com/a", "Acme has audit logs everywhere."),
             ("https://example.com/b", "Acme has audit logs everywhere too.")]
    raw = json.loads(payload())
    raw["attributes"][0]["claim_quotes"] = ["Acme has audit logs"]
    _, attrs, _ = agent(json.dumps(raw)).run("Acme", "example.com", pages)
    assert attrs[0].claim_pages == 2 and attrs[0].claim_pages_total == 2


# --- quotes are never trusted ------------------------------------------------
def test_unverifiable_quote_drops_the_attribute():
    raw = json.loads(payload())
    raw["attributes"][0]["claim_quotes"] = ["Acme is ISO 27001 certified"]   # not on any page
    _, attrs, warnings = agent(json.dumps(raw)).run("Acme", "example.com", PAGES)
    assert attrs == []
    assert any("no verifiable quote" in w for w in warnings)
    assert any("nothing can be measured" in w for w in warnings)


def test_partially_hallucinated_quotes_keep_only_the_real_ones():
    raw = json.loads(payload())
    raw["attributes"][0]["claim_quotes"] = ["audit logs and SCIM provisioning", "we are ISO 27001"]
    _, attrs, warnings = agent(json.dumps(raw)).run("Acme", "example.com", PAGES)
    assert attrs[0].claim_quotes == ["audit logs and SCIM provisioning"]
    assert any("not verbatim" in w for w in warnings)


# --- the actual complaint: labels that explain nothing ------------------------
def test_description_that_restates_the_label_is_flagged():
    raw = json.loads(payload())
    raw["attributes"][0]["description"] = "Enterprise ready for enterprises."
    _, attrs, warnings = agent(json.dumps(raw)).run("Acme", "example.com", PAGES)
    assert any("restates the label" in w for w in warnings)


def test_a_real_description_is_kept_without_complaint():
    _, attrs, warnings = agent(payload()).run("Acme", "example.com", PAGES)
    assert "SCIM" in attrs[0].description
    assert not any("restates the label" in w for w in warnings)


def test_missing_description_is_flagged():
    raw = json.loads(payload())
    raw["attributes"][0]["description"] = ""
    _, attrs, warnings = agent(json.dumps(raw)).run("Acme", "example.com", PAGES)
    assert attrs[0].description is None
    assert any("too thin" in w or "restates" in w for w in warnings)


# --- the three layers stay separate ------------------------------------------
def test_onboarding_never_sets_intent():
    """Crawling establishes what they CLAIM. What they want to be known for is the customer's."""
    _, attrs, _ = agent(payload()).run("Acme", "example.com", PAGES)
    assert all(a.intended_weight is None for a in attrs)
    assert all(not a.intended for a in attrs)


def test_profile_says_intent_is_not_derivable():
    profile, _, _ = agent(payload()).run("Acme", "example.com", PAGES)
    assert any("not derivable" in w for w in profile.warnings)
    assert [e.source_type for e in profile.evidence] == ["page_fetch", "page_fetch"]


# --- malformed model output --------------------------------------------------
def test_non_json_output_raises():
    with pytest.raises(ValueError, match="no JSON object"):
        parse("I could not find anything useful.")


def test_missing_attributes_list_raises():
    with pytest.raises(ValueError, match="no attributes list"):
        parse('{"name": "Acme"}')


def test_no_pages_is_refused():
    with pytest.raises(ValueError, match="at least one fetched page"):
        agent(payload()).run("Acme", "example.com", [])


def test_unlabelled_attribute_is_dropped():
    raw = json.loads(payload())
    raw["attributes"].append({"id": "x", "claim_quotes": ["audit logs"]})
    attrs, warnings = build_attributes(raw, PAGES)
    assert [a.id for a in attrs] == ["enterprise_ready"]
    assert any("no label" in w for w in warnings)


def test_description_restating_a_hyphenated_label_is_rejected():
    assert not _useful_description("Real-time collaboration", "Real-time collaboration, done in real-time.")
    assert not _useful_description("All-in-one workspace", "An all-in-one workspace for teams.")
    assert _useful_description("Real-time collaboration",
                               "Several people edit the same page and see each other's cursors live.")
