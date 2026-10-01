# Web frontend (React + FastAPI)

The product UI. The Python engine — `graph.py`, `drift.py`, `agents/`, `scoring.py` and the fixtures —
is imported, not reimplemented. The API runs the graph on a worker thread and pushes an SSE event per
**answer** as well as per node, so the browser sees progress while a long batch is still running (why it
replaced a Streamlit app: `.claude/skills/build-history`).

## Run it

Two processes. Both commands work in **any** shell, interactive or not.

Terminal 1 — the API, from the repo root:

```bash
cd ~/Projects/VinayDemo && ~/miniconda3/envs/visexp/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Terminal 2 — the frontend:

```bash
cd ~/Projects/VinayDemo/web && export PATH="$HOME/miniconda3/envs/visexp/bin:$PATH" && npm run dev
```

Open **http://localhost:5173** — not `127.0.0.1:5173`. Vite binds IPv6 localhost and the numeric
address is refused. The browser calls the API on port 8000 unless `VITE_API` says otherwise — useful
when a second checkout is running beside the first:

```bash
VITE_API=http://127.0.0.1:8731 npx vite --port 5731   # with the API started on --port 8731
```

### Why not `conda activate`

`conda activate` is a shell function installed into `~/.zshrc`, so it only exists in an **interactive**
shell that has sourced that file. It works in a fresh Terminal.app tab; it fails with
`command not found: conda` in a non-interactive shell, a script, or an editor's embedded terminal.

The commands above sidestep it entirely. The API command calls the env's Python by absolute path.
The frontend command needs the `PATH` export because npm's shebang is `#!/usr/bin/env node` and
cannot find node otherwise. If you prefer `conda activate`, open a new terminal window first, or run
`source ~/.zshrc`.

### Live mode

Put your key in `.env` at the repo root (gitignored, never committed):

```
OPENAI_API_KEY=sk-...
```

Everything else has a working default. The full list, and what each one changes:

| Variable | Default | What it does |
| --- | --- | --- |
| `OPENAI_API_KEY` | — | The only required one. Without it live mode errors rather than replaying fixtures. |
| `MEASURED_MODEL` | `gpt-6-luna` | The model that ANSWERS the buyer and brand questions: the one being measured. It must accept the Responses API `web_search` tool. The default is the cheapest current model that does ($0.10/$0.50 per 1M tokens, knowledge to May 2026). `gpt-4.1` was the old default and its training stops in 2024, so it answered about brands it had never heard of. |
| `EVALUATOR_MODEL` | `gpt-6-luna` | The separate model that grades those answers. It is sent no tools at all — it reads text it is handed. It defaults to the same model as the measured side, so both halves of a run are priced the same; that means one model grades its own answers, which `/api/health` surfaces as `same_model_warning`. Set it to something else (`gpt-4.1-mini` is the tested one) to remove the self-preference bias. |
| `ONBOARDING_MODEL` | `gpt-4.1-mini` | Reads a company's own pages and extracts what they claim, and writes buyer questions for a category. |
| `TARGET_MARGIN` | `20` | The margin each buyer front aims for, in points of "named you", at 95% (`sampler.py`). It sets how many questions a front freezes and asks: 10 first, and the rest of 23 only where those are not clear yet. `15` means 16 then 43 — about 2.5× the buyer calls on a mid-range brand. Clamped to 5–50. |
| `RUN_BUDGET_USD` | unset | The most one run's measured calls may spend. A front whose look 2 would pass it stops at look 1, and its margin is reported as not met. Unset: look 2's size is the cap. |
| `LIVE_CONCURRENCY` | `16` | How many measured asks the whole server has in flight, every run together (`dispatch.py`). Runs take turns, one ask each, so a big run never makes a small one wait for it to finish. A 429 from OpenAI pauses every call for the time it asked (`Retry-After`), then retries, up to 4 times. |
| `WOBBLE_AUDIT` | `1` | How many times each front's first question is asked again, to show how much one question wobbles. `0` turns it off. |
| `WHY_BUDGET_USD` | `0.60` | The most one why investigation may spend (`why.py`); it stops there and says how far it got. The mean investigation on Amgen cost $0.36 (2026-09-28). |
| `FLEET_BUDGET_USD` | `3.00` | The most one investigation fleet may spend, every agent together (`fleet.py`, "Investigation fleet" below). |
| `FLEET_CONCURRENCY` | `3` | How many of a fleet's investigators run at once (1–6); each already asks 6 calls at a time. |
| `VERIFY_BUDGET_USD` | `0.75` | The most one re-check of a fix may spend (`verify.py`). An unpublished fix costs nothing. |
| `DATA_DIR` | bundled `data/` | Where runs, companies and the access database are kept. On Render, the mount path of a disk, or a redeploy wipes them. |
| `VISEXP_PUBLIC_DEMO` | unset | Hosted demo: saved replays for everyone, live runs only for a pass holder. |
| `SESSION_SECRET`, `ADMIN_PASSWORD`, `CONTACT_EMAIL` | — | Access passes and the admin page: "Deploy to Render" below. |
| `VISEXP_OFFLINE_REPLAY` | unset | Measuring the preloaded company replays the bundled sample instead of calling a model. |
| `VISEXP_DEV_DELAY` | `0` | Development only: seconds of pause per replayed answer, to watch the stages move ("Run it" below). |

`MEASURED_MODEL` replaced `LIVE_MODEL`, which is no longer read: an old `.env` that still pins
`LIVE_MODEL=gpt-4o-mini` would otherwise have kept the model that named obscure tools for a category
leader's own category. Every live report names both models ("answered by gpt-6-luna, judged by
gpt-4.1-mini"); `/api/health` reports `measured_model`, `evaluator_model`, `forced_search`,
`target_margin`, `looks`, `buyer_questions` (the questions a front freezes), `max_buyer_questions`
(the most a run may plan: both fronts plus one front's worth for weighted claims), `wobble_audit`,
`run_budget_usd` and `why_budget_usd`, `live_concurrency`, `fleet_budget_usd`, `fleet_concurrency` and `verify_budget_usd`, plus `configured_measured_model`, `search_mode` and
`model_fallback` when a step-down happened.

Any model you point `MEASURED_MODEL` or `EVALUATOR_MODEL` at should be in `access.PRICES`, or the
spend meter charges it `UNKNOWN_PRICE` — deliberately above every listed model, so a pass is never
under-charged for a model nobody priced.

#### What a run actually costs

Measured on a real run against the API on 2026-09-22 (Anthropic, budget turned down to 3 buyer
questions a front, 16 measured answers, gpt-6-luna both halves): **$0.40** at OpenAI list prices,
every call priced exactly rather than estimated. The shape of that bill is the thing worth knowing:

| | |
| --- | --- |
| web_search calls | 35 — **88% of the bill** ($0.35) |
| all tokens, both models | $0.05 |
| searches per measured answer | ~2 |

Forced search worked: 16 of 16 answers were grounded, none needed the retry, and none was discarded.
Because search dominates, the **model** is no longer the cost lever — the **number of answers** is.
A buyer answer averaged **$0.025** on 24 Amgen buyer questions (2026-09-28). `TARGET_MARGIN` is
therefore the dial that moves the bill: at ±20 a front costs 10 to 23 buyer asks (about $0.50–1.15
for two fronts, against $0.80 for the old fixed 16 a front, which guaranteed no margin), at ±15 it
costs 16 to 43. Each weighted claim adds one topic of 3 questions (about $0.08) on top, at most one
front's worth, so the known maximum at ±20 is 72 buyer questions (about $1.80, `max_buyer_questions`). The tool's `search_context_size` is the one lever still untouched. The preflight call costs one forced search of its own (~$0.01): that is
the price of proving the exact request shape before spending a run on it.

Restart the API. It prints `[config] loaded from .env: OPENAI_API_KEY=<set>` — names only, never
values. Check `curl -s http://127.0.0.1:8000/api/health` for `"live_available": true`. There is no
mode switch in the page: every measurement it starts is live.

A live run asks every brand question once and, beside them, the buyer questions on where the company
aims to be (its own category needs no brand answer); the buyer questions on where AI places it are
planned the moment the brand answers are read. Each buyer question is asked once to the measured model — look 1 first, look 2 only where needed, and one per
front once more — plus one **control question** per front, and has the evaluator grade each
answer — two calls per ask — plus one round-two comparison question when a buyer answer names a
competitor, and one evaluator call at the end for the action plan. Without a key, live mode
**errors** rather than falling back to fixtures — a fixture result under a live label would be a
fabricated measurement.

Asks run side by side (`graph.Asks`, `dispatch.py`): a question is submitted the moment it is frozen
and collected when the next step needs it, and each front decides its own look 2 as soon as its look-1
answers are in. The run is written only by the graph, and in one fixed order (`graph.canonical`), so a
saved run never depends on which answer came back first and matches what one-at-a-time asking saved.
Two differences follow from asking the aimed front first: a question both fronts' pools hold stays on
the aimed front, and when AI places the company in its own category the aimed set becomes the one
shared set as asked, without topping it up from the placed questions. Under concurrency a pass's cap
counts the estimated cost of its calls under way; a call that would pass the cap with them waits for
them to be charged, so a pass stops where it always did, about one call past its cap. With 16 at
once a live Amgen run (`TARGET_MARGIN=33`, 28–30 asks) took 192 s against 325 s at 3.

Before a live run the API makes one trivial preflight call, so a broken setup fails once with one
message rather than once per question. It is classified on the HTTP status, never the error text: a
401 means OpenAI refused the key, a 403 is an account-level refusal (most often OpenAI not serving
your region), and only a 400 means the model will not take the web_search tool and the model needs
changing — set `MEASURED_MODEL`. The message names the error type and status only — the provider's response body is never
shown, because a 401 body quotes part of the key back.

Set `EVALUATOR_MODEL` to a different model from `MEASURED_MODEL`: a model grading its own output has
a self-preference bias.

**Search is required, not offered.** Every measured call carries `tool_choice: "required"`
(`live.TOOL_CHOICE`) and the tool `{"type": "web_search", "external_web_access": true}`
(`live.SEARCH_TOOL`), because an answer written from memory is excluded from live scores
(`scoring.eligible`) — paid for and then thrown away. `external_web_access` asks for the open
internet rather than the tool's offline/cache-only mode. A response that still comes back with no
`web_search_call` is asked once more; if the second try does not search either, the answer is kept
and marked ungrounded exactly as before. Grounding is still read off the response, never assumed.

**If OpenAI refuses that pair, preflight steps down — never silently.** The one trivial call before
a run tries, in order: the configured model with `external_web_access`; then `live.FALLBACK_MODEL`
(`gpt-5-nano`) with plain `web_search`; then `gpt-5-nano` with **no tool at all**, where every answer
comes back ungrounded and is excluded from the scores. Only a 400 steps down — that means the model
or the tool shape was not accepted, not that the key, account or network is wrong. There is no third
model: substituting one nobody chose would be a quieter failure than measuring nothing. The judge
follows it only when the judge is on the refused model — by default it is, since both default to
gpt-6-luna; a judge set separately is kept. `/api/health` reports
`measured_model`, `evaluator_model`, `configured_measured_model`, `search_mode` and
`model_fallback`, and the reason appears in the run log and the report's limitations.

#### Why a rerun gives a different number, and what the report does about it

The measured model answers the same question differently every time — web search returns different
pages, and the model samples its wording. Asked once, a question is one draw: rerun the same company
and a buyer question that named the brand may not name it again, so visibility moves between runs
without anything about the company changing. That is expected, not a bug in the scoring. Three
things make the buyer number trustworthy anyway:

- **Visibility is measured on two fronts, side by side.** Where you aim to be is planned and asked
  beside the brand questions (`graph.plan_aiming`); the brand answers are read (`graph.perceive`) and
  `graph.plan_buyer` plans where AI places you around it, so the two fronts cover two
  categories, a full pool of `ana.set_questions()` each (look 2 for `TARGET_MARGIN`), plus one topic
  for every claim the customer weighted (at most one front's worth), so each weighted claim is asked
  its own buyer questions, its Quick-wins fix can cite them, and neither front drops below look 2:
  **where AI places you** — the attribute, claimed or discovered, that the most valid brand answers
  endorsed (`ana.placed_attribute`; ties go to the claim stated on more pages; one discovery marked
  `business`, about the company's stock, revenue, cash or size rather than what it sells, is never
  placed; its questions are the claim's own, topped up by the onboarding model) — and **where you
  aim to be**, the site's core category (`profile.core_category`, named at onboarding from the one-line description, blind
  questions written for it, correctable on the claims screen). Each front has its own visibility,
  repeat sample, wobble and control question (`drift.sets`), and `drift.visibility_gap` is placed minus
  aiming: "known for AI search visibility, not yet seen as an AI marketing platform" is the finding.
  When both are the same category (`ana.same_category`: one's content words all in the other's) one
  set is asked and the run says so; with only one front measured (the same category, no endorsed
  attribute, no saved category or no questions left) the claims' own buyer questions fill the other
  half, counted in neither front, and the run says why the front is missing (`drift.missing_fronts`);
  with neither, questions follow the claims as before. The placed front cites only that attribute's
  own claim evidence, never the homepage's. Every question
  still goes through `brand_leaks` and `vendor_address`. A replayed sample is one unlabelled set.
- **Buyer questions come from real demand first** (`demand.py`). For each front's category a live
  run harvests Google autocomplete suggestions (a few question-prefix seeds) and Reddit's public
  search, keeps phrasings on the category with buying intent that never name the brand or address
  the vendor, groups them by meaning (`text-embedding-3-small`, metered through `access.py`;
  average-link clustering at one cosine threshold) and asks the most central phrasing of the
  biggest groups first, exactly as people typed it; no model rewords it. Each such probe carries
  `probe.demand` (the real phrase and its whole group), shown as a "real demand" badge; the
  written questions fill any shortfall. Harvests are cached a week under `DATA_DIR/demand/`.
  Reddit refuses unauthenticated clients from many networks and "People also ask" would mean
  scraping Google, so the one is stated when it fails and the other is not used. Nothing is a
  volume estimate. With no usable searches the front keeps its written questions and
  `run.demand_notes` says why. Tests never touch the network (`tests/conftest.py`).
- **Each front asks fresh questions until its margin is met** (`sampler.py`, sampler-lite). On the
  Amgen run 35 of 36 re-asks of a buyer question gave the same answer (intraclass correlation 0.90),
  so what a front's number does not know yet is the questions not asked, not one question's wobble.
  Each front freezes a pool sized for `TARGET_MARGIN` (±20 points of "named you" at 95%: 23
  questions), asks the first 10, and asks the rest only if the Wilson interval of those 10 is wider
  than the margin — a front AI never (or always) names the brand in is clear after the first look.
  The 5% error is split 1% at look 1 and 4% at look 2 (`sampler.ALPHA1`, `ALPHA2`), so the reported
  interval holds the true rate with at least 95% whichever look the front stopped at, and look 2 is
  the known most a front can cost. Questions no front needed leave the run's questions for
  `run.sampler.unasked`; the frozen hash covers both (`graph.frozen_hash`). Simulated on cells fitted
  to that run, a bandit or a Bayesian allocator saved nothing over this, so neither is built.
  `WOBBLE_AUDIT` asks each front's first question once more; that re-ask is the **wobble**
  (`drift.visibility_range`), shown inside the number's popover, and like every re-ask it is stored
  in `run.repeat_answers` / `repeat_evaluations`, so everything else reads the first try. Buyer
  visibility is still the mean over **questions**, each worth the mean of its own tries
  (`scoring.visibility_by_question`). The report shows each front's rate of "named you" with its
  margin and how many of the frozen questions it took (`run.sampler.fronts`). A replayed sample has
  one authored answer per question, no sampler and no wobble, and its numbers do not move.
- **Buyer answers are shared across brands in one category** (`sharing.py`). A buyer question
  never names a brand, so the same question asked of the same model on the same UTC day is the same
  measurement whichever brand it is scored for. The pool a front was planned with is kept per
  category and day, so the next brand in that category asks the same questions (vetted again for
  it), and each grounded buyer answer is reused, flagged `shared`, and judged again for the brand it
  now scores: tracking a brand and five rivals pays for the buyer calls once. Brand questions and
  re-asks are never shared. On the public demo nothing is shared across access passes. Kept in
  `DATA_DIR/shared.db`.
- **Every number says how sure it is.** `scoring` bootstraps a 95% confidence interval (2,000
  resamples, fixed seed, so a saved run always shows the same interval) and the report shows it as a
  small low–high range beside the number (the headline's in untapped-potential terms, 100 minus the
  score's range), what it means one tap away. Visibility resamples the buyer questions, then each
  chosen question's tries (`visibility_draws`, weighting each question once exactly as the score
  does), from `MIN_INTERVAL_ANSWERS` (5) scored questions up; with nothing re-asked there is no
  interval, so a replayed sample says "No question was asked twice". This is the range the summary
  shows, in plain words ("could be 16.7–50 if we asked again").
  The gap between fronts is bootstrapped draw by draw (`gap_verdict`): an interval that excludes 0
  reads "The gap is real, 95% confident" (`drift.gap_real`), otherwise "Not distinguishable with this
  sample". When either front has no interval, or one whose width is zero (its answers never varied),
  the verdict is withheld: "Too few questions to call the gap", the reason in
  `na_reasons["visibility_gap_interval"]`. Claim echo and
  alignment resample the brand answers (`echo_draws`), from `MIN_INTERVAL_ANSWERS` (5) answers up;
  below that the reason is in `na_reasons["<field>_interval"]`. `score_drift` computes them, so a
  rescore recomputes them.
- **A control question checks what a front's number means.** One extra blind question per front,
  "What are the leading tools for <category>?", is asked once and never scored (`phase="control"`).
  Whatever the buyer answers scored, `scoring.low_confidence` flags that front **low confidence**,
  with the reason, if its control answer names fewer than two tools (the model does not know the
  category), does not name the brand (the model does not count it among the category's leaders —
  a brand named once by chance is still not known there), or could not be scored. If the control
  names the brand, the number stands. A flagged number is never shown bare — the badge sits beside
  it in the pinned summary, the Questions we asked AI tab and the PDF summary.
- **A generic phrase is never the brand's name.** An alias counts as a mention unless every word in
  it is a generic noun (`schemas.distinctive_alias`), so a product name such as "Conversation
  Explorer" still counts and is still a brand leak. "AI Marketer" and "AI Agents" are dropped at
  onboarding and ignored on older saved companies, and
  matching stays word-bounded and case-sensitive, so "AiMarketer" is not the brand.

### Investigation fleet

After a live run, a team of agents works out why AI says what it says and what would change it, at
the same time, from the **Investigate the gaps** button on Quick wins (`fleet.py`, `verify.py`,
`api/fleet.py`). It reads the saved run and never writes it.

- **Coordinator** — a model (the evaluator model) choosing from a shortlist code builds
  (`fleet.shortlist`: claims to win back, amplify or correct, and perceptions AI raised in a brand
  answer, each with the run's branded questions that do not name it and what each answer said).
  It picks the claims worth money and the question for each, and a literal term only for a
  perception AI raised. Every call it makes is Responses API function calling, and every call is
  checked (shortlisted claim, one of its questions, no term on a company claim, 2 tries a claim,
  8 tasks, affordable); a refused call goes back to it as a reason. When its call fails or none of
  its calls can be used, code's own ranking decides, and the task says "picked by code".
- **Investigators** — `why.start`, one per claim and question, `FLEET_CONCURRENCY` at a time on
  a stdlib thread pool; each stops at its own budget, the fleet's purse, or its deadline
  (`live.LIMITS["investigation_deadline_s"]`, checked where it already checks its budget, so it keeps
  what it found). One failing never stalls the rest.
- **Critic** — code rules on each finished investigation (`fleet.critic`): not reproducible, a
  **ceiling** (a claim AI already says in 90% of replays of that question, where no fix can show a
  rise), stopped with an experiment still open (asks for more budget), quotes that share no word with
  the claim, and a fix that moved it on one question and not another. The coordinator re-dispatches
  once, changing one thing, or accepts.
- **Planner / writer** — code ranks what was accepted: tested copy fixes by the low end of their
  interval times intent weight, then authority fixes, then sources to address (a perception's
  pages), then what copy cannot move, then what did not decide, then the run's untested rewrites.
  Every number is copied from an experiment. One model call rewords the lines; a line is kept only if
  it adds no number, no page and no marketing word (`fleet.acceptable`), else the template's stays.
  $0.05 of the purse is held back for it, so running out never leaves a fleet without its plan.
- **Verifier** — "Mark fix live" on a tested fix (`verify.py`): for a copy fix or a hypothetical
  rewrite the page is fetched first, without a model, and one whose copy is not on it word for word
  is "not published" for $0 (an authority fix on unchanged copy skips this check). Then the
  question is asked live 3, 8, then 16 times, recording whether AI read the fix (none of the first
  three reading it: "not crawled yet"), and the investigation's old reading list is replayed as a
  control (it moving means the model changed, not the page). Confirmed means the live rate's 95%
  interval holds the prediction and not the old rate.

Agents never call each other: they write typed `FleetEvent`s to one append-only log,
`DATA_DIR/fleets/<id>.jsonl`, which the fleet's loop thread alone writes while it runs (a re-check
appends once it is done) and the page streams, resuming from the last event it saw. Every model
call of every agent goes through `access.openai_response` and draws on one `access.Purse`
(`FLEET_BUDGET_USD`, and at most 18 calls in flight), inside the pass that started the fleet; the
pass cap still applies call by call. Investigations are `counterfactual_replay` and never scored; a
re-check's live asks are `live_api` but kept in its `Verification`, never added to a run. A server
restart mid-fleet marks it stopped and keeps what finished.

Two live fleets on the committed Amgen run (2026-09-28, gpt-6-luna for every agent): 6 investigations
each (5 picks and 1 re-dispatch; the coordinator skipped the 4 flattering perceptions, with a reason
each), **8.4 and 9.6 minutes** against 18.0 and 23.8 had they run one after another, for **$0.98 and
$1.25**, of which the coordinator and writer were $0.003–0.005. The first found a copy fix for
"biologic medicines" (your rewrite on /about: 12 of 18 replays against 0 of 18); the second, on the
same question, did not decide it — what AI reads changes between runs, so a plan is one fleet's
reading. Both traced "significant debt" to one line of the Q2 2026 earnings release on sec.gov.

### Offline fallback — no network, no key

For a demo on bad wifi, start the API with `VISEXP_OFFLINE_REPLAY=1`, then reopen Notion from the
Onboard tab ("Or reopen one you already onboarded"). Measuring the preloaded Notion company then replays the bundled Notion sample (fixture scenario A) instead of asking a model.
Nothing in the page can turn this on; it lives only in the server's environment, and only the
preloaded company is affected — any other company still refuses without a key. The run says what it
is everywhere it appears: an "Offline replay — sample answers, not a measurement" notice above the
stages, a SAMPLE tag on every streamed answer, and the SYNTHETIC DEMO banner on its report and in
History. While it is on, the reopened Notion company shows the sample's own claims in place of the real read of
notion.com, so what is on screen is exactly what is scored; its sliders are locked and the API
refuses to edit it, so the committed seed file is never touched.

To watch the stages move with a visible pause per answer, add `VISEXP_DEV_DELAY=1` (seconds per
replayed answer) to the same command:

```bash
VISEXP_OFFLINE_REPLAY=1 VISEXP_DEV_DELAY=1 ~/miniconda3/envs/visexp/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

`node` and `npm` come from the `visexp` conda env — nothing is installed system-wide.

## Onboarding

Only the company's name is needed (`web/src/find.tsx`, `discovery.py`, `documents.py`).

1. **Find.** One web search on the measured model's search tool (`live.SEARCH_TOOL`, metered like
   every call) returns up to three companies the name could mean. A candidate is kept only when its
   domain came back in a search result, never from the model's own knowledge. The customer always
   confirms, because a made-up name still comes back with confident near-misses: those are offered
   as not an exact match, with a warning. "No, it's a different company" searches again with what
   the customer adds. A website typed under "I know the website" skips the search.
2. **Read.** The plain crawl (`fetching.fetch_site`) comes first. When it reads fewer than three pages
   (`MIN_DIRECT_PAGES`), one more search fills up with the company's own pages: each is read directly
   when it lets us (a subdomain often does when the main site will not), else its **search copy**
   is used, the text the search engine saved, with its age ("saved 3 days ago"). perplexity.ai turns
   every automated reader away with Cloudflare's "verify you are human" check, and a real Chrome
   window gets the same, so there is no headless browser: search copies are the fallback.
3. **What counts as claimed.** An own page is on the confirmed domain or a subdomain **and** names the
   company (perplexity.ai also hosts other companies' SEC filings). Pages in another language are
   skipped, and tracking query strings dropped. Everything else that names the company is
   **third-party** (Wikipedia, news, forums): stored as `Company.third_party`, listed as "Others
   about you", never extracted and never counted.
4. **Documents.** PDF (text layer only, via `pypdf`; a scan is refused, there is no OCR), Word .docx
   (standard library), text and Markdown, or pasted text. Up to 5 files, 10 MB each, 30,000
   characters kept each. Only the text is kept, as JSON under `DATA_DIR/uploads/<hash of the pass>/`;
   the file is never stored, and a document is only ever loaded from the caller's own folder.
   Documents add to the pages read, or with "Use only my documents" replace them; with no website
   they are the only source. Quotes are checked word for word against their text like a page's.
   A document is private: it never counts toward "stated on N% of your pages", which is over public
   pages only (own pages and search copies); a claim also in documents says so. A claim found only
   in documents is `private_only`, and if AI does not
   repeat it, `drift.classify` calls it a **messaging gap** (the company has not said it in public),
   never an authority gap. The site audit skips such claims and does not run with no website.

Every source keeps its kind through to the saved company (`Evidence.source_type`: `page_fetch`,
`search_copy`, `uploaded_document`) and the page lists it with its label. A fetch that fails says
why in plain words (`fetching._plain`, `fetching.status_problem`): "did not answer within 10 seconds",
"has a security certificate that is not valid", "turns automated readers away (HTTP 403)", "there is
no website at …", "shows no text until script runs".

Cost, measured on 2026-09-28 with `gpt-6-luna`: a find is $0.011 (one search); filling up from search
is $0.04 on perplexity.ai (four searches, only when the site turns us away); extraction on
`gpt-4.1-mini` is about $0.005–0.02. About 2¢ for a site that can be read, about 7¢ for one that cannot.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | liveness, whether live mode is usable for this browser (`live_available`) and whether a key is set on the server at all (`key_configured` — on the public demo a visitor without a pass sees the second true and the first false, and the page asks them to open their pass link rather than reporting a missing key), and `seed_company` — the id of the preloaded company, `showcase` — the company and run ids of the committed live example in History, and `contact_email` — where to ask for a pass or a higher cap (`CONTACT_EMAIL`), and `storage` — whether the pass database survives a redeploy ("Deploy to Render" below) |
| `GET /api/stream?company=<id>` or `?scenario=A&mode=demo` | SSE while the graph runs: `node` (with `planned` question counts per stage, discovered `competitors` and the run `mode`), `answer` (the question, the first 320 characters of its answer, provenance and whether a web search ran), `done` (the full run), `error`. A company is always `mode=live`, apart from the offline fallback above. The page only ever measures companies; `?scenario=` remains for the fixture path |
| `GET /api/runs` | run history, newest first; each row's `mode` (`live_api` for a measured run) lets History mark it measured live or a sample |
| `GET /api/runs/{id}` | one full run, including the drift report and its `insights` (share of voice, cited sources and the brands each was cited beside, searches); the stream's `done` event and `rescore` return the same shape |
| `POST /api/runs/{id}/reask` | test a fix: `{probe_id}` asks that buyer question once more, with the rewritten passage and the cited page's passage as the only sources, and saves whether the brand was named on its retrieval row. One metered model call; live runs only, refused on the public demo without a pass. A simulation that moves no score |
| `POST /api/runs/{id}/rescore` | lens 2 after the fact: `{weights: {id: 0..1}}` sets intent on a finished run and re-scores its saved answers — no provider is built and no model is asked. Unnamed weights keep their value; 0 unweights; with nothing weighted the run reads through the claim lens again. Saved in place, except in the public demo (`VISEXP_PUBLIC_DEMO`) and for the committed live example (`SHOWCASE_RUN`) |
| `GET /api/onboard/find?name=&hint=` | which company a name means: one web search, up to three `candidates` (`name`, `domain`, `what`, `exact`) and whether any is an exact match (`discovery.find`). The customer confirms one before anything is read; "No, it's a different company" asks again with a `hint`. Needs the key; refused on the public demo without a pass |
| `POST /api/onboard/documents?filename=` | one document as the raw request body (PDF, .docx, .txt, .md; 10 MB) → `{id, filename, chars}`. Only its text is kept, in the pass's own folder (`documents.py`); 413 when too large, 422 with the reason when it cannot be read |
| `GET /api/onboard/stream?url=&name=&docs=&only_docs=` | the same onboarding as SSE: `pages` (`pages`, the web URLs read, and `sources`, each with how it was read) as soon as everything is read, then `company` once extraction is saved, or `error`. The page uses this one |
| `GET /api/onboard?url=&name=&docs=&only_docs=` | Agent 1: read up to 8 of a company's own pages (`CRAWL_PAGES`; search copies when the site turns us away) and any uploaded documents (`docs`, comma-separated ids; `only_docs=true` skips the website), extract the **claimed** layer (attributes, verbatim quotes, derived page counts) and **save** the company. `url` may be empty when documents are given. Needs the same key as live mode. A company is always saved, never refused: one where fewer than three claims survive quote validation carries a prominent warning that it states too little for a reliable claim percentage, and the existing insufficient-evidence rules withhold the scores rather than the company. The company carries `sources` and `third_party` ("Onboarding" above) |
| `GET /api/companies` · `GET /api/companies/{id}` | onboarded companies, newest first, and one in full |
| `PATCH /api/companies/{id}` | the customer's own input: `{weights: {id: 0..1}, added: [{label, description, intended_weight}]}`. Intent arrives only here (or on `rescore`) — never derived from their copy, and a weight of 0 leaves an extracted attribute unintended. Weights are optional: a company measured with none runs the claim lens. An **added** claim is intended by construction, so its weight cannot go below 0.1 |
| `POST /api/access/exchange` · `GET /api/access` | access passes on the hosted demo (`access.py`): `{code}` from a personal link `/?pass=<code>` becomes an HttpOnly session cookie; `GET` is the holder's meter (`{pass: {label, spent_usd, cap_usd, capped}}` or `{pass: null}`). With a pass, live runs and onboarding are allowed on the public demo, charged to the pass, every run it makes (replay or live) is saved under `DATA_DIR`, and runs and companies are listed only to the pass that made them — a pass sees none of the shared preloaded ones. `/admin` (behind `ADMIN_PASSWORD`) creates passes, shows each link once, and tops up or revokes. Cookies are same-origin, so passes work on the production build, not across the Vite dev port |
| `POST /api/companies/{id}/audit` | checks again whether AI can read the site (`audit.py`) and saves it on the company; the same check runs once during onboarding. Plain fetches, no model and no key: robots.txt for the AI crawlers, the claim's words in the no-JavaScript HTML, schema.org JSON-LD, headings, load time and llms.txt, on every page that states each claim, plus Wikidata/Wikipedia (tied to the company only by Wikidata's official website on its domain) and the Crunchbase, G2 and LinkedIn pages the site itself links to. Anything that cannot be reached, or whose robots.txt turns automated tools away, is "could not check", never a guess. A company read from documents only (no pages, no domain) is refused with 400. A run copies the company's audit when it starts |
| `GET /api/runs/{id}/why/stream?attribute=&probe=` or `&question=`, optional `&term=` | the why agent (`api/why.py`) as SSE: `start` (its budget), `log`, `arm` (one experiment, decided), `verdict`, `done` (the investigation, saved under `DATA_DIR/investigations/`), `error`. Live runs only; refused on the public demo without a pass, without a key, or with a model that cannot search. The question must name the company and not the claim |
| `GET /api/runs/{id}/rewrite-test/stream?attribute=&probe=` | a Quick wins rewrite's **replay test** (`why.test_rewrite`): the same SSE events as the why agent, for the claim's rewrite against one buyer question it was written for, counting the gap the question has: whether the answer names the company, or, for a question that named it without recommending it, whether it recommends it. The investigation is saved with `kind: "buyer"` and `counts: "names"` or `"recommends"`. Refused as the why agent is, and for a question the rewrite was not written for |
| `GET /api/investigations/{id}/verify/stream` | "Mark fix live" on a rewrite its replay test proved (`verify.verify_investigation`): `log` lines, then `done` with the Verification, which is kept on the investigation. The page is read first, free; an unpublished rewrite asks nothing |
| `GET /api/runs/{id}/why` · `GET /api/investigations/{id}` | a run's investigations (claims' and rewrites'), newest first, and one in full. The run itself is never changed |
| `POST /api/runs/{id}/fleet` | starts an investigation fleet on a live run ("Investigation fleet" above) and returns `{id}` at once. Refused on the public demo without a pass, on a sample run, with nothing to investigate, while another fleet is running on the run, and without a model that can search |
| `GET /api/runs/{id}/fleets` | a run's fleets, newest first (`status`, `spent_usd`, `wall_s`), and what a new one would cost (`estimate`: shortlist size, picks, dollars, minutes) |
| `GET /api/fleets/{id}/stream?after=` | the fleet's log as SSE: one `fleet` event per `FleetEvent` (with its number as the SSE id, so a reconnect resumes after `after` or `Last-Event-ID`), then `end` once it is done |
| `GET /api/fleets/{id}/verify/stream?rank=` | re-checks plan item `rank` of a finished fleet: its `verify` and `verified` events as SSE (also kept on the log), then `end`. Only a tested copy or authority fix |
| `DELETE /api/companies/{id}/attributes/{attr}` | removes a claim the customer added. Refuses for a claim extracted from their own pages: that one is evidence, and excluding it from scoring is what its zero slider is for |

## Views

The page has two tabs, Onboard and History. Two committed examples ship with every clone:
`data/companies/5eed0001.json`, a real onboarding of notion.com with an example set of intent weights,
reopened from step 1 of Onboard; and `data/runs/cb67186167.json`, a real live run of amgen.com on
`gpt-6-luna` (28 Sep 2026; `data/companies/b5aced577f.json` its onboarding), listed in History and labelled as measured live
with its date. Opening that run asks no model; re-weighting it re-scores in the page but never
rewrites the committed file (`SHOWCASE_RUN` in `api/main.py`). On the hosted demo a visitor without a
pass cannot onboard, so the page opens on History; a pass holder sees neither example, only their own
work, starting on Onboard.

**First-visit guide** (`web/src/guide.tsx`; copy, memory and the story's picker in `web/src/tour.ts`).
Every first-time visitor opens on a welcome saying what the app is (about 8 s, time to read it). A
visitor without a pass on the hosted demo then sees a short "how it works" story: four scenes of about 3.6 s each, told with the showcase run's own words, never written into the code. The scenes
are a claim quoted from the company's site, a branded question with pieces of its answer, the
headline gap with one identity AI gave the company unasked, and the first Quick wins rewrite
(`tour.pickStory`). The story plays only from a run measured live that has all four, and shows where
each quote came from. Its last button opens that report, and a five-step spotlight tour takes over:
the headline, buyer visibility, the claim groups, the Questions tab, and Quick wins, which the last
step opens. A pass holder, who cannot read the showcase run, gets the welcome alone, which hands over to three steps
on Onboard (the name form, the optional weights, the measuring stages); the report tour follows on
their first finished report. Each part starts on its own once per browser
(`localStorage["offmessage.tour.v1"]`; blocked storage means once per page load). Skip, Esc or
finishing ends a part; skipping the story skips the report tour too, and skipping the welcome alone
skips the tour it hands over to. **How it works** in the top bar replays it: the story when the
showcase run can be read, else the welcome followed by the report tour on an open report or the
Onboard tour, switching to that tab first. Captions fill in the open report's own numbers, and a step whose element or
number is missing is left out. Invented terms open their `glossary.ts` definition. The caption is a
bottom sheet on a phone; ← → move, Esc skips, and Tab stays inside the caption. Under reduced
motion the story is a still strip of all five scenes and the spotlight jumps instead of sliding.
Tests: `web/src/tour.test.ts`.

- **Onboard your own company** — one workflow on one screen, seven stages that complete in order:
  find the company and read its pages (from its name, confirmed by the customer, or a website
  typed; "Onboarding" above), which reads the homepage and up to seven same-site pages chosen by what they are — about,
  mission and values, what it offers, "why us", the newsroom's own page, then customers, pricing,
  enterprise — from the homepage's links and their words, topped up from `/sitemap.xml`; never a
  story, blog post, campaign, careers or legal page: `fetching.positioning_links`), extract what they
  claim (claims kept, each with its verbatim quote — matched with case, apostrophes, quotation marks,
  dashes and spacing forgiven, stored as the page spells it — and page count, and a "How we checked
  these claims" panel listing each extracted claim once: left out because no quote was found on
  their pages, left out for another reason, or kept with some quotes removed; a claim whose
  statement leans on marketing words is never dropped for them: it is kept, measured and marked
  "Needs your review", and the customer keeps it or sets it aside, and can restore one set aside), optionally choose what you want to be known for (one compact
  step asking three plain questions: what the company's own pages say, with the first note from
  reading them in amber and the rest folded; which claims you want to be known for, each a
  zero-floor slider whose value reads in words — Not a goal (0), Nice to have (under 0.5), Important
  (under 0.9), Top priority — over the same 0–1 weight, its page count opening to the quote, and the
  add-your-own row folded under them; and what a buyer would call what you sell, the core category.
  "How we checked" folds the claim checks and the site check into one row, and Save and Measure sit in
  a bar pinned to the bottom of the step), ask buyer questions, ask brand questions, follow up on products AI named, and
  score. Each stage is driven by the stream's events, shows what it actually did, and lists every
  answer as it arrives; a finished stage folds to a one-line summary. The report appears beneath
  the stages when scoring finishes. Previously onboarded companies can be reopened from step 1
- **Report** (inline after a run, and from History) — a product view, not one long page. A summary
  at the top: the company's own website icon beside its name (captured
  at onboarding from the homepage already fetched: `apple-touch-icon`, then any icon link, then
  `/favicon.ico`, stored as `profile.logo_url`; the first letter in a coloured square when there is
  none or it fails to load — never an external logo service), the run date and whether it was
  measured live or is a sample, the headline framed as upside — **untapped potential** (100 minus
  the score) with the real score beside it ("AI says 21.4% of what you want to be known for
  today") in its own card with the count of quick wins, which opens that tab — and buyer visibility
  in a second card. On a live run that card shows **Where AI places you** and **Where you aim to be**
  as two numbered markers on one 0–100 line, the likely range shaded and the gap between them dashed
  (a picture only: the rows beneath carry every number in words), then a row per front with its
  category, one plain sentence on what it is ("The category AI's own answers about Amgen put it in";
  "The category your own homepage puts you in"), its score, range and an amber **Low confidence**
  chip whose hover gives the reason, a short gap sentence ending in whether the gap is real, and a
  "What does low confidence mean here?" expander with each front's control-question result. Then
  **Download summary (PDF)**. The summary scrolls with the page; once it is out of view one line pins
  above the tabs (the headline and each front's visibility), so a phone keeps its screen.
  Below it, five tabs, each badge saying what it counts in words ("3 claims", "31 questions") and
  never a bare 0 (`web/src/badge.ts`: a tick where nothing is left to fix, else no badge;
  `role=tablist`, arrow keys, Home/End; the tab is kept in the URL
  hash, so `#report-questions` opens Questions we asked AI, and the old `#report-buyer` and
  `#report-brand` links land there too; on a phone the strip scrolls sideways; the tabs are pills,
  the active one solid accent with white text, and on a report's first view the others hop in a wave
  twice, stopped by the first tab click, never under reduced motion):
  - **Overview** — where the answers came from (measured live with the model, or the SYNTHETIC
    DEMO banner for a replayed run), what the figures mean, then one **chip per zone** with its
    count (an empty zone is greyed). Hovering, tapping or focusing a chip opens a popover listing
    that zone's claims — site share, AI share, the AI's own words, the questions that raised it,
    the site's verbatim quotes and, while it is a claim to win back or amplify, its fix — scrolling
    when there are many. When brand answers were left out, a plain-words box says how many the
    headline rests on, why each was left out (mirroring `scoring.eligible`) and that this can only
    flatter the score. Then the optional **weights** block, which calls `POST /api/runs/{id}/rescore`
    (no new AI calls; a 409 is shown in the server's words), and **How we checked this report**:
    counts derived from `drift.limitations` (answers counted and left out, answer readings dropped
    and why, possible new traits kept and rejected, sample size), each list behind
    a toggle. The workflow log is not on the page; it is in the run's JSON download.

    One popover (`web/src/popover.tsx`) serves every in-place explanation: any "Branded question 2"
    or "Unbranded question 7" reference opens the question, whether it counted and the AI's answer,
    with a link to its tab; every term the product invented (zone names, branded and unbranded question,
    untapped potential, buyer visibility, tries, low confidence…) has a dotted underline or ⓘ that
    opens its definition from `web/src/glossary.ts`, the one place those definitions live. Hover
    opens it on a desktop, a tap pins it, Enter moves focus into it, Esc closes it; on a phone it is
    a bottom sheet.
  - **Quick wins** (the tab once called Win it back; its badge and the summary's figure count the
    claims with room to grow: claims to win back plus claims to amplify) — the action plan: per claim,
    a new passage for one of the company's pages, headed by a buyer's own question and answering it in
    two or three factual sentences, why it should make AI name the company, and the buyer questions
    it is for (or when the proposer names none, the claim's own buyer questions that did not
    recommend them) — one evaluator-model call at the end of a live run over the saved answers and pages,
    authored and labelled sample in replay. `agents/win_back.py` drops any action whose page was
    not read, whose replaced copy is not verbatim on it, whose rewrite is marketing language, that
    gives no reason, whose heading is not one of the buyer questions it cites (a heading of its own is
    allowed only when it cites none, and then may not name the company or address the vendor) or is a
    buyer question AI already recommended the company for or whose answer was excluded, whose
    rewrite repeats more than half the words of the copy it replaces (Amgen, 2026-09-28: all three
    rewrites rephrased the sentence already on /about, and two matched their questions worse), or whose
    question was not asked, and says why in a plain sentence under "Suggestions we could not confirm";
    it moves no number. Each rewrite is a row that opens to **what changes** (a word diff when it
    replaces copy, else the new passage under its heading), **why this rewrite**, and a three-step
    **proof**: ① the match check, the retrieval scores of "Test a fix" per question it targets (today,
    the page AI cited, with the rewrite, and the change, where a move under 0.02 is no change);
    ② the **replay test** (`why.test_rewrite`, `GET /api/runs/{id}/rewrite-test/stream`): the buyer
    question asked live 3 times recording what the model read and 3 times with search off, the reading
    list replayed, then replayed with the rewrite on its page — leading it when the model read that
    page, added to the search results when it did not — 6, 18, then 36 times each, counting the gap
    the question has: whether the answer names the company (`why.NamesJudge`, the body only, as buyer
    visibility counts a mention), or, where the baseline answer named it without recommending it,
    whether it recommends it (`why.RecommendsJudge`, the run's evaluator, validated as a scored answer
    is), until the effect's corrected 95% interval decides it: proven (`copy_fix`), proven once
    the page is found (`authority_fix`), no change (`not_movable`), makes it worse (`copy_lowers`),
    not reproducible, or undecided, within `WHY_BUDGET_USD`. When the replays without the rewrite
    already name or recommend the company in more than four in five answers, no rise could show, and
    the verdict is `ceiling` ("Already at the top"), never a disproof; ③ the **live check**, "Mark fix live" on a
    proven rewrite (`verify.verify_investigation`), which reads the page first for free and only then
    asks live, kept on the investigation. One verdict line says what to do. A rewrite whose match check
    is worse on more of its questions than it is closer sits under "Rewrites we could not stand
    behind", with its reason; nothing is hidden. On Amgen (2026-09-30), the question-headed rewrites
    matched their buyer questions far better than the copy before them (0.55 → 0.84, 0.48 → 0.76), and
    the replay test still disproved both it ran: with the rewrite among what the model read, it named
    Amgen in 0 of 36 answers against 0 of 36 without it. A closer match is a reason to test, not proof.
    Then **where the upside is**: the biggest open claims
    as one compact table (claim, type, why when their diagnoses differ, site share, AI share, AI's own
    words), the shared diagnosis said once above it, each claim opening to all its evidence. On a live run it opens with **Investigate the gaps**
    (`web/src/fleet.tsx`, "Investigation fleet" above): a button with the fleet's estimate, then, as
    the fleet's log streams in, the coordinator's picks with its reasons (and any calls our code
    refused), one lane per investigator on one clock with its status, experiments, spend and verdict,
    the critic's challenge and what became of it (re-dispatched as a new try, or accepted), and the
    **tested plan**: ranked items, each with its fix, its line, the page, the prediction as "k/n
    against k/n in replays" with its interval, and on a tested fix **Mark fix live — re-check**,
    whose result sits under it with its live and replay numbers labelled apart. The panel folds the
    log (`web/src/fleetlog.ts`), so reopening the run replays it to the same place.
  - **Questions we asked AI** — second, because the questions are the evidence for every number:
    the **unbranded questions** (the code's buyer questions) and **branded questions** (its brand
    questions) side by side, each set in its own bordered frame (stacked on a narrow screen), what
    each set is and how it was asked folded behind "How these were asked". Every question is a card
    headed by its own text, with its verdict ("recommended you", "did not name you yet", the claims it
    raised; with several tries, "named in 2 of 3 tries") and who AI named instead; a card opens to
    the full answer (every try's, for an unbranded question) and the scorer's note. Unbranded
    questions are grouped by front, each group with its visibility and range, its
    questions and its **control question** with its answer and, when flagged, why the result is
    low confidence. A buyer row, and its question popover, also says what the model searched for
    it and whether any cited page was the brand's own. Every live answer opens to **What AI read**
    (`Answer.trace`, `live.reading_of`): each search with the snippets it returned, each page the
    model opened and the lines it looked up, in order, with the crawler's own date stamp. The
    Responses API returns them with the answer when asked (`include=["web_search_call.action.sources",
    "web_search_call.results"]`, `live.INCLUDE`), at no extra charge; a run keeps each result's first
    600 characters. Each front's header gives its rate of "named you" with its **margin** and how many
    of its frozen questions it took.
  - **Why AI misses you** — one headline (on how many buyer questions none of the pages AI cited was
    the company's), a summary card per reason (its searches don't reach you; your pages lose the match,
    with how the suggested rewrites moved; something in AI's way on the claim pages), then the detail
    on sub-tabs (`role=tablist`, arrow keys): What the AI searched, Test a fix, Site check, and Ask why
    (live), last because it spends. **Why AI says it** (the why agent, `why.py`, live runs only): pick a claim and a
    branded question — one of the run's, or your own that names the company and not the claim — and
    optionally a word that counts as saying it (otherwise the evaluator judges, quote verified, and
    counts what the report counts: only answers that endorse a claim of the company's, any mention of
    a perception AI raised; a literal word counts any mention). The
    agent asks it live 3 times recording what the model read, and 3 times with web search off (what
    the model already believes); replays the recorded reading list with search off, handed back as
    the web_search tool's own output, and stops unless the replay says the claim about as often as
    live did; then runs experiments on that reading list: remove every page that says it, bisect
    them, remove only the lines that say it; for a claim the company makes, lead a page AI already
    read with the run's win-back rewrite, or without one the site's own quote of the claim (copy), and add the company's page that states it where
    search never returned it (authority; with no such page, the rewrite's page carrying the
    rewrite). Each experiment is re-asked 6, 18, then 36 times until its effect's 95% interval —
    widened for every look and every experiment (`why.Z`) — excludes zero, or sits inside ±20 points. The claim card says what AI says, whether it believes it, what causes it
    (down to the lines), the tested fix with its predicted rate, and every experiment's effect.
    There is one card per claim and question: asking again gives a fresh result, since what AI reads
    changes, so the newest leads and earlier ones fold under it (`web/src/investigations.ts`). A
    media-library file or download the model read (`/-/media/`, `/static-files/`, a PDF or `.ashx`;
    `why.is_asset`) can be a cause and is named as a document, but it is never a page to put a
    rewrite on or to add.
    Replays are provenance `counterfactual_replay` and never reach a score; any copy that is not a
    page's own verbatim text is labelled hypothetical. Every call is metered; an investigation stops
    at `WHY_BUDGET_USD`.
    On Amgen (2026-09-28) it traced "debt" to two lines of the company's Q2-2026 earnings release and
    showed the "AI in R&D" rewrite on /about taking the claim from 6/18 to 14/18 answers.
    **What the AI searched** (`insights.searches`): the web searches the measured model
    ran for the buyer questions (every try), read from the Responses API's `web_search_call` items
    into `Answer.searches` and grouped when they differ only by case, a year or punctuation; one
    question told as a sentence, then the buyer questions grouped under where AI places you, where
    you aim to be and your claims, each with how many searches it ran and whether any answer to it
    cited the brand's own page, opening to its searches; "Show all searches as one list" gives each
    search with the questions it came from and the pages cited in those answers, the brand's own marked. The API does not say which search found which
    page, so pages belong to the answer. Runs saved before searches were kept say "not recorded";
    the bundled samples carry authored searches, labelled sample, that move no score.
    **Can AI read your site?** says the problems first — each failing check once, with how many
    claim pages it fails on, and the checks every page passes — then each advice line once with how
    many pages it is for, then one grid, a mark per check for each claim's page (AI crawlers, text
    without JavaScript, structured data, headings, speed), in amber and green text rather than filled
    red and green pills. The page
    checked is the first that states the claim and AI can read; any other page that states it but
    blocks an AI crawler or is an empty script shell is listed under the claim as advice ("It is also on
    /pricing, but robots.txt blocks GPTBot there"), never as a failure. Headings pass on a main
    heading plus subheadings; phrasing one as a buyer's question is advice too. Then the whole site
    (llms.txt, pages without JavaScript) and **where AI gets its facts** (Wikipedia, Wikidata,
    Crunchbase, G2, LinkedIn: found, not found or not checked). Every mark opens its reason, the
    page checked and what the check means; Wikipedia and Wikidata show their own short description
    beside the site's one-liner, and a Crunchbase, G2 or LinkedIn profile the site does not link
    is "not checked", with a one-tap search link to look by hand. It is the audit the run carried; runs from before it
    say so. The same section, closed, sits on the claims step with **Check again**. The onboarding
    crawler never ran JavaScript, so a quote it kept was in the plain HTML by construction: the
    JavaScript mark says whether it still is, and near-empty shells (under 100 characters of text,
    filled in by inline script or script files) are flagged; a short page with an analytics tag is not.
    **Test a fix** (`run.retrieval`, `retrieval.py`): a mini version of how an AI search picks what
    to read. After scoring, the brand's pages (fetched again, with the onboarding text as fallback)
    and the pages AI cited for each buyer question (up to 10, most-cited first, robots.txt respected,
    5 s timeouts) are split into 80–150-word passages on heading and paragraph boundaries, embedded
    with `text-embedding-3-small` (`embeddings.py`: metered, cached on disk by text hash) and scored
    by cosine similarity against the question and its fan-out searches. Per question: your best
    passage, the best passage of a page AI cited, and — where a "Quick wins" fix targets the
    question — the rewrite spliced into its page (in place of the copy it replaces, else as a new
    passage) and scored again: one table, rows with a fix first, a Result column in words ("Rewrite:
    worse", "Cited page matches better"); open a question for the passages. Every number is labelled a
    **retrieval score**, a similarity-based simulation, never a guarantee of citation, and moves no
    score. On a live run, "Quick check: 1 ask, not proof" asks the buyer question once with the
    rewritten passage and the cited page as the only sources and says whether the brand is named:
    one metered call, off until pressed, refused without a pass. Pages not read are listed with the
    reason. The bundled samples carry an authored sample, labelled as such. Overview gets one line
    on the biggest fixable gap.
  - **Sources & rivals** — the **citation network**, headed by its finding ("AI cited 6 sites
    beside your rivals, never beside Notion"; collapsed on a phone): the third-party sites (not the
    brand's or a rival's own — a rival's own site is recognised from its name, whole, first or last
    word, or initials, so jnj.com and innovativemedicine.jnj.com are Johnson & Johnson's:
    `insights.domain_keys`) cited in counted buyer answers that named a rival and never mentioned the brand, ranked by buyer answers citing
    each then rivals beside it, each with its rivals' initials and opening in place to the answers
    that cited it; a citation map joining brands to the sites cited beside them (plain SVG, wide
    screens only); and every cited site with its type (own, rival's, review, community, media,
    other — `insights.source_kind`, a short site list plus the address) behind a toggle. It reuses
    the saved citations; no model call. Then **share of voice** (answers recommending the brand beside the three
    most-recommended competitors, on the buyer questions that count; a tie for first beyond those
    three is counted in the headline, "A, B, C and 2 others 3 each"), the **positioning map**
    (`run.positioning`, `positioning.py`: the brand as its brand answers describe it, where it
    wants to be (the claims weighted, by weight) or, with no weights, where its site aims (its
    positioning points), and up to six rivals as the buyer-answer sentences naming them describe
    them, each the mean embedding of its sentences; a rival named as a division of another it names
    ("Johnson & Johnson Innovative Medicine" beside "Johnson & Johnson", "Merck & Co." beside
    "Merck") counts as that company only when the rest of its name is a known division or legal
    suffix, so "Merck KGaA" stays apart from "Merck"; a trailing "(qualifier)" is dropped, and "X and
    Y" is two companies when either is also named alone and neither is such a suffix (`evaluation.merge_divisions`). Each axis is one of the company's own claims, so it is always
    named, in the chart above and below the plot: across, how strongly a dot's sentences talk
    about the claim weighted highest (with no weights, the one the dots spread along most); up, the
    claim the dots differ on most once the first is taken out. Every dot carries its own full name
    (`web/src/maplabels.ts`: measured widths, dots on top of each other drawn a little apart, a
    leader line when a label sits apart, never a bare number or a cut name; `npm test` checks it); an arrow is
    the drift, and every dot opens its sentences. A similarity picture that moves no score; a
    re-score redraws it from cached embeddings only, else keeps the old map with a note; the
    samples carry hand-placed points and named axis ends, labelled as such), **who AI named instead**
    (every company named in a buyer answer that counts, beside the line that names it — the first
    three shown, the rest behind a toggle — plus the round-two comparison question) and **discovered identities** (cards that open the same claim popover).

  Every n/a shows the server's reason from `na_reasons`. Two lenses: with
  no weight set the report reads through the **claim lens** — buyer questions go to the claims
  stated on the most pages, **claim echo** (of what the site claims, weighted by pages stating it,
  how much AI repeats supportively) is the headline, and alignment is absent with its reason in
  `drift.na_reasons`. Once weights exist the **intent lens** makes alignment the headline and adds
  the unstated-intent messaging gap. **Unprioritised** is an intent-lens zone for a claim the
  company's own pages state and AI repeats, but which the customer did not weight. Zone keys and
  numbers never change; `web/src/labels.ts` only speaks them (`lost_claim` → "claim to win back",
  `contested` → "claim to correct", `unstated_intent` → "claim to amplify", `imposed` → "identity
  to shape"). **Download summary (PDF)** opens the browser's print dialog on a
  one-page executive summary (logo, untapped potential with the real score beneath, top 3 landed
  claims, top 3 claims to win back / correct / amplify / shape, run date and live-vs-sample source);
  "Save as PDF" makes the file. It is print CSS over a view that never renders on screen — no PDF
  library, no server call (`screenshots/exec-summary-pdf.png`)
- **History** — every saved run from `data/runs/` (under `DATA_DIR` when set; a pass holder's own
  runs only), under one line saying what a run is. Each row shows its company, whether it was
  measured live or is a sample, and its untapped potential. The column headings open their glossary
  definitions, and "Open report →" (or a click on the row) opens the report in place. On a phone
  each run is a card

Saving weights on the reopened Notion company — or measuring, which saves them first — writes to the committed
seed file, so the working tree shows it modified afterwards; `git checkout data/companies/5eed0001.json`
restores the example weights.

## Wording

No engine identifier is the only name a reader gets: where a raw id is still shown for traceability
it follows the words it stands for, as in "Unbranded question 3 — Project tracking (`pt-3`)".
`web/src/labels.ts` names everything the browser holds (probe ids, run ids, provenance, probe kinds);
`labels.py` names the ids the engine bakes into strings it hands over whole (exclusion reasons, the
follow-up rationale, gap findings).
Change a word in one of those label modules, not in a component. The ids themselves are untouched — the
JSON export, `data/runs/` and the baseline hash are exactly what they were.

## Deploy to Render

[`render.yaml`](render.yaml) deploys the app as one paid web service with a persistent disk: the
`Dockerfile` builds the web app and FastAPI serves it with the API on the same origin. It sets
`VISEXP_PUBLIC_DEMO=1`, so a visitor **without a pass** gets History only: the two bundled Notion
sample runs and the committed Amgen live run — no model calls, no cost. Live runs, onboarding and
company edits are refused with a message saying so. The saved reports in History can be re-scored,
and that is not saved, so one visitor cannot change what the next one sees. The two bundled scenarios
are replayed once at startup so History is not empty.

**Access passes** let chosen people run it live on your OpenAI key. Each pass has a name, a dollar
cap and a personal link, `<site>/?pass=<code>`. Opening the link signs the browser in (an HttpOnly
session cookie; the code leaves the address bar), after which the holder can onboard and measure
companies live, sees a meter such as "$1.40 of $5.00 used", and sees only their own runs and companies
— nobody else's, and none of the preloaded examples: the Notion company, the Amgen report and the
sample runs are hidden, so the page opens on "Onboard your own company". Every run a pass makes,
replay or live, is saved under `DATA_DIR` and owned by that pass, so it is back in History after a
restart, a redeploy onto the same disk, or a new browser opened with the same link. Every OpenAI call is checked against the cap before it is
made and charged afterwards from the usage OpenAI reports, at the dated per-model prices in
[`access.py`](access.py); a call whose usage or model price is unknown is charged a deliberately high
estimate, never zero. A run or onboarding that reaches the cap stops with a message and saves nothing.

- **Admin**: `<site>/admin`, behind `ADMIN_PASSWORD`. It lists every pass — spent against cap, runs and
  companies, first and last visit — and a log of recent visits (pass name, event, time; no IP
  address). Create a pass with a name and cap, **Generate link** (the link stays in its row with a
  **Copy link** button), **Regenerate link** (the old link and every session opened with it stop
  working), **Set cap** to top up, **Revoke** to switch a pass off. A pass made before links were kept
  shows "link hidden - regenerate to see it".
- **Names**: [`passes.json`](passes.json) seeds `person 1` … `person 5` at $5 each. Edit a `label` there
  and redeploy to rename someone; keep the `id`. A file's cap applies only when its pass is first
  created — after that the admin page owns the cap. Seeding never deletes or resets a pass, so one
  made in the admin page survives restarts like a seeded one. Codes are never in the repo, only in
  the pass database on the disk.
- **Contact**: visitors without a pass, pass holders and a capped pass are all told to email
  `CONTACT_EMAIL` (default in [`access.py`](access.py)) for a link or a higher cap.

1. Sign in at [render.com](https://render.com) with GitHub.
2. **New → Blueprint**, pick this repository (grant Render access to it if it is not listed).
3. Render asks for the secrets `render.yaml` leaves blank: `OPENAI_API_KEY` and `ADMIN_PASSWORD` (a
   long one). `SESSION_SECRET` is generated for you; changing it signs every pass holder and the admin
   out. **Apply**; the first build takes a few minutes.
4. The Blueprint attaches a 1 GB persistent disk at `/var/data` and sets `DATA_DIR=/var/data`, so
   passes, spend, the visit log, runs and companies — every pass holder's History — survive a redeploy. A disk needs a paid instance
   (`plan: starter`), and a service with a disk cannot scale past one instance, which is what the pass
   database expects.
5. **Check your storage**: `<site>/api/health` must show `"storage": {"persistent": true, ...}`. If it
   is `false`, the admin page shows a red banner (and the startup log a warning) saying why: passes
   and every pass holder's runs then vanish on the next deploy. Fix it by giving the service a disk (Settings → Disks) and setting
   `DATA_DIR` to exactly that disk's mount path, e.g. `/var/data`.
6. Open `<site>/admin`, sign in, and **Generate link** for each person.

**Tuning a live run**: set the variables in [Live mode](#live-mode) under Render → the service →
Environment. Every one has a working default.

`<site>/api/health` shows what is actually in force: `measured_model`, `evaluator_model`,
`search_mode`, `forced_search`, `target_margin`, `looks`, `buyer_questions`, `max_buyer_questions`, `wobble_audit`,
`run_budget_usd`, `why_budget_usd`, `live_concurrency`, `fleet_budget_usd`, `fleet_concurrency` and `verify_budget_usd`. If OpenAI
refuses the configured model or the live-search tool, the one preflight call steps down to
`gpt-5-nano` — and, if that will not search either, to no search at all, with every answer marked
ungrounded. It never substitutes a third model. `model_fallback` then says why, in the same words
the run log and the report's caveats carry.

Use a **separate OpenAI key for this demo**, in its own OpenAI project with a monthly budget set, as
a backstop: the caps here are enforced by this app, and a budget on the key holds even if something
here were wrong. Up to three calls of one run are in flight at once, so a pass can end a few cents
over its cap.

Check the production build locally first:

```bash
(cd web && npm ci && VITE_API= npm run build)
VISEXP_PUBLIC_DEMO=1 SESSION_SECRET=dev ADMIN_PASSWORD=dev DATA_DIR=/tmp/vd python -m uvicorn api.main:app --port 8000
curl localhost:8000/ && curl localhost:8000/api/companies
```

## Not done yet

- The onboard screen does not show the brand questions it will ask. Showing them would fit this
  product's habit of showing its work, and is worth doing deliberately rather than as a payload
  field nothing renders — `agents.onboarding.named_probes_for` already produces them
- No tests for the React app itself. `tests/test_api_stream.py` runs each bundled scenario end to end
  through the event stream the app consumes, which is the journey coverage the repository has;
  `tests/test_api_seed.py` covers the preloaded company, its offline fallback and the onboarding
  stream's event order; `tests/test_api_http.py` covers the API over HTTP (health, runs, companies,
  the PATCH intent rules, and that the key appears in no response)
- Report-surface attribute descriptions still render nothing: `AttributeScore` carries no
  `description` field. The onboarding task added `claim_pages`/`claim_pages_total` there but left
  this one open
- `/api/onboard` and `PATCH /api/companies/{id}` are unauthenticated, like the rest of the API
- Three.js 3-axis drift visual (deferred deliberately; the three layers are literally three axes)
