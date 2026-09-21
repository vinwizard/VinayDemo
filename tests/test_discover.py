"""Emergent attributes: discovered from the answers, and held to the same verbatim bar as the rest."""
import json

import graph
from agents import evaluation
from agents.evaluator_model import ModelEvaluator, build_discovery_prompt
from providers import fixture, live
from schemas import Answer, Attribute, AttributeObservation, CompanyProfile, Probe

PROFILE = CompanyProfile(name="Notion", domain="notion.com")
TEXT = ("**Notion** is powerful but Clunky on mobile. ([blog.example](https://blog.example/n))\n\n"
        "Teams also find it slow to load big pages.")
ANSWERS = {f"np-{i}": Answer(probe_id=f"np-{i}", text=TEXT, provenance="synthetic") for i in (1, 2, 3)}


def proposal(label, *quotes, polarity="negative"):
    return dict(label=label, description=f"{label}.",
                evidence=[dict(answer=pid, quote=q, polarity=polarity) for pid, q in quotes])


def discover(*proposals, attributes=(), observations=None):
    return evaluation.discover_attributes(list(proposals), ANSWERS, list(attributes),
                                          observations or {}, PROFILE)


def test_a_characterisation_two_answers_make_becomes_an_emergent_attribute():
    new, obs, dropped = discover(proposal("Clunky on mobile", ("np-1", "notion is powerful but clunky on mobile"),
                                          ("np-2", "Clunky on mobile")))
    assert [a.label for a in new] == ["Clunky on mobile"] and new[0].discovered
    assert not new[0].intended and not new[0].claimed
    assert sorted(obs) == ["np-1", "np-2"] and not dropped
    assert all(o.attribute_id == new[0].id and o.polarity == "negative" for o in obs["np-1"] + obs["np-2"])


def test_a_single_mention_is_noise_and_is_dropped():
    new, obs, dropped = discover(proposal("Clunky on mobile", ("np-1", "Clunky on mobile"),
                                          ("np-1", "powerful but Clunky")))
    assert not new and not obs
    assert "1 eligible answer(s), needs 2" in dropped[0]


def test_an_invented_or_cited_quote_does_not_count_toward_the_floor():
    new, _, dropped = discover(proposal("Clunky on mobile", ("np-1", "Clunky on mobile"),
                                        ("np-2", "clunky on phones"),        # not in the answer
                                        ("np-3", "blog.example"),            # only in a citation
                                        ("np-9", "Clunky on mobile")))       # not an eligible answer
    assert not new
    assert "not verbatim" in dropped[0] and "citation" in dropped[0] and "'np-9'" in dropped[0]


def test_a_rephrasing_of_a_measured_attribute_is_not_a_new_one():
    fast = Attribute(id="fast", label="Fast by design")
    for label in ("Fast", "Fast by design", "Fast and snappy"):
        new, _, dropped = discover(proposal(label, ("np-1", "slow to load"), ("np-2", "slow to load")),
                                   attributes=[fast])
        assert not new and "same attribute" in dropped[0], label
    new, _, _ = discover(proposal("Slow page loads", ("np-1", "slow to load"), ("np-2", "slow to load")),
                         attributes=[Attribute(id="fast", label="Fast", aliases=["page loads instantly"])])
    assert not new  # two of its three words already name a measured attribute: unsure, so no
    # sharing only an audience word is not sameness: this is a different claim about those teams
    new, _, _ = discover(proposal("Expensive for large teams", ("np-1", "Clunky"), ("np-2", "Clunky")),
                         attributes=[Attribute(id="teams", label="Built for teams")])
    assert [a.label for a in new] == ["Expensive for large teams"]


def test_the_same_quote_already_counted_for_an_attribute_is_not_counted_again():
    speed = Attribute(id="speed", label="Performance")
    already = {"np-1": [AttributeObservation(attribute_id="speed", quote="slow to load big pages")]}
    new, _, dropped = discover(proposal("Sluggish", ("np-1", "slow to load"), ("np-2", "slow to load")),
                               attributes=[speed], observations=already)
    assert not new and "np-1 quotes the same words for 'Performance'" in dropped[0]


def test_two_proposals_for_one_trait_keep_only_the_better_supported():
    new, _, dropped = discover(
        proposal("Clunky", ("np-1", "Clunky on mobile"), ("np-2", "Clunky on mobile")),
        proposal("Clunky mobile app", *[(p, "Clunky on mobile") for p in ANSWERS]))
    assert [a.label for a in new] == ["Clunky mobile app"]
    assert "same attribute" in dropped[0] and "'Clunky'" in dropped[0]


def test_malformed_proposals_are_dropped_not_fatal():
    new, _, dropped = evaluation.discover_attributes([{"evidence": []}, "junk", {"label": "  "}],
                                                     ANSWERS, [], {}, PROFILE)
    assert not new and len(dropped) == 3
    assert evaluation.discover_attributes(None, ANSWERS, [], {}, PROFILE) == ([], {}, [])


# --- fixtures: discovery must not duplicate the hand-written unclaimed attributes -------------
class Discovering(fixture.FixtureProvider):
    """A fixture replay that also 'discovers' — paraphrases of the attributes the authors wrote."""
    def __init__(self, scenario, proposals):
        super().__init__(scenario)
        self.proposals = proposals

    def discover(self, attributes, answers):
        return self.proposals


def test_discovery_on_the_fixtures_duplicates_nothing_and_moves_no_number():
    plain = {s: graph.execute(graph.new_run(fixture.bundled_profile(s), p := fixture.FixtureProvider(s)), p)
             for s in ("A", "B")}
    proposals = {
        "A": [proposal("Hard to learn at first", ("np-2", "steep learning curve"), ("np-4", "steep learning curve")),
              proposal("Beautiful templates", ("np-3", "templates"), ("np-4", "templates"))],
        "B": [proposal("Costly per seat", ("np-4", "pricing adds up once every seat is paid"),
                       ("np-5", "per-seat costs become significant")),
              proposal("Expensive for big teams", ("np-6", "costly for large teams"),
                       ("np-5", "per-seat costs become significant"))]}
    for s, expected in (("A", 21.4), ("B", 30.7)):
        prov = Discovering(s, proposals[s])
        run = graph.execute(graph.new_run(fixture.bundled_profile(s), prov), prov)
        assert run.drift.alignment == plain[s].drift.alignment == expected
        assert not any(a.discovered for a in run.attributes), s
        assert [x.model_dump() for x in run.attribute_scores] == [x.model_dump() for x in plain[s].attribute_scores]
        notes = [l for l in run.drift.limitations if l.startswith("Discovery")]
        assert len(notes) == 2 and all("same attribute" in n or "needs 2" in n for n in notes), notes


# --- live: an emergent attribute lands as imposed, and says where it came from -----------------
class Evaluator:
    model = "test-evaluator"

    def __init__(self, proposals):
        self.proposals = proposals

    def label(self, probe, answer, attributes, profile):
        return dict(mentioned=True, recommended=False, negative_mention=False,
                    competitor_recommendations=[], evidence_quotes=["is powerful"], on_topic=True,
                    attributes=[])

    def discover(self, profile, attributes, answers):
        self.seen = [p.id for p, _ in answers]
        return self.proposals


def live_run(proposals):
    message = {"type": "message", "content": [{"type": "output_text", "text": TEXT, "annotations": []}]}
    f = fixture.FixtureProvider("A")
    ev = Evaluator(proposals)
    prov = live.LiveProvider(f.attributes(), f.named_probes(), profile=f.profile, model="m",
                             transport=lambda *_: {"output": [{"type": "web_search_call"}, message]},
                             evaluator=ev)
    return graph.execute(graph.new_run(f.profile, prov, mode="live_api"), prov), ev


def test_a_discovered_attribute_is_imposed_and_marked_discovered():
    base, _ = live_run([])
    run, ev = live_run([proposal("Clunky on mobile", ("np-1", "Clunky on mobile"), ("np-5", "clunky on mobile"))])
    assert ev.seen == [p.id for p in fixture.FixtureProvider("A").named_probes()]  # one call, all answers
    s = next(x for x in run.attribute_scores if x.label == "Clunky on mobile")
    assert s.discovered and s.zone == "imposed" and s.owner == "imposed_identity"
    assert s.echoes == 2 and s.negative_echoes == 2 and s.probe_ids == ["np-1", "np-5"]
    assert "Discovered from the answers" in s.limitations[0]
    assert run.drift.imposed == ["Clunky on mobile"]
    assert run.drift.alignment == base.drift.alignment  # never intended, so never in alignment
    assert any("1 kept (Clunky on mobile)" in l for l in run.log)


def test_a_failed_discovery_call_is_stated_and_the_run_still_completes():
    run, _ = live_run(None)
    assert run.status == "complete" and not any(a.discovered for a in run.attributes)
    assert any("discovery call failed" in l for l in run.drift.limitations)


# --- the model call ---------------------------------------------------------------------------
def pairs():
    probes = [Probe(id=pid, topic_id="perception", text=f"What is Notion? ({pid})", kind="named",
                    phase="baseline", purpose="p") for pid in ANSWERS]
    return [(p, ANSWERS[p.id]) for p in probes]


def test_one_prompt_carries_every_answer_and_every_measured_attribute_but_no_citation():
    attrs = [Attribute(id="fast", label="Fast by design", aliases=["snappy"])]
    prompt = build_discovery_prompt(PROFILE, attrs, pairs())
    assert all(f"Answer {pid} — question: What is Notion? ({pid})" in prompt for pid in ANSWERS)
    assert "Fast by design" in prompt and "snappy" in prompt
    assert "blog.example" not in prompt and "**" not in prompt.split("The answers")[1].split("Return")[0]


def test_discover_returns_the_raw_proposals_or_none_on_a_bad_payload():
    calls = []
    ok = ModelEvaluator(model="m", transport=lambda p, m, t: calls.append(p) or
                        "```json\n" + json.dumps({"proposals": [proposal("Clunky", ("np-1", "Clunky"))]}) + "\n```")
    assert ok.discover(PROFILE, [], pairs())[0]["label"] == "Clunky" and len(calls) == ok.calls == 1
    bad = ModelEvaluator(model="m", transport=lambda *_: '{"nope": 1}')
    assert bad.discover(PROFILE, [], pairs()) is None and bad.failures
