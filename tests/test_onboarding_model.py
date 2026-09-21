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
            "description": "Acme offers SAML single sign-on, audit logs and SCIM provisioning for "
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


def notes(checks):
    return [n for c in checks for n in c.notes]


# --- the page-count fix ------------------------------------------------------
def test_claim_pages_is_counted_from_validated_quotes_not_taken_from_the_model():
    """The old fixtures asserted claim_pages 6/8 with nothing fetched. It must be derived."""
    _, attrs, _, _ = agent(payload()).run("Acme", "example.com", PAGES)
    a = attrs[0]
    assert a.claim_pages == 1 and a.claim_pages_total == 2   # quote appears on page 2 only
    assert a.claim_evidence_ids == ["pg2"]


def test_model_supplied_page_counts_are_ignored():
    raw = json.loads(payload())
    raw["attributes"][0]["claim_pages"] = 99
    raw["attributes"][0]["claim_pages_total"] = 99
    _, attrs, _, _ = agent(json.dumps(raw)).run("Acme", "example.com", PAGES)
    assert attrs[0].claim_pages == 1 and attrs[0].claim_pages_total == 2


def test_quote_on_every_page_counts_every_page():
    pages = [("https://example.com/a", "Acme has audit logs everywhere."),
             ("https://example.com/b", "Acme has audit logs everywhere too.")]
    raw = json.loads(payload())
    raw["attributes"][0]["claim_quotes"] = ["Acme has audit logs everywhere"]
    _, attrs, _, _ = agent(json.dumps(raw)).run("Acme", "example.com", pages)
    assert attrs[0].claim_pages == 2 and attrs[0].claim_pages_total == 2


# --- quotes are never trusted ------------------------------------------------
def test_unverifiable_quote_drops_the_attribute():
    raw = json.loads(payload())
    raw["attributes"][0]["claim_quotes"] = ["Acme is ISO 27001 certified"]   # not on any page
    _, attrs, warnings, checks = agent(json.dumps(raw)).run("Acme", "example.com", PAGES)
    assert attrs == []
    assert any("No verifiable quote" in n for n in notes(checks))
    assert any("nothing can be measured" in w for w in warnings)
    [c] = checks   # one entry per claim, never listed twice, under its plain label
    assert (c.label, c.kept, c.quotes_matched, c.quotes_removed) == ("Enterprise ready", False, 0, 1)
    assert c.not_found


def test_partially_hallucinated_quotes_keep_only_the_real_ones():
    raw = json.loads(payload())
    raw["attributes"][0]["claim_quotes"] = ["audit logs and SCIM provisioning",
                                            "we are ISO 27001 certified today"]
    _, attrs, _, checks = agent(json.dumps(raw)).run("Acme", "example.com", PAGES)
    assert attrs[0].claim_quotes == ["audit logs and SCIM provisioning"]
    assert any("not verbatim" in n for n in notes(checks))
    [c] = checks
    assert (c.kept, c.quotes_matched, c.quotes_removed) == (True, 1, 1)


# --- the actual complaint: claims nothing could contradict ---------------------
def test_description_that_restates_the_label_is_rejected():
    raw = json.loads(payload())
    raw["attributes"][0]["description"] = "Enterprise ready for enterprises."
    _, attrs, _, checks = agent(json.dumps(raw)).run("Acme", "example.com", PAGES)
    assert attrs == [] and any("restates the label" in n for n in notes(checks))
    assert not checks[0].kept and checks[0].quotes_matched == 1   # found, but not checkable
    assert not checks[0].not_found


@pytest.mark.parametrize("statement,why", [
    # the two statements the first live linear.app onboard actually produced
    ("The platform reduces noise and restores momentum, allowing teams to ship products rapidly "
     "and with focus.", "does not name the company"),
    ("Designed specifically for contemporary product development practices, accommodating scaling "
     "needs as teams grow.", "does not name the company"),
    ("Acme minimizes noise and friction, allowing teams to focus and maintain high velocity.",
     "marketing language"),
    ("Acme lets IT roll out SSO seamlessly across the whole company.", "marketing language"),
])
def test_marketing_paraphrase_is_rejected_not_kept(statement, why):
    raw = json.loads(payload())
    raw["attributes"][0]["description"] = statement
    _, attrs, _, checks = agent(json.dumps(raw)).run("Acme", "example.com", PAGES)
    assert attrs == []
    assert any(why in n and statement in n for n in notes(checks))   # the loss is shown, not silent


def test_a_checkable_assertion_passes():
    raw = json.loads(payload())
    raw["attributes"][0]["description"] = ("Acme is fast by design - issues open instantly and the "
                                           "whole app is keyboard-first")
    _, attrs, warnings, checks = agent(json.dumps(raw)).run("Acme", "example.com", PAGES)
    assert [a.id for a in attrs] == ["enterprise_ready"] and not warnings and not notes(checks)
    assert [(c.kept, c.quotes_matched, c.quotes_removed) for c in checks] == [(True, 1, 0)]


@pytest.mark.parametrize("statement,rejected", [
    ("Modern Treasury offers SAML single sign-on, audit logs and SCIM provisioning for IT.", False),
    ("Modern Treasury lets IT roll out SSO seamlessly across the whole company.", True),
])
def test_a_marketing_word_in_the_company_name_is_not_marketing(statement, rejected):
    raw = json.loads(payload(name="Modern Treasury", aliases=[]))
    raw["attributes"][0]["description"] = statement
    _, attrs, _, checks = agent(json.dumps(raw)).run("Modern Treasury", "example.com", PAGES)
    assert (attrs == []) is rejected
    assert any("seamlessly" in n for n in notes(checks)) is rejected


def test_a_real_description_is_kept_without_complaint():
    _, attrs, _, checks = agent(payload()).run("Acme", "example.com", PAGES)
    assert "SCIM" in attrs[0].description
    assert not any("restates the label" in n for n in notes(checks))


def test_missing_description_is_rejected():
    raw = json.loads(payload())
    raw["attributes"][0]["description"] = ""
    _, attrs, _, checks = agent(json.dumps(raw)).run("Acme", "example.com", PAGES)
    assert attrs == [] and any("too thin" in n for n in notes(checks))


# --- page counts come from every page ------------------------------------------
def test_quotes_filed_by_page_count_every_page_that_states_it():
    pages = PAGES + [("https://example.com/security",
                      "Security first: SAML single sign-on, audit logs and SCIM provisioning.")]
    raw = json.loads(payload())
    raw["attributes"][0]["claim_quotes"] = {"2": "SAML single sign-on, audit logs and SCIM provisioning",
                                            "3": "Security first: SAML single sign-on"}
    _, attrs, _, _ = agent(json.dumps(raw)).run("Acme", "example.com", pages)
    assert attrs[0].claim_pages == 2 and attrs[0].claim_evidence_ids == ["pg2", "pg3"]


def test_a_nav_label_on_every_page_does_not_count():
    """Asking for a quote from every page invites "Available today" from the site chrome."""
    pages = [(f"https://example.com/{i}", "Available today. " + t) for i, (_, t) in enumerate(PAGES)]
    raw = json.loads(payload())
    raw["attributes"][0]["claim_quotes"] = ["Available today",
                                            "SAML single sign-on, audit logs and SCIM provisioning"]
    _, attrs, _, checks = agent(json.dumps(raw)).run("Acme", "example.com", pages)
    assert attrs[0].claim_pages == 1 and attrs[0].claim_quotes == [
        "SAML single sign-on, audit logs and SCIM provisioning"]
    assert any("too short" in n for n in notes(checks))
    assert checks[0].quotes_removed == 1   # a too-short quote counts as removed


def test_the_company_name_always_counts_as_a_mention():
    """The model lists product names as aliases; the bare name must still count as the brand."""
    profile, _, _, _ = agent(payload(aliases=["Acme Agent"])).run("Acme", "example.com", PAGES)
    assert profile.aliases == ["Acme", "Acme Agent"]


# --- the three layers stay separate ------------------------------------------
def test_onboarding_never_sets_intent():
    """Crawling establishes what they CLAIM. What they want to be known for is the customer's."""
    _, attrs, _, _ = agent(payload()).run("Acme", "example.com", PAGES)
    assert all(a.intended_weight is None for a in attrs)
    assert all(not a.intended for a in attrs)


def test_profile_says_intent_is_not_derivable():
    profile, _, _, _ = agent(payload()).run("Acme", "example.com", PAGES)
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
    attrs, checks = build_attributes(raw, PAGES)
    assert [a.id for a in attrs] == ["enterprise_ready"]
    assert any("no name" in n for n in notes(checks))
    assert checks[1].label == "Unnamed claim 2" and not checks[1].kept
    assert not checks[1].not_found   # listed as could-not-be-checked, not as missing from the pages


def test_description_restating_a_hyphenated_label_is_rejected():
    assert not _useful_description("Real-time collaboration", "Real-time collaboration, done in real-time.")
    assert not _useful_description("All-in-one workspace", "An all-in-one workspace for teams.")
    assert _useful_description("Real-time collaboration",
                               "Several people edit the same page and see each other's cursors live.")
