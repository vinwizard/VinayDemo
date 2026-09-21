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
LIVE_MODEL=gpt-6-astra
```

Restart the API. It prints `[config] loaded from .env: OPENAI_API_KEY=<set>` — names only, never
values. Check `curl -s http://127.0.0.1:8000/api/health` for `"live_available": true`. There is no
mode switch in the page: every measurement it starts is live.

A live run asks every brand and buyer question once to the measured model with web search, and has
the evaluator grade each answer — two calls per question — plus one round-two comparison question
when a buyer answer names a competitor. Without a key, live mode
**errors** rather than falling back to fixtures — a fixture result under a live label would be a
fabricated measurement.

Before a live run the API makes one trivial preflight call, so a broken setup fails once with one
message rather than once per question. It is classified on the HTTP status, never the error text: a
401 means OpenAI refused the key, a 403 is an account-level refusal (most often OpenAI not serving
your region), and only a 400 means the model will not take the web_search tool and `LIVE_MODEL` needs
changing. The message names the error type and status only — the provider's response body is never
shown, because a 401 body quotes part of the key back.

Set `EVALUATOR_MODEL` to a different model from `LIVE_MODEL` once it works: a model grading its own
output has a self-preference bias.

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
| `GET /api/health` | liveness, whether live mode is usable, and `seed_company` — the id of the preloaded company |
| `GET /api/stream?company=<id>` or `?scenario=A&mode=demo` | SSE while the graph runs: `node` (with `planned` question counts per stage, discovered `competitors` and the run `mode`), `answer` (the question, the first 320 characters of its answer, provenance and whether a web search ran), `done` (the full run), `error`. A company is always `mode=live`, apart from the offline fallback above. The page only ever measures companies; `?scenario=` remains for the fixture path |
| `GET /api/runs` | run history, newest first |
| `GET /api/runs/{id}` | one full run, including the drift report |
| `GET /api/onboard/stream?url=&name=` | the same onboarding as SSE: `pages` (the URLs the crawl fetched) as soon as the crawl lands, then `company` once extraction is saved, or `error`. The page uses this one |
| `GET /api/onboard?url=&name=` | Agent 1: crawl up to 6 of a company's own pages, extract the **claimed** layer (attributes, verbatim quotes, derived page counts) and **save** the company. Needs the same key as live mode. A company is always saved, never refused: a site where fewer than three claims survive quote validation carries a prominent warning that it states too little for a reliable claim percentage, and the existing insufficient-evidence rules withhold the scores rather than the company |
| `GET /api/companies` · `GET /api/companies/{id}` | onboarded companies, newest first, and one in full |
| `PATCH /api/companies/{id}` | the customer's own input: `{weights: {id: 0..1}, added: [{label, description, intended_weight}]}`. Intent arrives only here — never derived from their copy, and a weight of 0 leaves an extracted attribute unintended. An **added** claim is intended by construction, so its weight cannot go below 0.1 |
| `DELETE /api/companies/{id}/attributes/{attr}` | removes a claim the customer added. Refuses for a claim extracted from their own pages: that one is evidence, and excluding it from scoring is what its zero slider is for |

Comparison is done client-side from two `GET /api/runs/{id}` responses — no extra endpoint.

## Views

- **Notion** — the preloaded company. `data/companies/5eed0001.json` is a real onboarding of
  notion.com, committed so a fresh clone has it, with an example set of intent weights the page
  labels as an example rather than Notion's own. It is the same workflow as the next tab, starting at
  step 3
- **Onboard your own company** — one workflow on one screen, seven stages that complete in order:
  read their site (the pages fetched), extract what they claim (claims kept, each with its verbatim
  quote and page count), choose what you want to be known for (the zero-floor intent sliders and the
  add-your-own row), ask buyer questions, ask brand questions, follow up on products AI named, and
  score. Each stage is driven by the stream's events, shows what it actually did, and lists every
  answer as it arrives; a finished stage folds to a one-line summary. The report appears beneath
  the stages when scoring finishes. Previously onboarded companies can be reopened from step 1
- **Report** (inline after a run, and from History) — where the answers came from first (measured
  live, with the model, or the SYNTHETIC DEMO banner for a replayed run), then positioning alignment
  and buyer visibility side by side, a legend counting each zone with what it means, the
  claim-vs-echo drift map with an Evidence disclosure per claim, "whose problem is each gap" cards,
  "named in buyer answers" (every product named in a buyer answer that counts toward the scores,
  beside the part of the answer that names it, ranked only when a name repeats across answers, plus the round-two
  comparison question built from those names), and the evidence, limitations and log behind a
  disclosure. **Unprioritised** is the zone for a claim the company's own pages state and AI repeats,
  but which the customer never weighted — the default state of every onboarded attribute until a
  slider moves, and the one case where "imposed" would otherwise accuse AI of asserting something the
  company demonstrably claims
- **History** — every saved run from `data/runs/`; click one to open its report in place
- **Compare** — two runs side by side with the alignment delta and per-attribute zone changes (`lost claim → landed`)

Saving weights on the Notion tab — or measuring, which saves them first — writes to the committed
seed file, so the working tree shows it modified afterwards; `git checkout data/companies/5eed0001.json`
restores the example weights.

## Wording

No engine identifier is the only name a reader gets: where a raw id is still shown for traceability
it follows the words it stands for, as in "Buyer question 3 — Project tracking (`pt-3`)".
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
- No production build wiring — Vite dev server only, so nothing is deployable from here yet
