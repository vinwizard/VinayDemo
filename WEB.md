# Web frontend (React + FastAPI)

The product UI. It replaced a Streamlit app, since deleted. The Python engine — `graph.py`,
`drift.py`, `agents/`, `scoring.py` and the fixtures — is imported, not reimplemented.

## Why not Streamlit

`st.status` can only render when a graph **node** returns. `execute_or_replay` answers the whole batch
inside one node call, so the page froze for the entire batch with no feedback — 24 seconds at 1s/answer,
and 50–130s with a real search-grounded provider.

The API runs the graph on a worker thread and pushes an SSE event per **answer** as well as per node.
Measured with `VISEXP_DEV_DELAY=1`, events arrive once per second throughout the batch instead of all at
the end. That is the whole reason for the move; Three.js and other rendering choices are irrelevant to it.

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
| `BUYER_QUESTIONS` | `12` | How many buyer questions are asked **per front**, once each. More distinct questions is what narrows the confidence interval; the two fronts together are the whole buyer budget. |
| `REPEAT_SAMPLE` | `2` | How many of those questions are also asked `BUYER_TRIES` times, to show how much one question wobbles between asks. `0` turns repeats off, and with them the wobble and the confidence interval. |
| `BUYER_TRIES` | `3` | How many times each **repeat-sampled** question is asked. Every other question is asked once. |
| `DATA_DIR` | bundled `data/` | Where runs, companies and the access database are kept. On Render, the mount path of a disk, or a redeploy wipes them. |
| `VISEXP_PUBLIC_DEMO` | unset | Hosted demo: saved replays for everyone, live runs only for a pass holder. |
| `SESSION_SECRET`, `ADMIN_PASSWORD`, `CONTACT_EMAIL` | — | Access passes and the admin page: README "Deploy to Render". |
| `VISEXP_OFFLINE_REPLAY` | unset | Measuring the preloaded company replays the bundled sample instead of calling a model. |

`MEASURED_MODEL` replaced `LIVE_MODEL`, which is no longer read: an old `.env` that still pins
`LIVE_MODEL=gpt-4o-mini` would otherwise have kept the model that named obscure tools for a category
leader's own category. Every live report names both models ("answered by gpt-6-luna, judged by
gpt-4.1-mini"); `/api/health` reports `measured_model`, `evaluator_model`, `forced_search`,
`buyer_questions`, `repeat_sample` and `buyer_tries`, plus `configured_measured_model`,
`search_mode` and `model_fallback` when a step-down happened.

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
At the default budget (about 39 measured answers) the same shape comes to roughly **$0.85** a run.
`BUYER_QUESTIONS` is therefore the dial that moves the bill, and the tool's `search_context_size`
is the one still untouched. The preflight call costs one forced search of its own (~$0.01): that is
the price of proving the exact request shape before spending a run on it.

Restart the API. It prints `[config] loaded from .env: OPENAI_API_KEY=<set>` — names only, never
values. Check `curl -s http://127.0.0.1:8000/api/health` for `"live_available": true`. There is no
mode switch in the page: every measurement it starts is live.

A live run asks every brand question once, then plans its buyer questions from those answers, and
asks each of them once to the measured model — `REPEAT_SAMPLE` of them `BUYER_TRIES` times — plus one
**control question** per front, and has the evaluator grade each
answer — two calls per ask — plus one round-two comparison question when a buyer answer names a
competitor, and one evaluator call at the end for the action plan. Without a key, live mode
**errors** rather than falling back to fixtures — a fixture result under a live label would be a
fabricated measurement.

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

- **Visibility is measured on two fronts, side by side.** Brand questions are answered and read
  first (`graph.plan_brand` → `perceive`), then `graph.plan_buyer` asks buyer questions about two
  categories, `BUYER_QUESTIONS` each (`ana.set_questions`):
  **where AI places you** — the attribute, claimed or discovered, that the most valid brand answers
  endorsed (`ana.placed_attribute`; ties go to the claim stated on more pages; its questions are the
  claim's own, topped up by the onboarding model) — and **where you aim to be**, the site's core
  category (`profile.core_category`, named at onboarding from the one-line description, blind
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
- **The budget goes on distinct questions, with a sample re-asked.** Every buyer question is asked
  once; `REPEAT_SAMPLE` of them (default 2, spread evenly through the plan order so each front
  contributes one — `graph.repeat_sampled`) are asked `BUYER_TRIES` times, each in a fresh context.
  Re-asking one question moves visibility by a few points while different questions disagree by
  tens, so questions — not tries — are what narrows the interval, and the same money buys a tighter
  number. Buyer visibility is the mean over **questions**, each question worth the mean of its own
  tries (`scoring.visibility_by_question`): a question asked three times still gets one vote, or the
  sample would drag the whole number towards whatever those two questions happen to say.
  The re-asked questions show how stable they were ("named in 2 of 3 tries") with every try's answer,
  and their per-try spread is the **wobble** (`drift.visibility_range`) — reported from that sample
  alone, and shown inside the number's popover rather than beside it, so the summary carries one
  range and not two. Brand questions are asked once. Extra asks are stored in `run.repeat_answers` /
  `repeat_evaluations`, so everything else — topic scores, sources, share of voice, the action plan —
  reads the first try exactly as before. A replayed sample has one authored answer per question, so
  nothing is re-asked, there is no wobble to show, and its numbers do not move.
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

### Offline fallback — no network, no key

For a demo on bad wifi, start the API with `VISEXP_OFFLINE_REPLAY=1`. Measuring the preloaded
Notion company then replays the bundled Notion sample (fixture scenario A) instead of asking a model.
Nothing in the page can turn this on; it lives only in the server's environment, and only the
preloaded company is affected — any other company still refuses without a key. The run says what it
is everywhere it appears: an "Offline replay — sample answers, not a measurement" notice above the
stages, a SAMPLE tag on every streamed answer, and the SYNTHETIC DEMO banner on its report and in
History. While it is on, the preloaded tab shows the sample's own claims in place of the real read of
notion.com, so what is on screen is exactly what is scored; its sliders are locked and the API
refuses to edit it, so the committed seed file is never touched.

To watch the stages move with a visible pause per answer, add `VISEXP_DEV_DELAY=1` (seconds per
replayed answer) to the same command:

```bash
VISEXP_OFFLINE_REPLAY=1 VISEXP_DEV_DELAY=1 ~/miniconda3/envs/visexp/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

`node` and `npm` come from the `visexp` conda env — nothing is installed system-wide.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | liveness, whether live mode is usable, and `seed_company` — the id of the preloaded company, `showcase` — the company and run ids of the preloaded Profound report, and `contact_email` — where to ask for a pass or a higher cap (`CONTACT_EMAIL`), and `storage` — whether the pass database survives a redeploy (README "Deploy to Render") |
| `GET /api/stream?company=<id>` or `?scenario=A&mode=demo` | SSE while the graph runs: `node` (with `planned` question counts per stage, discovered `competitors` and the run `mode`), `answer` (the question, the first 320 characters of its answer, provenance and whether a web search ran), `done` (the full run), `error`. A company is always `mode=live`, apart from the offline fallback above. The page only ever measures companies; `?scenario=` remains for the fixture path |
| `GET /api/runs` | run history, newest first |
| `GET /api/runs/{id}` | one full run, including the drift report and its `insights` (share of voice, cited sources and the brands each was cited beside, searches); the stream's `done` event and `rescore` return the same shape |
| `POST /api/runs/{id}/reask` | test a fix: `{probe_id}` asks that buyer question once more, with the rewritten passage and the cited page's passage as the only sources, and saves whether the brand was named on its retrieval row. One metered model call; live runs only, refused on the public demo without a pass. A simulation that moves no score |
| `POST /api/runs/{id}/rescore` | lens 2 after the fact: `{weights: {id: 0..1}}` sets intent on a finished run and re-scores its saved answers — no provider is built and no model is asked. Unnamed weights keep their value; 0 unweights; with nothing weighted the run reads through the claim lens again. Saved in place, except in the public demo (`VISEXP_PUBLIC_DEMO`) and for the committed Profound run |
| `GET /api/onboard/stream?url=&name=` | the same onboarding as SSE: `pages` (the URLs the crawl fetched) as soon as the crawl lands, then `company` once extraction is saved, or `error`. The page uses this one |
| `GET /api/onboard?url=&name=` | Agent 1: crawl up to 6 of a company's own pages, extract the **claimed** layer (attributes, verbatim quotes, derived page counts) and **save** the company. Needs the same key as live mode. A company is always saved, never refused: a site where fewer than three claims survive quote validation carries a prominent warning that it states too little for a reliable claim percentage, and the existing insufficient-evidence rules withhold the scores rather than the company |
| `GET /api/companies` · `GET /api/companies/{id}` | onboarded companies, newest first, and one in full |
| `PATCH /api/companies/{id}` | the customer's own input: `{weights: {id: 0..1}, added: [{label, description, intended_weight}]}`. Intent arrives only here (or on `rescore`) — never derived from their copy, and a weight of 0 leaves an extracted attribute unintended. Weights are optional: a company measured with none runs the claim lens. An **added** claim is intended by construction, so its weight cannot go below 0.1 |
| `POST /api/access/exchange` · `GET /api/access` | access passes on the hosted demo (`access.py`): `{code}` from a personal link `/?pass=<code>` becomes an HttpOnly session cookie; `GET` is the holder's meter (`{pass: {label, spent_usd, cap_usd, capped}}` or `{pass: null}`). With a pass, live runs and onboarding are allowed on the public demo, charged to the pass, and runs and companies are listed only to the pass that made them. `/admin` (behind `ADMIN_PASSWORD`) creates passes, shows each link once, and tops up or revokes. Cookies are same-origin, so passes work on the production build, not across the Vite dev port |
| `POST /api/companies/{id}/audit` | checks again whether AI can read the site (`audit.py`) and saves it on the company; the same check runs once during onboarding. Plain fetches, no model and no key: robots.txt for the AI crawlers, the claim's words in the no-JavaScript HTML, schema.org JSON-LD, headings, load time and llms.txt, on every page that states each claim, plus Wikidata/Wikipedia (tied to the company only by Wikidata's official website on its domain) and the Crunchbase, G2 and LinkedIn pages the site itself links to. Anything that cannot be reached, or whose robots.txt turns automated tools away, is "could not check", never a guess. A run copies the company's audit when it starts |
| `DELETE /api/companies/{id}/attributes/{attr}` | removes a claim the customer added. Refuses for a claim extracted from their own pages: that one is evidence, and excluding it from scoring is what its zero slider is for |

Comparison is done client-side from two `GET /api/runs/{id}` responses — no extra endpoint.

## Views

- **Notion** — the preloaded company. `data/companies/5eed0001.json` is a real onboarding of
  notion.com, committed so a fresh clone has it, with an example set of intent weights the page
  labels as an example rather than Notion's own. It is the same workflow as the next tab, starting at
  step 3
- **Profound** — the preloaded finished report. `data/runs/8d1d78c3e6.json` is a real live run of
  tryprofound.com (`data/companies/998420ffae.json` its onboarding), committed so every clone and the
  public demo open it straight away, labelled as measured live with its date. Opening it asks no
  model; re-weighting it re-scores in the page but never rewrites the committed file
  (`SHOWCASE_RUN` in `api/main.py`). It also appears in History and Compare
- **Onboard your own company** — one workflow on one screen, seven stages that complete in order:
  read their site (the pages fetched), extract what they claim (claims kept, each with its verbatim
  quote and page count, and a "How we checked these claims" panel listing each extracted claim once:
  left out because no quote was found on their pages, left out for another reason, or kept with some
  quotes removed), optionally choose what you want to be known for (the zero-floor intent
  sliders and the add-your-own row), ask buyer questions, ask brand questions, follow up on products AI named, and
  score. Each stage is driven by the stream's events, shows what it actually did, and lists every
  answer as it arrives; a finished stage folds to a one-line summary. The report appears beneath
  the stages when scoring finishes. Previously onboarded companies can be reopened from step 1
- **Report** (inline after a run, and from History) — a product view, not one long page. A summary
  pinned at the top while you move around: the company's own website icon beside its name (captured
  at onboarding from the homepage already fetched: `apple-touch-icon`, then any icon link, then
  `/favicon.ico`, stored as `profile.logo_url`; the first letter in a coloured square when there is
  none or it fails to load — never an external logo service), the run date and whether it was
  measured live or is a sample, the headline framed as upside — **untapped potential** (100 minus
  the score) with the real score beside it ("AI says 21.4% of what you want to be known for
  today") — buyer visibility (on a live run, side by side: **Where AI places you** and **Where you
  aim to be**, each with its category, range, 95% confidence interval and any low-confidence badge, then
  one plain gap sentence ending in whether the gap is real), the count of claims to win back, and **Download summary (PDF)**.
  Below it, five tabs, each badge saying what it counts in words ("3 claims", "31 questions") and
  never a bare 0 (`web/src/badge.ts`: a tick where nothing is left to fix, else no badge;
  `role=tablist`, arrow keys, Home/End; the tab is kept in the URL
  hash, so `#report-questions` opens Questions we asked AI, and the old `#report-buyer` and
  `#report-brand` links land there too; on a phone the strip scrolls sideways):
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
  - **Quick wins** (the tab once called Win it back; its badge and the pinned figure count the
    claims with room to grow: claims to win back plus claims to amplify) — the action plan (per claim, the page of theirs to
    change, a suggested rewrite and the buyer questions that did not recommend them which it should
    help with — one evaluator-model call at the end of a live run over the saved answers and pages,
    authored and labelled sample in replay; `agents/win_back.py` drops any action whose page was
    not read, whose replaced copy is not verbatim on it, whose rewrite is marketing language, or
    whose question was not asked, and says why in a plain sentence under "Suggestions we could not
    confirm"; it moves no number), then "where the upside is"
    cards for the biggest open claims.
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
    it and whether any cited page was the brand's own.
  - **Why AI misses you** — diagnosis sections, each headed by one finding sentence and collapsed
    on a phone. **What ChatGPT searched** (`insights.searches`): the web searches the measured model
    ran for the buyer questions (every try), read from the Responses API's `web_search_call` items
    into `Answer.searches` and grouped when they differ only by case, a year or punctuation; one
    question told as a sentence, then each search with the questions it came from and the pages
    cited in those answers, the brand's own marked. The API does not say which search found which
    page, so pages belong to the answer. Runs saved before searches were kept say "not recorded";
    the bundled samples carry authored searches, labelled sample, that move no score.
    **Can AI read your site?** is a red/green mark per check for each claim's page (AI crawlers, text without JavaScript,
    structured data, headings, speed; a claim that passes all five is one green mark). The page
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
    passage) and scored again; tap a row for the passages. Every number is labelled a
    **retrieval score**, a similarity-based simulation, never a guarantee of citation, and moves no
    score. On a live run, "Ask the AI again with the fix" asks the buyer question once with the
    rewritten passage and the cited page as the only sources and says whether the brand is named:
    one metered call, off until pressed, refused without a pass. Pages not read are listed with the
    reason. The bundled samples carry an authored sample, labelled as such. Overview gets one line
    on the biggest fixable gap.
  - **Sources & rivals** — the **citation network**, headed by its finding ("AI cited 6 sites
    beside your rivals, never beside Notion"; collapsed on a phone): the third-party sites (not the
    brand's or a rival's own) cited in counted buyer answers that named a rival and never mentioned the brand, ranked by buyer answers citing
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
    ("Johnson & Johnson Innovative Medicine" beside "Johnson & Johnson") counts as that company
    only when the rest of its name is a known division or legal suffix, so "Merck KGaA" stays apart
    from "Merck" (`evaluation.merge_divisions`). Each axis is one of the company's own claims, so it is always
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
- **History** — every saved run from `data/runs/` with its untapped potential; click one to open
  its report in place
- **Compare** — two runs side by side as untapped potential with the real score beneath, the change
  in untapped potential, and per-attribute zone changes (`claim to win back → landed`)

Saving weights on the Notion tab — or measuring, which saves them first — writes to the committed
seed file, so the working tree shows it modified afterwards; `git checkout data/companies/5eed0001.json`
restores the example weights.

## Wording

No engine identifier is the only name a reader gets: where a raw id is still shown for traceability
it follows the words it stands for, as in "Unbranded question 3 — Project tracking (`pt-3`)".
`web/src/labels.ts` names everything the browser holds (probe ids, run ids, provenance, probe kinds);
`labels.py` names the ids the engine bakes into strings it hands over whole (exclusion reasons, the
follow-up rationale, gap findings, the Markdown export), and `reports.py` names strengths and topic
statuses where the Markdown export prints them.
Change a word in one of those label modules, not in a component. The ids themselves are untouched — the
JSON export, `data/runs/` and the baseline hash are exactly what they were.

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
- Production: `VITE_API= npm run build` makes a same-origin build in `web/dist`, which FastAPI serves when it exists (the `Dockerfile` and `render.yaml` do this — see README "Deploy to Render")
