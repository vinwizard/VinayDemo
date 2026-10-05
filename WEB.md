# Web frontend (React + FastAPI)

The product UI. The Python engine — `graph.py`, `drift.py`, `agents/`, `scoring.py` and the fixtures —
is imported, not reimplemented. The API runs the graph on a worker thread and pushes an SSE event per
**answer** as well as per node, so the browser sees progress while a long batch is still running.

## Run it

Setup and the two commands are in [`README.md`](README.md#run-locally). Open **http://localhost:5173** —
not `127.0.0.1:5173`: Vite binds IPv6 localhost and the numeric address is refused. The browser calls
the API on port 8000 unless `VITE_API` says otherwise — useful beside a second checkout:

```bash
VITE_API=http://127.0.0.1:8731 npx vite --port 5731   # with the API started on --port 8731
```

### Why not `conda activate`

`conda activate` is a shell function from `~/.zshrc`, so it fails with `command not found: conda` in a
non-interactive shell, a script or an editor's terminal. Call the env's binaries by path instead:

```bash
~/miniconda3/envs/visexp/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
cd web && export PATH="$HOME/miniconda3/envs/visexp/bin:$PATH" && npm run dev   # npm's shebang needs node on PATH
```

### Live mode

Put your key in `.env` at the repo root (gitignored, never committed):

```
OPENAI_API_KEY=sk-...
```

Everything else has a working default. The full list, and what each one changes:

| Variable | Default | What it does |
| --- | --- | --- |
| `OPENAI_API_KEY` | — | The only required one. Without it live mode errors rather than replaying fixtures. |
| `MEASURED_MODEL` | `gpt-6-luna` | The model that ANSWERS the buyer and brand questions: the one being measured. It must accept the Responses API `web_search` tool. |
| `EVALUATOR_MODEL` | `gpt-6-luna` | The separate model that grades those answers, sent no tools. On the same model as the measured side it grades its own answers (`same_model_warning`); set another (`gpt-4.1-mini` is the tested one) to remove that self-preference bias. |
| `ONBOARDING_MODEL` | `gpt-4.1-mini` | Reads a company's own pages and extracts what they claim, and writes buyer questions for a category. |
| `TARGET_MARGIN` | `20` | The margin each buyer front aims for, in points of "named you", at 95% (`sampler.py`): how many questions a front freezes and asks. Clamped to 5–50. |
| `RUN_BUDGET_USD` | unset | The most one run's measured calls may spend. A front whose look 2 would pass it stops at look 1, and its margin is reported as not met. |
| `LIVE_CONCURRENCY` | `16` | How many measured asks the whole server has in flight, every run together (`dispatch.py`). |
| `WOBBLE_AUDIT` | `1` | How many times each front's first question is asked again, to show how much one question wobbles. `0` turns it off. |
| `WHY_BUDGET_USD` | `0.60` | The most one why investigation may spend (`why.py`); it stops there and says how far it got. |
| `FLEET_BUDGET_USD` | `3.00` | The most one investigation fleet may spend, every agent together (`fleet.py`). |
| `FLEET_CONCURRENCY` | `3` | How many of a fleet's investigators run at once (1–6). |
| `VERIFY_BUDGET_USD` | `0.75` | The most one re-check of a fix may spend (`verify.py`). An unpublished fix costs nothing. |
| `DATA_DIR` | bundled `data/` | Where runs, companies and the access database are kept. On Render, the mount path of a disk, or a redeploy wipes them. |
| `VISEXP_PUBLIC_DEMO` | unset | Hosted demo: saved replays for everyone, live runs only for a pass holder. |
| `SESSION_SECRET`, `ADMIN_PASSWORD`, `CONTACT_EMAIL` | — | Access passes and the admin page: "Deploy to Render" below. |
| `VISEXP_OFFLINE_REPLAY` | unset | Measuring the preloaded company replays the bundled sample instead of calling a model. |
| `VISEXP_DEV_DELAY` | `0` | Development only: seconds of pause per replayed answer, to watch the stages move. |

`/api/health` shows what is actually in force: `measured_model`, `evaluator_model`, `forced_search`,
`target_margin`, `looks`, `buyer_questions` (the questions a front freezes), `max_buyer_questions` (the
most a run may plan), `wobble_audit`, `run_budget_usd`, `why_budget_usd`, `live_concurrency`,
`fleet_budget_usd`, `fleet_concurrency` and `verify_budget_usd`, plus `configured_measured_model`,
`search_mode` and `model_fallback` when a step-down happened. Every live report names both models.

Any model you point `MEASURED_MODEL` or `EVALUATOR_MODEL` at should be in `access.PRICES`, or the
spend meter charges it `UNKNOWN_PRICE` — deliberately above every listed model, so a pass is never
under-charged for a model nobody priced.

Web search, not tokens, is most of a live bill, so the **number of answers** is the cost lever and
`TARGET_MARGIN` is the dial that moves it.

Restart the API after editing `.env`; it prints the names it loaded, never the values. Check
`/api/health` for `"live_available": true`. There is no mode switch in the page: every measurement it
starts is live.

A live run asks every brand question once and, beside them, the buyer questions on where the company
aims to be; the buyer questions on where AI places it are planned the moment the brand answers are
read. The evaluator grades each answer, a round-two comparison question follows when a buyer answer
names a competitor, and one evaluator call at the end writes the action plan. Without a key, live mode
**errors** rather than falling back to fixtures — a fixture result under a live label would be a
fabricated measurement.

Asks run side by side (`graph.Asks`, `dispatch.py`), but the run is written only by the graph, in one
fixed order (`graph.canonical`), so a saved run never depends on which answer came back first. Under
concurrency a pass's cap counts the estimated cost of its calls under way (`access.start`), so a pass
stops about one call past its cap.

**Why a run takes the time it does.** A run is a chain of stages, each as slow as its slowest ask:
the brand questions, the discovery call over their answers, the placed front, its look 2, the
comparison question, the action plan. The judge grades each answer on the worker that fetched it
(`LiveProvider._labelled`). Both models think at reasoning effort "low" (`live.REASONING`): on
2026-10-01 that took a live Amgen run from 211 s and $0.77 to 87 s and $0.41. The measurements behind
that choice, and the settings rejected, are in the comments at `live.REASONING` and
`evaluator_model.DEFAULT_MODEL`.

Before a live run the API makes one trivial preflight call, so a broken setup fails once with one
message rather than once per question. It is classified on the HTTP status, never the error text: a
401 means OpenAI refused the key, a 403 is an account-level refusal (most often OpenAI not serving
your region), and only a 400 means the model will not take the web_search tool — set
`MEASURED_MODEL`. The provider's response body is never shown, because a 401 body quotes part of the
key back.

**Search is required, not offered** (`live.TOOL_CHOICE`, `live.SEARCH_TOOL`): an answer written from
memory is excluded from live scores (`scoring.eligible`), so a response with no `web_search_call` is
asked once more, and kept as ungrounded if it still did not search.

**If OpenAI refuses that pair, preflight steps down — never silently**: to `live.FALLBACK_MODEL`
(`gpt-5-nano`) with plain `web_search`, then to `gpt-5-nano` with no tool, where every answer is
ungrounded and excluded. Only a 400 steps down. There is no third model. The judge follows only when
it is on the refused model. `model_fallback` gives the reason, as do the run log and the report's
limitations.

#### Why a rerun gives a different number, and what the report does about it

The measured model answers the same question differently every time, so visibility moves between
runs without anything about the company changing. What keeps the buyer number trustworthy:

- **Two fronts, side by side** (`graph.plan_aiming`, `graph.perceive`, `graph.plan_buyer`):
  **where you aim to be**, the site's core category (`profile.core_category`, correctable on the
  claims screen), and **where AI places you**, the attribute the most valid brand answers endorsed
  (`ana.placed_attribute`; a `business` discovery about stock, revenue or size is never placed). Each
  front has its own visibility, wobble and control question (`DriftReport.sets`);
  `DriftReport.visibility_gap` is placed minus aiming. Each weighted claim adds a topic of its own
  buyer questions. One category, or one missing front, is said in the run
  (`ana.same_category`, `DriftReport.missing_fronts`).
- **Real demand first** (`demand.py`): live runs ask Google autocomplete phrasings, grouped by meaning,
  exactly as people typed them, marked "real demand"; written questions fill the rest, and
  `run.demand_notes` says why when none were usable.
- **Fresh questions until the margin is met** (`sampler.py`). Re-asks of one question are stored in
  `run.repeat_answers`, so everything else reads the first try; visibility is the mean over
  **questions** (`scoring.visibility_by_question`). A replayed sample has no sampler and no wobble.
- **Every number says how sure it is.** `scoring` bootstraps a 95% interval (fixed seed, so a saved
  run always shows the same one) from `MIN_INTERVAL_ANSWERS` scored questions or answers up; below
  that, or with nothing re-asked, `na_reasons` says why. The gap between fronts is bootstrapped draw
  by draw (`gap_verdict`): "The gap is real, 95% confident", "Not distinguishable with this sample",
  or "Too few questions to call the gap".
- **A control question checks what a front's number means.** "Which companies lead in
  <category>?" is asked once a front and never scored; `scoring.low_confidence` flags the front
  **low confidence** with the reason, and a flagged number is never shown bare.
- **A generic phrase is never the brand's name** (`schemas.distinctive_alias`): matching is
  word-bounded and case-sensitive, and an alias made only of generic nouns does not count.

### Answer reuse

`sharing.py` and `LiveProvider.plan_reuse` own the rules: a fresh grounded live answer is reused for
24 hours by a later run asking the same question, or a buyer question at cosine `sharing.SIMILARITY`
or more, in the same mode; the labels are made again and the report says "reused from <time>".
Another pass's answer is reused only for a buyer question the app wrote. **Fresh run** (the checkbox
by Measure, `?fresh=true`) reuses nothing. At most half a run's first asks are reused
(`sharing.MAX_SHARE`), each stored answer once a run, never within the run that asked it, and a
reused answer or wobble re-ask is never stored again, so no answer counts twice in a margin. The
threshold's calibration is beside `SIMILARITY`. Kept in `DATA_DIR/shared.db`.

### Investigation fleet

After a live run, **Investigate the gaps**, its own tab on the Evidence page, starts a team of agents that work out why AI
says what it says and what would change it (`fleet.py`, `verify.py`, `api/fleet.py`; the roles are in
`fleet.py`'s docstring). It reads the saved run and never writes it. The plan is code's ranking of the
accepted verdicts, every number copied from an experiment, in the template's wording.

Agents never call each other: they write typed `FleetEvent`s to one append-only log,
`DATA_DIR/fleets/<id>.jsonl`, which the page streams, resuming from the last event it saw. Every model
call of every agent goes through `access.openai_response` and draws on one `access.Purse`
(`FLEET_BUDGET_USD`) inside the pass that started the fleet; the pass cap still applies call by call.
Investigations are `counterfactual_replay` and never scored; a re-check's live asks are `live_api`
but kept in its `Verification`, never added to a run. A server restart mid-fleet marks it stopped and
keeps what finished.

Two live fleets on the committed Amgen run (2026-09-28): 6 investigations each, 8.4 and 9.6 minutes,
$0.98 and $1.25. The first found a copy fix for "biologic medicines"; the second, on the same
question, did not decide it — what AI reads changes between runs, so a plan is one fleet's reading.

### Offline fallback — no network, no key

For a demo on bad wifi, start the API with `VISEXP_OFFLINE_REPLAY=1`, then reopen Notion from the
Onboard tab ("Or reopen one you already onboarded"). Measuring the preloaded Notion company then
replays the bundled Notion sample (fixture scenario A) instead of asking a model. Nothing in the page
can turn this on, and only the preloaded company is affected — any other company still refuses
without a key. The run says what it is everywhere it appears (an "Offline replay" notice, a SAMPLE tag
on every answer, the SYNTHETIC DEMO banner); the reopened company shows the sample's own claims, its
sliders are locked, and the API refuses to edit it, so the committed seed file is never touched.

Add `VISEXP_DEV_DELAY=1` (seconds per replayed answer) to watch the stages move.

## Onboarding

Only the company's name is needed (`web/src/find.tsx`, `discovery.py`, `documents.py`; their
docstrings have the rules).

1. **Find.** One web search returns up to three companies the name could mean, each only from a
   domain a search result returned; the customer always confirms. A website typed under "I know the
   website" skips the search.
2. **Read.** The plain crawl (`fetching.fetch_site`) comes first. Under three pages
   (`MIN_DIRECT_PAGES`), one more search fills up with the company's own pages, read directly or as a
   dated **search copy**. There is no headless browser.
3. **What counts as claimed.** An own page is on the confirmed domain or a subdomain **and** names the
   company. Everything else that names it is **third-party** (`Company.third_party`, "Others about
   you"), never extracted or counted.
4. **Documents.** PDF (text layer only), .docx, text and Markdown, or pasted text; up to 5 files, 10 MB
   each. Only the text is kept, under the pass's own folder. A claim found only in documents is
   `private_only`: a **messaging gap** if AI does not repeat it, never an authority gap.

Every source keeps its kind (`Evidence.source_type`: `page_fetch`, `search_copy`,
`uploaded_document`). A fetch that fails says why in plain words (`fetching._plain`).

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | liveness, whether live mode is usable for this browser (`live_available`) and whether a key is set on the server at all (`key_configured` — on the public demo a visitor without a pass sees the second true and the first false, and the page asks them to open their pass link rather than reporting a missing key), and `seed_company` — the id of the preloaded company, `showcase` — the company and run ids of the committed live example in History, and `contact_email` — where to ask for a pass or a higher cap (`CONTACT_EMAIL`), and `storage` — whether the pass database survives a redeploy ("Deploy to Render" below); the live settings in force ("Live mode") |
| `GET /api/stream?company=<id>` or `?scenario=A&mode=demo` | `&fresh=true` reuses no earlier answer ("Answer reuse"). SSE while the graph runs: `node` (with `planned` question counts per stage, discovered `competitors` and the run `mode`), `answer` (the question, the first 320 characters of its answer, provenance and whether a web search ran), `done` (the full run), `error`. A company is always `mode=live`, apart from the offline fallback above. The page only ever measures companies; `?scenario=` remains for the fixture path |
| `GET /api/runs` | run history, newest first; each row's `mode` (`live_api` for a measured run) lets History mark it measured live or a sample. A saved file that cannot be read is named on the API console and counted in the `X-Unreadable-Files` header, which History says beside the list |
| `GET /api/runs/{id}` | one full run, including the drift report and its `insights` (share of voice, cited sources and the brands each was cited beside, searches); the stream's `done` event and `rescore` return the same shape |
| `POST /api/runs/{id}/reask` | test a fix: `{probe_id}` asks that buyer question once more, with the rewritten passage and the cited page's passage as the only sources, and saves whether the brand was named on its retrieval row. One metered model call; live runs only, refused on the public demo without a pass. A simulation that moves no score |
| `POST /api/runs/{id}/rescore` | lens 2 after the fact: `{weights: {id: 0..1}}` sets intent on a finished run and re-scores its saved answers — no provider is built and no model is asked. Unnamed weights keep their value; 0 unweights; with nothing weighted the run reads through the claim lens again. Saved in place, except in the public demo (`VISEXP_PUBLIC_DEMO`) and for the committed live example (`SHOWCASE_RUN`) |
| `GET /api/onboard/find?name=&hint=` | which company a name means: one web search, up to three `candidates` (`name`, `domain`, `what`, `exact`) and whether any is an exact match (`discovery.find`). The customer confirms one before anything is read; "No, it's a different company" asks again with a `hint`. Needs the key; refused on the public demo without a pass |
| `POST /api/onboard/documents?filename=` | one document as the raw request body (PDF, .docx, .txt, .md; 10 MB) → `{id, filename, chars}`. Only its text is kept, in the pass's own folder (`documents.py`); 413 when too large, 422 with the reason when it cannot be read |
| `GET /api/onboard/stream?url=&name=&docs=&only_docs=` | the same onboarding as SSE: `pages` (`pages`, the web URLs read, and `sources`, each with how it was read) as soon as everything is read, then `company` once extraction is saved, or `error`. The page uses this one |
| `GET /api/onboard?url=&name=&docs=&only_docs=` | Agent 1: read up to 8 of a company's own pages (`CRAWL_PAGES`; search copies when the site turns us away) and any uploaded documents (`docs`, comma-separated ids; `only_docs=true` skips the website), extract the **claimed** layer (attributes, verbatim quotes, derived page counts) and **save** the company. `url` may be empty when documents are given. Needs the same key as live mode. A company is always saved, never refused: one where fewer than three claims survive quote validation carries a prominent warning that it states too little for a reliable claim percentage, and the existing insufficient-evidence rules withhold the scores rather than the company. The company carries `sources` and `third_party` ("Onboarding" above) |
| `GET /api/companies` · `GET /api/companies/{id}` | onboarded companies, newest first, and one in full; unreadable files are counted in `X-Unreadable-Files`, as for runs |
| `PATCH /api/companies/{id}` | the customer's own input: `{weights: {id: 0..1}, added: [{label, description, intended_weight}]}`. Intent arrives only here (or on `rescore`) — never derived from their copy, and a weight of 0 leaves an extracted attribute unintended. Weights are optional: a company measured with none runs the claim lens. An **added** claim is intended by construction, so its weight cannot go below 0.1 |
| `POST /api/access/exchange` · `GET /api/access` | access passes on the hosted demo (`access.py`): `{code}` from a personal link `/?pass=<code>` becomes an HttpOnly session cookie; `GET` is the holder's meter (`{pass: {label, spent_usd, cap_usd, capped}}` or `{pass: null}`). With a pass, live runs and onboarding are allowed on the public demo, charged to the pass, every run it makes (replay or live) is saved under `DATA_DIR`, and runs and companies are listed only to the pass that made them — a pass sees none of the shared preloaded ones. `/admin` (behind `ADMIN_PASSWORD`) creates passes, shows each link once, and tops up or revokes. Cookies are same-origin, so passes work on the production build, not across the Vite dev port |
| `POST /api/companies/{id}/audit` | checks again whether AI can read the site (`audit.py`) and saves it on the company; the same check runs once during onboarding. Plain fetches, no model and no key. Anything that cannot be reached, or whose robots.txt turns automated tools away, is "could not check", never a guess. A company read from documents only is refused with 400. A run copies the company's audit when it starts |
| `GET /api/runs/{id}/why/stream?attribute=&probe=` or `&question=`, optional `&term=` | the why agent (`api/why.py`) as SSE: `start` (its budget), `log` lines, `done` (the investigation, saved under `DATA_DIR/investigations/`), `error`. Live runs only; refused on the public demo without a pass, without a key, or with a model that cannot search. The question must name the company and not the claim |
| `GET /api/runs/{id}/rewrite-test/stream?attribute=&probe=` | a Quick wins rewrite's **replay test** (`why.test_rewrite`): the same SSE events as the why agent, for the claim's rewrite against one buyer question it was written for. The investigation is saved with `kind: "buyer"` and `counts: "names"` or `"recommends"`. Refused as the why agent is, and for a question the rewrite was not written for |
| `GET /api/investigations/{id}/verify/stream` | "Mark fix live" on a rewrite its replay test proved (`verify.verify_investigation`): `log` lines, then `done` with the Verification, which is kept on the investigation. The page is read first, free; an unpublished rewrite asks nothing |
| `GET /api/runs/{id}/why` | a run's investigations (claims' and rewrites'), newest first. The run itself is never changed |
| `POST /api/runs/{id}/fleet` | starts an investigation fleet on a live run ("Investigation fleet" above) and returns `{id}` at once. Refused on the public demo without a pass, on a sample run, with nothing to investigate, while another fleet is running on the run, and without a model that can search |
| `GET /api/runs/{id}/fleets` | a run's fleets, newest first (`status`, `spent_usd`, `wall_s`), and what a new one would cost (`estimate`: shortlist size, picks, dollars, minutes) |
| `GET /api/fleets/{id}/stream?after=` | the fleet's log as SSE: one `fleet` event per `FleetEvent` (with its number as the SSE id, so a reconnect resumes after `after` or `Last-Event-ID`), then `end` once it is done |
| `GET /api/fleets/{id}/verify/stream?rank=` | re-checks plan item `rank` of a finished fleet: its `verify` and `verified` events as SSE (also kept on the log), then `end`. Only a tested copy or authority fix |
| `DELETE /api/companies/{id}/attributes/{attr}` | removes a claim the customer added. Refuses for a claim extracted from their own pages: that one is evidence, and excluding it from scoring is what its zero slider is for |

## Views

The page has two tabs, Onboard and History. Two committed examples ship with every clone:
`data/companies/5eed0001.json`, a real onboarding of notion.com with example intent weights, reopened
from step 1 of Onboard; and `data/runs/cb67186167.json`, a real live run of amgen.com (28 Sep 2026),
listed in History as measured live; `rescore` never rewrites the committed file (`SHOWCASE_RUN`).
On the hosted demo a visitor without a pass opens on History; a pass
holder lists only their own work, starting on Onboard, but can open the Amgen run the guide is told with.

Rules every view keeps: every simulation (retrieval scores, replays, reasks) is
labelled and moves no score; no engine id or 0 is the only thing a reader gets; every n/a shows its
reason from `na_reasons`; no external logo service (the logo is the site's own icon, else a letter).

- **First-visit guide** (`web/src/guide.tsx`, `web/src/tour.ts`, `web/src/guideBus.ts`, tests in
  `tour.test.ts`): a welcome and a four-scene "how it works" story told with the showcase run's own
  words (`tour.pickStory`), then a spotlight tour that lights up one block at a time, each anchored by
  `data-tour`: the Results blocks, on into the Evidence tabs and Investigate the gaps
  (`tour.REPORT_STEPS`); onboarding's six stages for a pass holder (`ONBOARD_STEPS`); and after a live
  result is generated, a short walk to Investigate with a worked example from that run
  (`INVESTIGATE_STEPS`, `tour.investigateExample`). Each part starts on its own once per browser;
  **How it works** in the top bar replays the story, or the tour of the screen when there is no story.
- **Onboard** (`web/src/find.tsx`, `claims.tsx`, `workflow.tsx`): find and read the company, review
  its claims with their verbatim quotes and "How we checked", weight what it wants to be known for and
  name its core category, then measure; each stage is driven by the stream's events and folds to a
  one-line summary.
- **Report** (`web/src/report/`): two pages kept in the URL hash (`#evidence`, `#evidence-<part>`
  picks the Evidence tab).
  The provenance pill, and on a sample run the SYNTHETIC banner, are always in view. One popover
  (`popover.tsx`) explains every question reference and every invented term, from `glossary.ts`, the
  one place definitions live; everything beyond the figures is behind one.
  - **Results** — six blocks, each figure animating in once: untapped potential (100 minus the score)
    with today's score, buyer visibility per front with its low-confidence badge (range, margin
    `margin.tsx` and gap on hover), the zone chips opening their claims, Quick wins with a diff
    teaser, Why AI misses you in three numbers, and share of voice.
  - **Evidence** — **Download summary (PDF)** (`print.tsx`: print CSS, no PDF library, no server call)
    and the run as JSON, then one tab per part, only that part shown (the one on show is solid violet):
    What we asked AI — every buyer and brand question with its verdict, answer, the control
    question per front and **What AI read** (`Answer.trace`, `live.reading_of`); What AI searched
    (`insights.searches`); Fixes and tests — the Quick wins plan (`agents/win_back.py`, `web/src/quickwins.ts`: per claim
    a question-headed passage, one verdict, one next step, its proof behind a disclosure) and Test a fix
    (`retrieval.py`); Site check (`audit.tsx`, `audit.py`); Cited sites and rivals — the citation network
    (`sources.tsx`, `insights.domain_keys`, `insights.source_kind`) and who AI named instead; How we
    checked (`drift.limitations`); and on a live run **Investigate the gaps** — what it does, told with
    the run's own Quick win, the fleet (`fleet.tsx`, `fleetlog.ts`) and the past why investigations,
    read-only (`why.tsx`).

  Two lenses: with no weight set the report reads through the **claim lens** (claim echo is the
  headline); once weights exist the **intent lens** makes alignment the headline. Zone keys never
  change; `web/src/labels.ts` only speaks them.
- **History** (`web/src/report/history.tsx`) — every saved run from `data/runs/` (a pass holder's own
  only), opening the report in place.

Saving weights on the reopened Notion company — or measuring, which saves them first — writes to the committed
seed file; `git checkout data/companies/5eed0001.json` restores the example weights.

## Wording

No engine identifier is the only name a reader gets: where a raw id is still shown for traceability
it follows the words it stands for, as in "Unbranded question 3 — Project tracking (`pt-3`)".
`web/src/labels.ts` names everything the browser holds (probe ids, run ids, provenance, probe kinds);
`labels.py` names the ids the engine bakes into strings it hands over whole (exclusion reasons).
Change a word in one of those label modules, not in a component. The ids themselves are untouched — the
JSON export, `data/runs/` and the baseline hash are exactly what they were.

## Deploy to Render

[`render.yaml`](render.yaml) deploys the app as one paid web service with a persistent disk: the
`Dockerfile` builds the web app and FastAPI serves it with the API on the same origin. It sets
`VISEXP_PUBLIC_DEMO=1`, so a visitor **without a pass** gets History only: the two bundled Notion
sample runs and the committed Amgen live run — no model calls, no cost. Live runs, onboarding and
company edits are refused with a message saying so. A `rescore` there is not saved, so one visitor
cannot change what the next one sees. The two bundled scenarios
are replayed once at startup so History is not empty.

**Access passes** let chosen people run it live on your OpenAI key. Each pass has a name, a dollar
cap and a personal link, `<site>/?pass=<code>`. Opening the link signs the browser in (an HttpOnly
session cookie; the code leaves the address bar), after which the holder can onboard and measure
companies live, sees a meter such as "$1.40 of $5.00 used", and sees only their own runs and companies
— nobody else's, and none of the preloaded examples, except that the committed Amgen run (`SHOWCASE_RUN`)
opens for everyone, unlisted, since the first-visit guide is told with it (`api.main.sees_run`), and read-only: no pass investigates, re-asks or tests a fix on it. Every run a pass makes, replay or live, is saved
under `DATA_DIR` and owned by that pass. Every OpenAI call is checked against the cap before it is
made and charged afterwards from the usage OpenAI reports, at the dated per-model prices in
[`access.py`](access.py); a call whose usage or model price is unknown is charged a deliberately high
estimate, never zero. A run or onboarding that reaches the cap stops with a message and saves nothing.

- **Admin**: `<site>/admin`, behind `ADMIN_PASSWORD`. It lists every pass — spent against cap, runs and
  companies, first and last visit — and a log of recent visits (pass name, event, time; no IP
  address). Create a pass with a name and cap, **Generate link** (the link stays in its row with a
  **Copy link** button), **Regenerate link** (the old link and every session opened with it stop
  working), **Set cap** to top up, **Revoke** to switch a pass off.
- **Names**: [`passes.json`](passes.json) seeds `person 1` … `person 5` at $5 each. Edit a `label` there
  and redeploy to rename someone; keep the `id`. A file's cap applies only when its pass is first
  created — after that the admin page owns the cap. Seeding never deletes or resets a pass. Codes are
  never in the repo, only in the pass database on the disk.
- **Contact**: visitors without a pass, pass holders and a capped pass are all told to email
  `CONTACT_EMAIL` (default in [`access.py`](access.py)) for a link or a higher cap.

1. Sign in at [render.com](https://render.com) with GitHub.
2. **New → Blueprint**, pick this repository (grant Render access to it if it is not listed).
3. Render asks for the secrets `render.yaml` leaves blank: `OPENAI_API_KEY` and `ADMIN_PASSWORD` (a
   long one). `SESSION_SECRET` is generated for you; changing it signs every pass holder and the admin
   out. **Apply**; the first build takes a few minutes.
4. The Blueprint attaches a 1 GB persistent disk at `/var/data` and sets `DATA_DIR=/var/data`, so
   passes, spend, the visit log, runs and companies survive a redeploy. A disk needs a paid instance
   (`plan: starter`), and a service with a disk cannot scale past one instance, which is what the pass
   database expects.
5. **Check your storage**: `<site>/api/health` must show `"storage": {"persistent": true, ...}`. If it
   is `false`, the admin page shows a red banner (and the startup log a warning) saying why: passes
   and every pass holder's runs then vanish on the next deploy. Fix it by giving the service a disk (Settings → Disks) and setting
   `DATA_DIR` to exactly that disk's mount path, e.g. `/var/data`.
6. Open `<site>/admin`, sign in, and **Generate link** for each person.

**Tuning a live run**: set the variables in [Live mode](#live-mode) under Render → the service →
Environment; `/api/health` shows what is in force.

Use a **separate OpenAI key for this demo**, in its own OpenAI project with a monthly budget set, as
a backstop: the caps here are enforced by this app, and a budget on the key holds even if something
here were wrong. Up to `LIVE_CONCURRENCY` measured calls are in flight at once, so a pass can end a
little over its cap.

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
- Report-surface attribute descriptions still render nothing: `AttributeScore` carries no
  `description` field
- Three.js 3-axis drift visual (deferred deliberately; the three layers are literally three axes)
