"""Buyer questions grounded in real demand (demand.py). No network and no key: the autocomplete
answers are recorded from Google's suggestqueries endpoint, and embeddings are a stub."""
import json
from pathlib import Path

import access
import demand
from agents import ana
from providers import fixture, live

F = fixture.FixtureProvider("A")
CAT = "project management software"
HERE = Path(__file__).resolve().parent.parent / "fixtures" / "demand"
AUTOCOMPLETE = json.loads((HERE / "autocomplete_project_management_software.json").read_text())
GROUPS = ("construction", "small", "free", "choose", "excel")


def recorded(url, calls=None):
    if calls is not None:
        calls.append(url)
    seed = demand.urllib.parse.unquote(url[len(demand.AUTOCOMPLETE):])
    return AUTOCOMPLETE[seed]


def embed(texts):
    """One direction per theme a test can predict; anything else is its own direction."""
    def vec(i, t):
        hit = next((k for k, g in enumerate(GROUPS) if g in t.lower()), None)
        v = [0.0] * (len(GROUPS) + len(texts))
        v[hit if hit is not None else len(GROUPS) + i] = 1.0
        return v
    return [vec(i, t) for i, t in enumerate(texts)]


def test_harvest_reads_autocomplete_and_caches_per_category(monkeypatch):
    calls = []
    monkeypatch.setattr(demand, "_fetch_json", lambda u: recorded(u, calls))
    phrases, notes = demand.harvest(CAT)
    assert {p["source"] for p in phrases} == {"autocomplete"} and notes == []
    assert len(calls) == len(demand.SEEDS)
    demand.harvest(CAT)
    assert len(calls) == len(demand.SEEDS)                  # second read comes from the disk cache


def test_clean_keeps_intent_on_the_category_and_drops_the_brand_and_the_vendor(monkeypatch):
    monkeypatch.setattr(demand, "_fetch_json", recorded)
    raw, _ = demand.harvest(CAT)
    raw += [dict(text="notion vs project management software", source="autocomplete", rank=0),
            dict(text="does your platform replace project management software?", source="autocomplete", rank=9)]
    kept = [p["text"] for p in demand.clean(raw, CAT, F.profile)]
    assert "best project management software for small teams" in kept
    assert CAT not in kept                                   # the bare category is not a question
    assert "project management software tools" not in kept   # no buying intent
    assert "project management vs software engineering" not in kept   # off the category
    assert not any("notion" in k.lower() or "your platform" in k for k in kept)
    assert len(kept) == len({k.lower().rstrip("?") for k in kept})


def test_cluster_groups_by_cosine_and_leaves_the_unlike_alone():
    groups, _ = demand.cluster([[1, 0], [0.99, 0.1], [0, 1]], threshold=0.9)
    assert sorted(map(sorted, groups)) == [[0, 1], [2]]


def test_ground_asks_the_biggest_groups_exactly_as_people_typed_them(monkeypatch):
    monkeypatch.setattr(demand, "_fetch_json", recorded)
    found, note = demand.ground(CAT, F.profile, 3, embed=embed)
    assert len(found) == 3
    sizes = [len(d.phrasings) for _, d in found]
    assert sizes == sorted(sizes, reverse=True) and sizes[0] > 1
    for q, d in found:
        assert q == d.phrase and d.phrase in [p.text for p in d.phrasings]
        assert not ana.brand_leaks(q, F.profile)
    assert "Google autocomplete" in note


def test_ground_without_real_searches_falls_back_and_says_why():
    found, note = demand.ground(CAT, F.profile, 6, embed=embed)          # conftest refuses the network
    assert found == [] and "written by AI" in note and "could not be reached" in note


def test_live_plan_asks_real_searches_first_and_marks_them(monkeypatch):
    aim_qs = [f"Which workspace tool suits a team of {n}?" for n in (5, 10, 20, 50, 100, 200)]
    profile = F.profile.model_copy(update=dict(core_category=CAT, category_questions=aim_qs))
    monkeypatch.setattr(demand, "_fetch_json", recorded)
    ground = lambda c, p, n: demand.ground(c, p, 2, embed=embed)
    # sharing off: this is about grounding, and the second plan below must not reuse the first's pool
    prov = live.LiveProvider(F.attributes(), F.named_probes(), profile=profile, model="m", demand=ground,
                             share=False)
    _, probes = prov.plan(profile, None)
    aim = [p for p in probes if p.topic_id.startswith("cat-")]
    assert [p.demand is not None for p in aim] == [True, True, *[False] * len(aim_qs)]
    assert [p.text for p in aim[2:]] == aim_qs               # the written ones fill the rest of the budget
    assert prov.demand_notes and CAT in prov.demand_notes[0]
    plain = live.LiveProvider(F.attributes(), F.named_probes(), profile=profile, model="m", share=False)
    _, probes = plain.plan(profile, None)
    assert not any(p.demand for p in probes) and not plain.demand_notes


def test_a_probe_without_demand_hashes_as_before():
    p = F.named_probes()[0]
    assert "demand" not in json.dumps(p.model_dump(exclude_none=True))
    assert ana.baseline_hash([p]) == ana.baseline_hash([p.model_copy(update=dict(demand=None))])


def test_embeddings_are_priced_from_their_input_tokens():
    usd, f = access.cost(demand.EMBED_MODEL, {"usage": {"prompt_tokens": 1_000_000, "total_tokens": 1_000_000}})
    assert round(usd, 4) == 0.02 and f["estimated"] == 0
