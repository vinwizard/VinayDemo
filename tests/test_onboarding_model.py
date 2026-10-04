"""Agent 1 model-backed extraction. No key, no network: the transport is injected."""
import json

import pytest

from agents.onboarding_model import _useful_description, build_attributes, onboard, parse

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


def onboarded(raw, *args):
    return onboard(*args, model="test", transport=lambda *_: raw)


def run(pages=PAGES, **attr):
    """Onboard Acme from the default payload, its one claim's fields overridden by `attr`."""
    raw = json.loads(payload())
    raw["attributes"][0].update(attr)
    return onboarded(json.dumps(raw), "Acme", "example.com", pages)


def notes(checks):
    return [n for c in checks for n in c.notes]


# --- the page-count fix ------------------------------------------------------
def test_claim_pages_is_counted_from_validated_quotes_not_taken_from_the_model():
    """The old fixtures asserted claim_pages 6/8 with nothing fetched. It must be derived."""
    _, attrs, _, _ = run(claim_pages=99, claim_pages_total=99)
    a = attrs[0]
    assert a.claim_pages == 1 and a.claim_pages_total == 2   # quote appears on page 2 only
    assert a.claim_evidence_ids == ["pg2"]


def test_quote_on_every_page_counts_every_page():
    pages = [("https://example.com/a", "Acme has audit logs everywhere."),
             ("https://example.com/b", "Acme has audit logs everywhere too.")]
    _, attrs, _, _ = run(pages, claim_quotes=["Acme has audit logs everywhere"])
    assert attrs[0].claim_pages == 2 and attrs[0].claim_pages_total == 2


# --- quotes are never trusted ------------------------------------------------
def test_unverifiable_quote_drops_the_attribute():
    _, attrs, warnings, checks = run(claim_quotes=["Acme is ISO 27001 certified"])   # not on any page
    assert attrs == []
    assert any("No verifiable quote" in n for n in notes(checks))
    assert any("nothing can be measured" in w for w in warnings)
    [c] = checks   # one entry per claim, never listed twice, under its plain label
    assert (c.label, c.kept, c.quotes_matched, c.quotes_removed) == ("Enterprise ready", False, 0, 1)
    assert c.not_found


def test_partially_hallucinated_quotes_keep_only_the_real_ones():
    _, attrs, _, checks = run(claim_quotes=["audit logs and SCIM provisioning", "we are ISO 27001 certified today"])
    assert attrs[0].claim_quotes == ["audit logs and SCIM provisioning"]
    assert any("not verbatim" in n for n in notes(checks))
    [c] = checks
    assert (c.kept, c.quotes_matched, c.quotes_removed) == (True, 1, 1)


# --- the actual complaint: claims nothing could contradict ---------------------
@pytest.mark.parametrize("description,note", [("Enterprise ready for enterprises.", "restates the label"),
                                                ("", "too thin")])
def test_a_description_nothing_could_contradict_is_rejected(description, note):
    _, attrs, _, checks = run(description=description)
    assert attrs == [] and any(note in n for n in notes(checks))
    assert not checks[0].kept and checks[0].quotes_matched == 1   # found, but not checkable
    assert not checks[0].not_found


@pytest.mark.parametrize("statement", [
    # the two statements the first live linear.app onboard actually produced
    "The platform reduces noise and restores momentum, allowing teams to ship products rapidly "
    "and with focus.",
    "Designed specifically for contemporary product development practices, accommodating scaling "
    "needs as teams grow.",
])
def test_a_statement_that_does_not_name_the_company_is_rejected(statement):
    _, attrs, _, checks = run(description=statement)
    assert attrs == []
    assert any("does not name the company" in n and statement in n for n in notes(checks))


@pytest.mark.parametrize("statement,words", [
    ("Acme minimizes noise and friction, allowing teams to focus and maintain high velocity.", "friction"),
    ("Acme lets IT roll out SSO seamlessly across the whole company.", "seamlessly"),
])
def test_marketing_language_flags_a_claim_for_review_and_never_drops_it(statement, words):
    _, attrs, _, checks = run(description=statement)
    [a] = attrs
    assert a.description == statement and not a.set_aside     # kept as written, and measured
    assert words in a.review
    assert checks[0].kept and any("Kept for your review" in n for n in notes(checks))


# Amgen on gpt-6-luna, 22 Sep 2026: all three statements were deleted for "innovative" or "innovator"
# although their quotes were on amgen.com. The first is its own one-liner; with it gone, discovery
# reported "Broad treatment portfolio" as an identity AI imposed, and claim echo read 0.0.
AMGEN_PAGE = ("Amgen discovers, develops, manufactures and delivers innovative medicines to fight some "
              "of the world’s toughest diseases. We focus on cardiovascular/metabolic, bone health, "
              "inflammation, oncology and rare diseases.")


@pytest.mark.parametrize("label,statement", [
    ("Develops innovative medicines", "Amgen discovers, develops, manufactures and delivers innovative "
                                      "medicines to fight some of the world’s toughest diseases."),
    ("Focus on key therapeutic areas", "Amgen delivers innovative medicines in cardiovascular/metabolic, "
                                       "bone health, inflammation, oncology and rare diseases therapeutic areas."),
    ("Pioneer and leader in biotechnology since 1980", "Amgen helped establish the biotechnology industry "
                                                       "over 45 years ago and continues as a leading "
                                                       "independent biotech innovator globally."),
])
def test_amgens_core_claims_survive_onboarding_flagged_for_review(label, statement):
    raw = {"name": "Amgen", "aliases": [], "attributes": [{
        "id": "core", "label": label, "description": statement,
        "claim_quotes": ["Amgen discovers, develops, manufactures and delivers innovative medicines"]}]}
    _, attrs, _, _ = onboarded(json.dumps(raw), "Amgen", "amgen.com", [("https://www.amgen.com", AMGEN_PAGE)])
    [a] = attrs
    assert a.review and "innovat" in a.review and a.claim_pages == 1


@pytest.mark.parametrize("statement,flagged", [
    ("Modern Treasury offers SAML single sign-on, audit logs and SCIM provisioning for IT.", False),
    ("Modern Treasury lets IT roll out SSO seamlessly across the whole company.", True),
])
def test_a_marketing_word_in_the_company_name_is_not_marketing(statement, flagged):
    raw = json.loads(payload(name="Modern Treasury", aliases=[]))
    raw["attributes"][0]["description"] = statement
    _, attrs, _, _ = onboarded(json.dumps(raw), "Modern Treasury", "example.com", PAGES)
    [a] = attrs
    assert bool(a.review) is flagged and ("seamlessly" in (a.review or "")) is flagged


def test_a_quote_differing_only_in_apostrophes_case_or_spacing_matches_the_page_spelling():
    page = "Amgen discovers medicines to fight some of the world’s  toughest\u00a0diseases."
    raw = {"name": "Amgen", "attributes": [{
        "id": "core", "label": "Tough diseases",
        "description": "Amgen develops medicines for cancer, bone loss and rare genetic diseases.",
        "claim_quotes": ["medicines to fight some of the World's toughest diseases",
                         "medicines to fight some of the world's hardest diseases"]}]}
    _, attrs, _, checks = onboarded(json.dumps(raw), "Amgen", "amgen.com", [("https://www.amgen.com", page)])
    [a] = attrs
    assert a.claim_quotes == ["medicines to fight some of the world’s  toughest\u00a0diseases"]  # as the page writes it
    assert a.claim_quotes[0] in page
    assert (checks[0].quotes_matched, checks[0].quotes_removed) == (1, 1)   # a changed word still fails


@pytest.mark.parametrize("description", [
    "Acme offers SAML single sign-on, audit logs and SCIM provisioning for company-wide IT rollout.",
    "Acme is fast by design - issues open instantly and the whole app is keyboard-first"])
def test_a_checkable_assertion_is_kept_without_complaint(description):
    _, attrs, warnings, checks = run(description=description)
    assert [a.description for a in attrs] == [description] and not warnings and not notes(checks)
    assert [(c.kept, c.quotes_matched, c.quotes_removed) for c in checks] == [(True, 1, 0)]


# --- page counts come from every page ------------------------------------------
def test_quotes_filed_by_page_count_every_page_that_states_it():
    pages = PAGES + [("https://example.com/security",
                      "Security first: SAML single sign-on, audit logs and SCIM provisioning.")]
    _, attrs, _, _ = run(pages, claim_quotes={"2": "SAML single sign-on, audit logs and SCIM provisioning",
                                              "3": "Security first: SAML single sign-on"})
    assert attrs[0].claim_pages == 2 and attrs[0].claim_evidence_ids == ["pg2", "pg3"]


def test_a_nav_label_on_every_page_does_not_count():
    """Asking for a quote from every page invites "Available today" from the site chrome."""
    pages = [(f"https://example.com/{i}", "Available today. " + t) for i, (_, t) in enumerate(PAGES)]
    _, attrs, _, checks = run(pages, claim_quotes=["Available today",
                                                   "SAML single sign-on, audit logs and SCIM provisioning"])
    assert attrs[0].claim_pages == 1 and attrs[0].claim_quotes == [
        "SAML single sign-on, audit logs and SCIM provisioning"]
    assert any("too short" in n for n in notes(checks))
    assert checks[0].quotes_removed == 1   # a too-short quote counts as removed


def test_the_company_name_always_counts_as_a_mention():
    """The model lists product names as aliases; the bare name must still count as the brand."""
    profile, _, _, _ = onboarded(payload(aliases=["Acme Agent"]), "Acme", "example.com", PAGES)
    assert profile.aliases == ["Acme", "Acme Agent"]


# --- the three layers stay separate ------------------------------------------
def test_onboarding_never_sets_intent_and_says_so():
    """Crawling establishes what they CLAIM. What they want to be known for is the customer's."""
    profile, attrs, _, _ = onboarded(payload(), "Acme", "example.com", PAGES)
    assert all(a.intended_weight is None for a in attrs)
    assert all(not a.intended for a in attrs)
    assert any("not derivable" in w for w in profile.warnings)
    assert [e.source_type for e in profile.evidence] == ["page_fetch", "page_fetch"]


# --- malformed model output --------------------------------------------------
@pytest.mark.parametrize("raw,error", [("I could not find anything useful.", "no JSON object"),
                                       ('{"name": "Acme"}', "no attributes list")])
def test_malformed_output_raises(raw, error):
    with pytest.raises(ValueError, match=error):
        parse(raw)


def test_no_pages_is_refused():
    with pytest.raises(ValueError, match="at least one fetched page"):
        onboarded(payload(), "Acme", "example.com", [])


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


def test_own_products_count_as_the_brand_and_are_never_its_rivals():
    # Amgen on gpt-6-luna, 22 Sep 2026: an answer's table row "**Tezepelumab** (Tezspire)" was
    # scored "Amgen absent", and judged again it listed Tezspire as Amgen's rival. Only "Amgen" and
    # "Amgen Inc." counted as naming it.
    from agents.evaluation import evaluate
    from agents.onboarding_model import build_profile
    from schemas import Answer, Probe
    profile = build_profile({"name": "Amgen", "aliases": ["Amgen Inc."], "products": ["Tezspire", "Repatha", "Humira"]},
                            [("https://www.amgen.com/", "Amgen makes Tezspire and Repatha.")], "amgen.com")
    assert {"Amgen", "Amgen Inc.", "Tezspire", "Repatha"} <= set(profile.names())
    assert "Humira" not in profile.names()  # not on its pages: a product named from memory credits nobody
    text = "| **Severe asthma** | **Tezepelumab** (Tezspire) | Add-on maintenance treatment. Humira is AbbVie's."
    probe = Probe(id="cat-b1", topic_id="cat-1", kind="blind", phase="baseline", purpose="p",
                  text="What biologic medicines are available for treating serious illnesses?")
    labels = dict(mentioned=True, recommended=False, negative_mention=False, on_topic=True,
                  competitor_recommendations=["Tezspire", "AbbVie"], evidence_quotes=["Tezepelumab (Tezspire)"],
                  outdated_claim_quote=None, attributes=[])
    answer = Answer(probe_id="cat-b1", text=text, provenance="live_api", provider="openai", model="m",
                    search_executed=True, evaluator_labels=labels)
    e = evaluate(probe, answer, profile)
    assert e.valid and e.mentioned and e.competitor_recommendations == ["AbbVie"]


def test_no_question_assumes_the_company_sells_software():
    # A drugmaker got "Which software supports oncology treatment planning?", "the leading tools for
    # biologic medicines" (answered with no tool at all) and "…to a 200-person company?".
    from agents import ana, onboarding
    from agents.onboarding_model import QUESTIONS_PROMPT
    from schemas import CompanyProfile
    assert "software" not in QUESTIONS_PROMPT and "which companies" in QUESTIONS_PROMPT.lower()
    profile = CompanyProfile(name="Amgen", domain="amgen.com")
    assert ana.control_probe(profile, "biologic medicines").text == "Which companies lead in biologic medicines?"
    shaped = ("200-person", "day to day", "never used", "team")
    assert not [t for t in onboarding.NAMED_TEMPLATES if any(s in t for s in shaped)]


# --- malformed JSON from the model -------------------------------------------
def test_malformed_json_is_asked_again_once():
    """Live extraction sometimes returns broken JSON; one retry, metered like any call."""
    replies = iter(['{"name": "Acme", "attributes": [,]}', payload()])
    calls = []
    _, attrs, _, _ = onboard("Acme", "example.com", PAGES, model="test",
                             transport=lambda *args: calls.append(args) or next(replies))
    assert len(calls) == 2 and attrs[0].id == "enterprise_ready"


def test_malformed_json_twice_says_so_plainly():
    with pytest.raises(ValueError, match="could not read twice"):
        onboarded('{"attributes": [,]}', "Acme", "example.com", PAGES)
