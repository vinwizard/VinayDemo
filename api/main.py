"""HTTP API over the existing Python engine. The engine is not modified — only observed.

Streamlit could only render progress when a graph NODE returned, so `execute_or_replay` froze the
page for the whole batch. Here the graph runs on a worker thread and pushes an event per ANSWER as
well as per node, so the browser sees real progress while a long batch is still running.
"""
import json
import os
import queue
import re
import threading
import traceback
import uuid
from pathlib import Path
from typing import Iterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import fetching
import graph
from insights import insights
from agents.ana import brand_leaks, discovered_competitors, vendor_address
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


def run_payload(run) -> dict:
    """The run as the browser reads it, plus the panels derived from its saved answers."""
    return {**json.loads(run.model_dump_json()), "insights": insights(run)}

# Any loopback port, because Vite silently moves to 5174/5175 when 5173 is taken and a pinned
# origin then fails as an opaque "TypeError: Failed to fetch" in the browser.
# DEV ONLY: tighten this to the real origin before deploying anywhere.
LOOPBACK_ORIGIN = r"http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"
app.add_middleware(CORSMiddleware, allow_origin_regex=LOOPBACK_ORIGIN,
                   allow_methods=["*"], allow_headers=["*"])


def sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


NO_REPLAY = ("{name} was onboarded from its own website, so there are no authored answers to "
             "replay — demo mode can only replay the two bundled scenarios. Measuring a real "
             f"company means asking a real model, which needs {live.KEY_ENV}.")


# The preloaded Notion company: a real onboarding of notion.com, committed so a fresh clone has it.
SEED_COMPANY = "5eed0001"
# Emergency fallback for a demo with no network: measuring the seed company replays the bundled
# Notion sample instead. Deliberately not reachable from the UI — only from the server's environment
# — and the run it produces is saved as a sample run and says so on every surface that shows it.
OFFLINE_ENV = "VISEXP_OFFLINE_REPLAY"
OFFLINE_FIXED = "offline replay: the bundled sample's claims and weights are fixed"


# The hosted demo (render.yaml): anyone with the link can open it, so nothing may reach a model or
# spend the owner's key. Implies the offline replay, and refuses every path that would call a model
# or change a saved company — even when a key happens to be configured.
PUBLIC_ENV = "VISEXP_PUBLIC_DEMO"
PUBLIC_REFUSED = ("This is the public demo: it replays the saved sample only, so {what} is switched "
                  "off here. Run it locally with your own key to measure a real company.")


def public_demo() -> bool:
    return bool(os.environ.get(PUBLIC_ENV))


def refuse_in_public(what: str) -> None:
    if public_demo():
        raise HTTPException(403, PUBLIC_REFUSED.format(what=what))


def offline_seed(company_id: str) -> bool:
    return company_id == SEED_COMPANY and bool(os.environ.get(OFFLINE_ENV) or public_demo())


def seed_public_runs() -> None:
    """A fresh public deploy has no saved runs (they are gitignored), so replay both bundled
    scenarios once — fixtures only, no model — and History and Compare have something to open."""
    if not public_demo() or any(RUNS.glob("*.json")):
        return
    for scenario in sorted(fixture.SCENARIOS):
        prov = fixture.FixtureProvider(scenario)
        save_run(graph.execute(graph.new_run(prov.profile, prov), prov))


def replay_company() -> Company:
    """The seed as the offline run scores it: the bundled sample's claims, never written to disk."""
    provider = fixture.FixtureProvider("A")
    return Company(id=SEED_COMPANY, profile=provider.profile, attributes=provider.attributes(), pages=[],
                   warnings=["Offline replay: these are the bundled sample's authored claims, not a "
                             "read of the site."])


def build_provider(mode: str, scenario: Optional[str] = None, company_id: Optional[str] = None):
    """-> (provider, profile, expected_answers, run_mode). Either a bundled scenario or a saved company.

    Live mode needs a key; it never falls back silently to fixtures, because a fixture result
    labelled live would be a fabricated measurement. The one fallback, OFFLINE_ENV, is opt-in on the
    server and labels its run as replay.
    """
    if company_id and offline_seed(company_id):
        company_id, scenario, mode = None, "A", "demo"
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
    refuse_in_public("measuring with a live model")
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


def progress(run) -> dict:
    """What a run has planned so far, in the counts the staged progress names."""
    planned = {"buyer": 0, "brand": 0, "followup": 0}
    for p in run.probes:
        planned["followup" if p.phase == "followup" else "brand" if p.kind == "named" else "buyer"] += 1
    return dict(mode=run.mode, planned=planned,
                competitors=discovered_competitors(run.topic_evaluations))


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
                              answer=a.text[:320], provenance=a.provenance,
                              grounded=a.search_executed,
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
                                    log=run.log[-1] if run.log else "", **progress(run))))
            if not public_demo():
                save_run(run)
            q.put(("done", dict(run_id=run.id, run=json.loads(run.model_dump_json()))))
        except Exception as e:                       # surfaced, never swallowed; detail stays on the console
            traceback.print_exc()
            q.put(("error", dict(message=f"Run failed after it started: {type(e).__name__}")))
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
                        claim_echo=d.claim_echo if d else None,
                        lens=d.lens if d else None,
                        visibility=d.visibility if d else None,
                        landed=len(d.landed) if d else 0,
                        lost=len(d.lost_claims) if d else 0,
                        contested=len(d.contested) if d else 0,
                        unstated=len(d.unstated_intent) if d else 0,
                        imposed=len(d.imposed) if d else 0,
                        unprioritised=len(d.unprioritised) if d else 0,
                        na_reasons=d.na_reasons if d else
                        {"headline": "This run finished without a drift report."}))
    return sorted(out, key=lambda r: r["created_at"], reverse=True)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    try:
        return run_payload(load_run(run_id))
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, f"run {run_id} not found")


CRAWL_PAGES = 6


def vet_questions(profile, attributes: list[Attribute]) -> list[str]:
    """Run both leak validators BEFORE the company is persisted, and say what they cost.

    Every question here is model-generated text that gets saved verbatim, so a collision saved
    unchecked makes the company permanently unmeasurable: the same validators run again inside
    `validate_and_freeze` and abort the run. That is true of all three of its checks — a leaked
    brand name, a leaked attribute, and a question repeated across two attributes, which is ordinary
    output when one response writes three questions each for eight claims. A contaminated question
    is dropped, never rewritten — we refuse to ask it, we do not quietly repair it. So is a question
    addressed to the vendor ("your platform", "this product"), which measures our question, not the brand.
    """
    warnings, asked = [], set()
    for a in attributes:
        kept = []
        for q in a.buyer_questions:
            if leaks := brand_leaks(q, profile):
                warnings.append(f"“{a.label}”: a buyer question named you ({', '.join(leaks)}) and was "
                                "dropped — a question that names you cannot test whether a buyer finds you.")
            elif vendor := vendor_address(q):
                warnings.append(f"“{a.label}”: a buyer question addressed the vendor ({', '.join(vendor)}) "
                                "and was dropped — a buyer who has never heard of you asks about a need, "
                                "not about “your platform”.")
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
                     logo_url=p.logo_url,
                     warnings=p.warnings),
        pages=c.pages,
        attributes=[dict(id=a.id, label=a.label, description=a.description, aliases=a.aliases,
                         claim_quotes=a.claim_quotes, claim_pages=a.claim_pages,
                         claim_pages_total=a.claim_pages_total,
                         buyer_questions=a.buyer_questions, intended_weight=a.intended_weight,
                         added_by_user=a.added_by_user, note=a.note)
                    for a in c.attributes],
        warnings=c.warnings, replay=offline_seed(c.id))


def onboard_steps(url: str, name: str) -> Iterator[tuple[str, dict]]:
    """Agent 1: crawl a company's own pages, extract the CLAIMED layer, and save the company.

    Yields ("pages", fetched URLs) once the crawl lands, then ("company", payload). The payload has
    claimed attributes with descriptions, verbatim quotes and page counts DERIVED from those
    quotes. Intent weights are deliberately absent — what a company wants to be known for is the
    customer's input, arrives only through PATCH, and is not derivable from their own marketing copy.
    """
    refuse_in_public("onboarding a new company")
    if not live.available():
        raise HTTPException(400, f"Onboarding needs {live.KEY_ENV} for the extraction model.")
    try:
        pages, logo = fetching.fetch_site(url, max_pages=CRAWL_PAGES)
    except fetching.UnsafeURL as e:
        raise HTTPException(400, f"Refused: {e}")
    except fetching.FetchError as e:
        raise HTTPException(502, f"Could not fetch: {e}")
    yield "pages", {"pages": [u for u, _ in pages]}
    domain = fetching.validate(url)[1].removeprefix("www.")
    try:
        profile, attrs, warnings = OnboardingAgent().run(name, domain, pages)
    except ValueError as e:
        raise HTTPException(502, f"Extraction failed: {e}")
    profile.logo_url = logo
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
    yield "company", company_payload(company)


@app.get("/api/onboard")
def onboard(url: str, name: str = ""):
    return dict(onboard_steps(url, name))["company"]


def onboard_events(url: str, name: str) -> Iterator[str]:
    """The same onboarding as SSE, so the browser can show the crawl finish before extraction does."""
    try:
        for kind, payload in onboard_steps(url, name):
            yield sse(kind, payload)
    except HTTPException as e:
        yield sse("error", {"message": str(e.detail)})
    except Exception as e:                           # detail stays on the server console
        traceback.print_exc()
        yield sse("error", {"message": f"Onboarding failed: {type(e).__name__}"})


@app.get("/api/onboard/stream")
def onboard_stream(url: str, name: str = ""):
    return StreamingResponse(onboard_events(url, name), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
        if brand_leaks(q, company.profile) or vendor_address(q) or q.strip().lower() in asked:
            continue
        asked.add(q.strip().lower())
        kept.append(q)
    warnings = []
    if dropped := len(generated) - len(kept):
        warnings.append(f"“{raw.label}”: {dropped} generated buyer question(s) named you, addressed "
                        "the vendor or repeated one already asked, and were dropped.")
    if not kept:
        warnings.append(f"“{raw.label}”: no buyer question survived, so this claim is measured on "
                        "the brand axis only.")
    return kept, warnings


def check_weights(attributes: list[Attribute], weights: dict[str, float]) -> None:
    by_id = {a.id: a for a in attributes}
    for aid, weight in weights.items():
        if aid not in by_id:
            raise HTTPException(400, f"unknown attribute {aid!r}")
        if not 0 <= weight <= 1:
            raise HTTPException(400, f"weight for {aid!r} must be between 0 and 1")
        if by_id[aid].added_by_user and weight < ADDED_MIN_WEIGHT:
            raise HTTPException(400, f"{by_id[aid].label!r} is a claim you added, so it is intended by "
                                     f"construction and cannot drop below {ADDED_MIN_WEIGHT}. Delete it "
                                     "instead if you no longer want it measured.")


class RescoreRequest(BaseModel):
    weights: dict[str, float] = {}


@app.post("/api/runs/{run_id}/rescore")
def rescore_run(run_id: str, req: RescoreRequest):
    """Lens 2 after the fact: intent weights on a finished run, re-scored from its saved answers.

    No provider is built and no model is asked — the weights only change arithmetic. Weights not
    named keep their value, and a weight of 0 unweights a claim; with none left the run reads
    through the claim lens again. The run is saved in place.
    """
    try:
        run = load_run(run_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, f"run {run_id} not found")
    check_weights(run.attributes, req.weights)
    try:
        graph.rescore(run, req.weights)
    except graph.ValidationError as e:
        raise HTTPException(409, str(e))
    if not public_demo():   # public: arithmetic only, so allowed — but one visitor never rewrites the shared run
        save_run(run)
    return json.loads(run.model_dump_json())


@app.get("/api/companies")
def companies():
    out = []
    for path in list_companies():
        try:
            c = _company(path.stem)
        except Exception:
            continue
        out.append(dict(id=c.id, name=c.profile.name, domain=c.profile.domain,
                        created_at=c.created_at, pages=len(c.pages),
                        attributes=len(c.attributes),
                        intended=sum(1 for a in c.attributes if a.intended)))
    return out


def _company(company_id: str) -> Company:
    if offline_seed(company_id):
        return replay_company()
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
    refuse_in_public("editing a company")
    if offline_seed(company_id):
        raise HTTPException(400, OFFLINE_FIXED)
    c = _company(company_id)
    check_weights(c.attributes, patch.weights)
    by_id = {a.id: a for a in c.attributes}
    for aid, weight in patch.weights.items():
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
    refuse_in_public("editing a company")
    if offline_seed(company_id):
        raise HTTPException(400, OFFLINE_FIXED)
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
    return {"ok": True, "scenarios": sorted(fixture.SCENARIOS), "seed_company": SEED_COMPANY,
            "live_available": live.available() and not public_demo(), "live_status": live.status(),
            "public_demo": public_demo(),
            "measured_model": measured, "evaluator_model": evaluator,
            # a model grading its own output has a self-preference bias worth surfacing
            "same_model_warning": bool(measured and evaluator and measured == evaluator)}


seed_public_runs()

# Production: serve the built web app from the same origin (render.yaml builds it with VITE_API="").
# Mounted last so every /api route above wins.
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
