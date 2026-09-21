"""HTTP API over the existing Python engine. The engine is not modified — only observed.

Streamlit could only render progress when a graph NODE returned, so `execute_or_replay` froze the
page for the whole batch. Here the graph runs on a worker thread and pushes an event per ANSWER as
well as per node, so the browser sees real progress while a long batch is still running.
"""
import json
import queue
import re
import threading
import traceback
import uuid
from typing import Iterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import fetching
import graph
from agents.ana import brand_leaks
from agents.evaluator_model import ModelEvaluator
from agents.onboarding import NAMED_TEMPLATES, named_probes_for
from agents.onboarding_model import MIN_CLAIMS, OnboardingAgent, buyer_questions_for
from drift import MIN_NAMED
from config import load_env, redacted_status
from providers import fixture, live
from providers.company import CompanyProvider
from reports import RUNS, list_companies, load_company, load_run, save_company, save_run
from schemas import Attribute, Company

_LOADED = load_env()
print(f"[config] {redacted_status(_LOADED)}")  # names only; a key value is never printed

app = FastAPI(title="Positioning Drift API")

# Any loopback port, because Vite silently moves to 5174/5175 when 5173 is taken and a pinned
# origin then fails as an opaque "TypeError: Failed to fetch" in the browser.
# DEV ONLY: tighten this to the real origin before deploying anywhere.
LOOPBACK_ORIGIN = r"http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"
app.add_middleware(CORSMiddleware, allow_origin_regex=LOOPBACK_ORIGIN,
                   allow_methods=["*"], allow_headers=["*"])


def sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


@app.get("/api/scenarios")
def scenarios():
    out = []
    for sid in sorted(fixture.SCENARIOS):
        p = fixture.FixtureProvider(sid)
        attrs = p.attributes()
        out.append(dict(
            id=sid, title=p.title, notice=p.data.get("notice"),
            company=p.data["profile"]["name"],
            named_probes=len(p.named_probes()),
            intended=[dict(id=a.id, label=a.label, description=a.description,
                           weight=a.intended_weight, claim_pages=a.claim_pages,
                           claim_pages_total=a.claim_pages_total)
                      for a in attrs if a.intended]))
    return out


NO_REPLAY = ("{name} was onboarded from its own website, so there are no authored answers to "
             "replay — demo mode can only replay the two bundled scenarios. Measuring a real "
             f"company means asking a real model, which needs {live.KEY_ENV}.")


def build_provider(mode: str, scenario: Optional[str] = None, company_id: Optional[str] = None):
    """-> (provider, profile, expected_answers, run_mode). Either a bundled scenario or a saved company.

    Live mode needs a key; it never falls back silently to fixtures, because a fixture result
    labelled live would be a fabricated measurement.
    """
    if company_id:
        try:
            base = CompanyProvider(load_company(company_id))
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, f"No onboarded company {company_id!r}")
        if mode != "live":
            raise HTTPException(400, NO_REPLAY.format(name=base.profile.name))
    else:
        base = fixture.FixtureProvider(scenario)
        if mode != "live":
            return (base, base.profile,
                    len(base.named_probes()) + graph.MAX_BASELINE + graph.MAX_FOLLOWUP, "demo_replay")
    profile = base.profile
    if not live.available():
        raise HTTPException(400, f"Live mode needs {live.KEY_ENV}. {live.status()}")
    if not base.attributes():
        # Refused before preflight, which is itself a billed call.
        raise HTTPException(400, f"Nothing on {profile.name}'s site survived quote validation, so "
                                 "there is nothing to measure yet. Add a claim you want to be known "
                                 "for, or onboard again from a page that states its positioning.")
    try:
        live.preflight()   # one trivial call: an unusable model fails once, not 20 times
    except live.PreflightFailed as e:   # its message is safe to show: no provider body, no key
        raise HTTPException(400, str(e))
    prov = live.LiveProvider(base.attributes(), base.named_probes(), profile=profile,
                             evaluator=ModelEvaluator())
    # a live run is both axes now: count the blind probes its own plan will produce, or the progress
    # bar reads "20/8"
    _, blind = prov.plan(profile)
    # The round-two comparison question is not counted: it is appended only when a baseline answer
    # names a competitor, so reserving a slot for it strands a finished run at "7/8". The overrun in
    # the other direction is held by the clamp in the progress bar.
    return prov, profile, len(blind) + len(base.named_probes()), "live_api"


def run_events(scenario: str, mode: str = "demo", company_id: Optional[str] = None) -> Iterator[str]:
    """Executes one run on a worker thread, yielding SSE as the graph progresses."""
    if not company_id and scenario not in fixture.SCENARIOS:
        yield sse("error", {"message": f"unknown scenario {scenario!r}"})
        return
    try:
        prov, profile, expected, run_mode = build_provider(mode, scenario, company_id)
    except HTTPException as e:
        yield sse("error", {"message": str(e.detail)})
        return
    except Exception as e:                           # setup failures surface too, minus the detail
        traceback.print_exc()                        # the detail stays on the server console
        yield sse("error", {"message": f"Setup failed before the run started: {type(e).__name__}"})
        return
    q: queue.Queue = queue.Queue()
    state = {"done": 0}
    # id -> label, so the live feed can say "Buyer question 2 — Team knowledge bases" instead of
    # "kb-2". Filled from plan_baseline's node event, which lands before any answer is produced.
    topic_labels: dict[str, str] = {}

    inner = prov.answer

    def counting_answer(probe):                     # per-answer progress: the whole point
        a = inner(probe)
        state["done"] += 1
        q.put(("answer", dict(probe_id=probe.id, kind=probe.kind, phase=probe.phase,
                              topic_label=topic_labels.get(probe.topic_id),
                              text=probe.text, status=a.status,
                              done=state["done"], expected=expected)))
        return a

    prov.answer = counting_answer

    def work():
        try:
            run = graph.new_run(profile, prov, mode=run_mode)
            for node, run in graph.stream(run, prov):
                topic_labels.update({t.id: t.label for t in run.topics})
                stage, agent = graph.STAGES[node]
                q.put(("node", dict(node=node, stage=stage, agent=agent,
                                    log=run.log[-1] if run.log else "")))
            save_run(run)
            q.put(("done", dict(run_id=run.id, run=json.loads(run.model_dump_json()))))
        except Exception as e:                       # surfaced, never swallowed
            q.put(("error", dict(message=f"{type(e).__name__}: {e}")))
        finally:
            q.put((None, None))

    threading.Thread(target=work, daemon=True).start()
    while True:
        kind, payload = q.get()
        if kind is None:
            return
        yield sse(kind, payload)


@app.get("/api/stream")
def stream(scenario: str = "A", mode: str = "demo", company: Optional[str] = None):
    return StreamingResponse(run_events(scenario, mode, company), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs")
def list_all():
    """Run history: newest first, with enough detail to pick one for comparison."""
    out = []
    for p in sorted(RUNS.glob("*.json")):
        try:
            r = load_run(p.stem)
        except Exception:
            continue
        d = r.drift
        out.append(dict(id=r.id, created_at=r.created_at, scenario=r.scenario, status=r.status,
                        company=r.profile.name,
                        alignment=d.alignment if d else None,
                        visibility=d.visibility if d else None,
                        landed=len(d.landed) if d else 0,
                        lost=len(d.lost_claims) if d else 0,
                        contested=len(d.contested) if d else 0,
                        unstated=len(d.unstated_intent) if d else 0,
                        imposed=len(d.imposed) if d else 0,
                        unprioritised=len(d.unprioritised) if d else 0))
    return sorted(out, key=lambda r: r["created_at"], reverse=True)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    try:
        return json.loads(load_run(run_id).model_dump_json())
    except FileNotFoundError:
        raise HTTPException(404, f"run {run_id} not found")


CRAWL_PAGES = 6


def vet_questions(profile, attributes: list[Attribute]) -> list[str]:
    """Run both leak validators BEFORE the company is persisted, and say what they cost.

    Every question here is model-generated text that gets saved verbatim, so a collision saved
    unchecked makes the company permanently unmeasurable: the same validators run again inside
    `validate_and_freeze` and abort the run. That is true of all three of its checks — a leaked
    brand name, a leaked attribute, and a question repeated across two attributes, which is ordinary
    output when one response writes three questions each for eight claims. A contaminated question
    is dropped, never rewritten — we refuse to ask it, we do not quietly repair it.
    """
    warnings, asked = [], set()
    for a in attributes:
        kept = []
        for q in a.buyer_questions:
            if leaks := brand_leaks(q, profile):
                warnings.append(f"“{a.label}”: a buyer question named you ({', '.join(leaks)}) and was "
                                "dropped — a question that names you cannot test whether a buyer finds you.")
            elif q.strip().lower() in asked:
                warnings.append(f"“{a.label}”: a buyer question repeated one already asked for an "
                                "earlier claim and was dropped — one question cannot measure two claims.")
            else:
                asked.add(q.strip().lower())
                kept.append(q)
        a.buyer_questions = kept
        if not kept:
            warnings.append(f"“{a.label}”: no buyer question survived, so this claim is measured on "
                            "the brand axis only.")
    named = named_probes_for(profile, attributes)
    if lost := len(NAMED_TEMPLATES) - len(named):
        warnings.append(f"{lost} of {len(NAMED_TEMPLATES)} brand questions dropped: their ordinary wording "
                        "collides with a claim being measured, and an answer echoing the question back "
                        "would measure the question, not the model.")
    if len(named) < MIN_NAMED:
        warnings.append(f"Only {len(named)} brand question(s) remain; perception needs at least "
                        f"{MIN_NAMED}, so no alignment score will be produced.")
    return warnings


def company_payload(c: Company) -> dict:
    p = c.profile
    return dict(
        id=c.id, created_at=c.created_at,
        profile=dict(name=p.name, domain=p.domain, aliases=p.aliases,
                     customer_types=p.customer_types,
                     one_liner=p.positioning_points[0].text if p.positioning_points else None,
                     warnings=p.warnings),
        pages=c.pages,
        attributes=[dict(id=a.id, label=a.label, description=a.description, aliases=a.aliases,
                         claim_quotes=a.claim_quotes, claim_pages=a.claim_pages,
                         claim_pages_total=a.claim_pages_total,
                         buyer_questions=a.buyer_questions, intended_weight=a.intended_weight,
                         added_by_user=a.added_by_user, note=a.note)
                    for a in c.attributes],
        warnings=c.warnings)


@app.get("/api/onboard")
def onboard(url: str, name: str = ""):
    """Agent 1: crawl a company's own pages, extract the CLAIMED layer, and save the company.

    Returns claimed attributes with descriptions, verbatim quotes and page counts DERIVED from
    those quotes. Intent weights are deliberately absent — what a company wants to be known for is
    the customer's input, arrives only through PATCH, and is not derivable from their own
    marketing copy.
    """
    if not live.available():
        raise HTTPException(400, f"Onboarding needs {live.KEY_ENV} for the extraction model.")
    try:
        pages = fetching.fetch_site(url, max_pages=CRAWL_PAGES)
    except fetching.UnsafeURL as e:
        raise HTTPException(400, f"Refused: {e}")
    except fetching.FetchError as e:
        raise HTTPException(502, f"Could not fetch: {e}")
    domain = fetching.validate(url)[1].removeprefix("www.")
    try:
        profile, attrs, warnings = OnboardingAgent().run(name, domain, pages)
    except ValueError as e:
        raise HTTPException(502, f"Extraction failed: {e}")
    if len(attrs) < MIN_CLAIMS:
        # The company is saved either way — discarding a paid crawl to refuse a thin site is the
        # wrong trade. Withhold confidence in the numbers, not the company.
        warnings.insert(0, f"Only {len(attrs)} claim(s) on {domain} survived quote validation across "
                           f"{len(pages)} page(s), below the {MIN_CLAIMS} this needs. The site states too "
                           "little for a reliable claim percentage — read every page share with care.")
    warnings += vet_questions(profile, attrs)
    company = Company(id=uuid.uuid4().hex[:10], profile=profile, attributes=attrs,
                      pages=[u for u, _ in pages], warnings=warnings)
    save_company(company)
    return company_payload(company)


ADDED_MIN_WEIGHT = 0.1


class AddedAttribute(BaseModel):
    """Something the customer wants to be known for that their own copy never states.

    Unlike an extracted claim, this one is intended by construction: typing it into "add something
    your copy never states" IS the expression of intent, so its weight starts at the midpoint and
    can never reach the zero that would drop it out of the report unseen. Changing your mind is a
    deletion, not a slider position — see `delete_attribute`.
    """
    label: str = Field(min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, max_length=400)
    intended_weight: float = Field(default=0.5, ge=ADDED_MIN_WEIGHT, le=1)


class CompanyPatch(BaseModel):
    weights: dict[str, float] = {}
    added: list[AddedAttribute] = []


def added_buyer_questions(company: Company, raw: AddedAttribute) -> tuple[list[str], list[str]]:
    """-> (questions, warnings). An added claim needs the placebo test most of all.

    It is a claim their own copy never makes, so "would a buyer looking for this find them?" is the
    whole question. There is no page text to draw the questions from, so the onboarding model writes
    them — and they go through `brand_leaks` exactly like the extracted ones. With no key the claim
    is still added, measured on the brand axis alone, and the omission is stated.
    """
    if not live.available():
        return [], [f"“{raw.label}”: no buyer questions were generated ({live.KEY_ENV} is not set), "
                    "so this claim is measured on the brand axis only."]
    asked = {q.strip().lower() for a in company.attributes for q in a.buyer_questions}
    try:
        generated = buyer_questions_for(raw.label, raw.description)
    except Exception as e:
        traceback.print_exc()
        return [], [f"“{raw.label}”: buyer-question generation failed ({type(e).__name__}), so this "
                    "claim is measured on the brand axis only."]
    kept = []
    for q in generated:
        if brand_leaks(q, company.profile) or q.strip().lower() in asked:
            continue
        asked.add(q.strip().lower())
        kept.append(q)
    warnings = []
    if dropped := len(generated) - len(kept):
        warnings.append(f"“{raw.label}”: {dropped} generated buyer question(s) named you or repeated "
                        "one already asked, and were dropped.")
    if not kept:
        warnings.append(f"“{raw.label}”: no buyer question survived, so this claim is measured on "
                        "the brand axis only.")
    return kept, warnings


@app.get("/api/companies")
def companies():
    out = []
    for path in list_companies():
        try:
            c = load_company(path.stem)
        except Exception:
            continue
        out.append(dict(id=c.id, name=c.profile.name, domain=c.profile.domain,
                        created_at=c.created_at, pages=len(c.pages),
                        attributes=len(c.attributes),
                        intended=sum(1 for a in c.attributes if a.intended)))
    return out


def _company(company_id: str) -> Company:
    try:
        return load_company(company_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, f"No onboarded company {company_id!r}")


@app.get("/api/companies/{company_id}")
def get_company(company_id: str):
    return company_payload(_company(company_id))


@app.patch("/api/companies/{company_id}")
def patch_company(company_id: str, patch: CompanyPatch):
    """The customer's own input: how much each claim matters, plus claims their copy never makes.

    For a claim extracted from their own pages, intent is never derived and never defaulted: a
    slider left at its resting zero leaves the attribute unintended, so an untouched form cannot
    invent an aspiration the customer never expressed. An ADDED claim is the opposite case — nothing
    but the customer's own intent puts it here — so it arrives already weighted.
    """
    c = _company(company_id)
    by_id = {a.id: a for a in c.attributes}
    for aid, weight in patch.weights.items():
        if aid not in by_id:
            raise HTTPException(400, f"unknown attribute {aid!r}")
        if not 0 <= weight <= 1:
            raise HTTPException(400, f"weight for {aid!r} must be between 0 and 1")
        if by_id[aid].added_by_user and weight < ADDED_MIN_WEIGHT:
            raise HTTPException(400, f"{by_id[aid].label!r} is a claim you added, so it is intended by "
                                     f"construction and cannot drop below {ADDED_MIN_WEIGHT}. Delete it "
                                     "instead if you no longer want it measured.")
        by_id[aid].intended_weight = round(weight, 2) or None
    for raw in patch.added:
        aid = base = re.sub(r"[^a-z0-9]+", "_", raw.label.lower()).strip("_") or "added"
        for n in range(2, 99):
            if aid not in by_id:
                break
            aid = f"{base}_{n}"
        questions, warns = added_buyer_questions(c, raw)
        c.warnings += warns
        attr = Attribute(id=aid, label=raw.label.strip(), description=raw.description,
                         intended_weight=round(raw.intended_weight, 2), added_by_user=True,
                         # zero pages state it — that is the finding, not missing data
                         claim_pages=0, claim_pages_total=len(c.pages),
                         buyer_questions=questions,
                         note="Added by you, so it is marked as intended — adding it is the intent. "
                              "Your own pages never state it, so AI has nothing to repeat.")
        by_id[aid] = attr
        c.attributes.append(attr)
    save_company(c)
    return company_payload(c)


@app.delete("/api/companies/{company_id}/attributes/{attribute_id}")
def delete_attribute(company_id: str, attribute_id: str):
    """Remove a claim the customer typed. Only theirs: an extracted claim is evidence, not an opinion."""
    c = _company(company_id)
    attr = next((a for a in c.attributes if a.id == attribute_id), None)
    if attr is None:
        raise HTTPException(404, f"unknown attribute {attribute_id!r}")
    if not attr.added_by_user:
        raise HTTPException(400, f"{attr.label!r} was extracted from the company's own pages, not added "
                                 "by you. Leave its intent slider at zero to exclude it from scoring.")
    c.attributes = [a for a in c.attributes if a.id != attribute_id]
    save_company(c)
    return company_payload(c)


@app.get("/api/health")
def health():
    """Reports whether live mode is usable — never the key itself."""
    from agents import evaluator_model
    measured = live.model_name() if live.available() else None
    evaluator = evaluator_model.model_name() if live.available() else None
    return {"ok": True, "scenarios": sorted(fixture.SCENARIOS),
            "live_available": live.available(), "live_status": live.status(),
            "measured_model": measured, "evaluator_model": evaluator,
            # a model grading its own output has a self-preference bias worth surfacing
            "same_model_warning": bool(measured and evaluator and measured == evaluator)}
