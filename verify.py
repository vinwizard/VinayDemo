"""The verifier: once a fix from a fleet's plan is live, does AI now say the claim as the experiment
predicted? (WEB.md, "Investigation fleet").

  1. The page, fetched without a model (audit.get): does it carry the copy, word for word? If it does
     not, the fix is not published and nothing is asked, so the check costs nothing.
  2. The branded question, asked live in looks (LOOKS): did AI read a result that carries the fix, and
     does it say the claim? When none of the first look's answers read it, the page is not crawled yet.
  3. A control: the investigation's recorded reading list replayed today. If that rate moved, the
     model itself changed since the experiment, and a before/after difference is not the fix's doing.

The live asks are measurements (live_api) kept in the Verification; the prediction and the control are
replays (counterfactual_replay). They are shown side by side, never pooled, and none reaches a run's
scores. Every call goes through access.openai_response; a check stops at VERIFY_BUDGET_USD.
"""
import html
import os
import re
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Callable, Optional
from urllib.parse import urlparse

import access
import audit
import fleet
import reports
import why
from providers import live
from schemas import Verification, WhyRate
from scoring import wilson

BUDGET_ENV, DEFAULT_BUDGET = "VERIFY_BUDGET_USD", 0.75
LOOKS = (3, 8, 16)          # live asks after each look; none reading the fix at the first is "not crawled"
CONTROL_ASKS = 6
LIVE_ASK_USD = 0.05         # held per live ask before a look: the pilot's dearest was $0.055, its mean $0.034
MIN_PAGE_TEXT = 200         # characters: less is a blocked or script-only page, which proves nothing


def budget() -> float:
    try:
        return max(0.05, float(os.environ.get(BUDGET_ENV) or DEFAULT_BUDGET))
    except ValueError:
        return DEFAULT_BUDGET


def plain(text: str) -> str:
    """Case, spacing and curly quotes aside, so a page's markup does not hide copy that is there."""
    return " ".join(html.unescape(text).replace("’", "'").replace("“", '"').replace("”", '"').split()).casefold()


def carries(copy: str, text: str) -> bool:
    return bool(copy.strip()) and plain(copy) in plain(text)


def page_text(body: str) -> str:
    return re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", body))


def check_page(url: str, copy: str) -> tuple[Optional[bool], str]:
    """-> (whether the page carries the copy, a sentence). None: the page could not be read."""
    name = why.page_name(url)
    try:
        _, status, _, body = audit.get(url)
    except Exception as e:
        return None, f"{name} could not be fetched ({type(e).__name__}), so the live asks decide."
    text = page_text(body)
    if status >= 400 or len(plain(text)) < MIN_PAGE_TEXT:
        return None, f"{name} returned too little text to check (HTTP {status}), so the live asks decide."
    if carries(copy, text):
        return True, f"{name} carries the new copy word for word."
    return False, f"{name} does not carry the new copy word for word yet."


def same_page(a: str, b: str) -> bool:
    key = lambda u: ((urlparse(u).hostname or "").removeprefix("www."), urlparse(u).path.rstrip("/"))
    return key(a) == key(b)


def conclude(v: Verification) -> tuple[str, str]:
    """Where the live rate's 95% interval puts it: at the prediction and away from the old rate, or the
    reverse, or not yet either. A moved control overrides both."""
    lo, hi = wilson(v.live.k, v.live.n)
    pred, base = v.predicted.k / max(1, v.predicted.n), v.base.k / max(1, v.base.n)
    (clo, chi), (blo, bhi) = wilson(v.control.k, v.control.n), wilson(v.base.k, v.base.n)
    said = f"AI says it in {v.live.k} of {v.live.n} live answers"
    was = f"predicted {v.predicted.k} of {v.predicted.n} in replay, against {v.base.k} of {v.base.n} before the fix"
    if v.control.n and (chi < blo or clo > bhi):
        return "model_moved", (f"The model itself changed: replayed today, the old reading list gives it in {v.control.k} "
                               f"of {v.control.n} against {v.base.k} of {v.base.n} when it was tested, so this "
                               f"before/after is not the fix's doing. {said}.")
    if lo <= pred <= hi and not lo <= base <= hi:
        return "confirmed", f"Confirmed: {said}, as {was}."
    if lo <= base <= hi and not lo <= pred <= hi:
        return "not_confirmed", f"Not confirmed: {said}; {was}. AI reads the fix and says it no more often."
    return "undecided", f"Not decided yet: {said}, which fits both the old rate and the prediction ({was})."


def verify(fleet_id: str, rank: int, resolve: Callable[[], object], emit: Callable[[str], None] = lambda text: None,
           lab: Optional[why.Lab] = None, evaluator=None) -> Verification:
    """Re-checks one plan item of a finished fleet. `resolve` gives the live model pair (live.preflight)
    and is called only once a live ask is needed, so an unpublished fix needs neither key nor pass."""
    p = fleet.plan_of(fleet.EventLog(fleet_id).read())
    item = next((i for i in p.items if i.rank == rank), None) if p else None
    if item is None or item.fix not in ("copy", "authority") or not item.investigation_id or not item.page_url:
        raise ValueError("only a tested copy or authority fix can be re-checked")
    inv = reports.load_investigation(item.investigation_id)
    run = reports.load_run(inv.run_id)
    attribute = next(a for a in run.attributes if a.id == inv.attribute_id)
    arm = next(a for a in inv.arms if a.id == item.arm_id)
    copy = item.rewrite or (arm.text[0] if arm.text else "")
    v = Verification(fleet_id=fleet_id, rank=rank, attribute_id=attribute.id, claim=inv.claim, page_url=item.page_url,
                     copy_text=copy, question=inv.question, investigation_id=inv.id, budget_usd=budget(),
                     predicted=WhyRate(k=arm.k, n=arm.n), base=WhyRate(k=arm.base_k, n=arm.base_n))
    v.page_has_copy, v.page_note = check_page(item.page_url, copy)
    emit(v.page_note)
    if v.page_has_copy is False:
        v.verdict, v.text = "not_published", f"Not published: {v.page_note} Nothing was asked, so this check cost nothing."
        return v
    if lab is None:
        from agents.evaluator_model import ModelEvaluator
        resolved = resolve()
        lab = why.Lab(resolved.model, resolved.tool)
        evaluator = None if inv.term else ModelEvaluator(model=resolved.judge, transport=lab.judge_transport)
    judge = why.Judge(attribute, run.profile, inv.question, inv.term, evaluator, endorse=inv.counts == "endorsements")
    read_it = ((lambda r: carries(copy, r.text)) if item.fix == "copy" else (lambda r: same_page(r.url, item.page_url)))

    def pmap(fn, n):   # contexts copied here, in this thread, so the pass and purse reach the calls
        with ThreadPoolExecutor(why.CONCURRENCY) as pool:
            return [f.result() for f in [pool.submit(copy_context().run, fn) for _ in range(n)]]

    def afford(usd: float) -> None:
        if lab.spent + usd > v.budget_usd:
            raise why.OverBudget

    try:
        for look in LOOKS:
            afford((look - v.read_by_ai.n) * LIVE_ASK_USD)
            for raw in pmap(lambda: lab.live(inv.question), look - v.read_by_ai.n):
                text = live.parse_response(raw)[0]
                reading = live.reading_of(raw, cap=None) or []
                v.read_by_ai.n += 1
                v.read_by_ai.k += any(read_it(r) for s in reading for r in s.results)
                states, quote = judge(text) if text else (None, None)
                if states is not None:
                    v.live.n, v.live.k = v.live.n + 1, v.live.k + states
                    if quote and len(v.live_quotes) < 3:
                        v.live_quotes.append(quote)
            emit(f"Asked live {v.read_by_ai.n} times: AI read the fix in {v.read_by_ai.k} and said it in "
                 f"{v.live.k} of {v.live.n}.")
            if look == LOOKS[0] and not v.read_by_ai.k:
                v.verdict = "not_crawled"
                v.text = (f"Not crawled yet: none of {v.read_by_ai.n} live answers read "
                          + ("the new copy" if item.fix == "copy" else why.page_name(item.page_url))
                          + ". Check again once search has picked it up.")
                v.spent_usd = round(lab.spent, 4)
                return v
        afford(CONTROL_ASKS * 0.01)
        texts = pmap(lambda: live.parse_response(lab.replay(inv.question, inv.reading))[0], CONTROL_ASKS)
        for states, _ in map(judge, texts):
            if states is not None:
                v.control.n, v.control.k = v.control.n + 1, v.control.k + states
        emit(f"Replayed the old reading list {v.control.n} times: it gives it in {v.control.k}.")
        v.verdict, v.text = conclude(v)
    except (why.OverBudget, access.PurseEmpty):
        v.verdict = "budget"
        v.text = (f"Stopped at the ${v.budget_usd:.2f} budget after {v.read_by_ai.n} live asks: "
                  + (conclude(v)[1] if v.live.n else "nothing to conclude yet."))
    v.spent_usd = round(lab.spent, 4)
    return v
