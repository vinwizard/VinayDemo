# Web frontend (React + FastAPI)

Replaces the Streamlit UI. The Python engine is **unchanged** — `graph.py`, `drift.py`, `agents/`,
`scoring.py` and the fixtures are imported, not modified. `app.py` still runs today, but it is
scheduled for removal in a filed follow-up task.

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
cd ~/Projects/VinayDemo/.claude/worktrees/web-frontend && ~/miniconda3/envs/visexp/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Terminal 2 — the frontend:

```bash
cd ~/Projects/VinayDemo/.claude/worktrees/web-frontend/web && export PATH="$HOME/miniconda3/envs/visexp/bin:$PATH" && npm run dev
```

Open **http://localhost:5173** — not `127.0.0.1:5173`. Vite binds IPv6 localhost and the numeric
address is refused. The API must be on port 8000; CORS allows only the Vite dev origin.

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
values. Check `curl -s http://127.0.0.1:8000/api/health` for `"live_available": true`, then reload the
page and the Mode dropdown becomes selectable.

A live run is 16 calls: 8 to the measured model with web search, 8 to the evaluator. It measures
perception only, so alignment is produced and visibility stays null. Without a key, live mode
**errors** rather than falling back to fixtures — a fixture result under a live label would be a
fabricated measurement.

Set `EVALUATOR_MODEL` to a different model from `LIVE_MODEL` once it works: a model grading its own
output has a self-preference bias.

To watch the streaming work without spending anything, run the API with a per-answer stall:

```bash
VISEXP_DEV_DELAY=1 ~/miniconda3/envs/visexp/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

`node` and `npm` come from the `visexp` conda env — nothing is installed system-wide.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | liveness + known scenarios |
| `GET /api/scenarios` | scenario list with each company's intended attributes and claim strength |
| `GET /api/stream?scenario=A` or `?company=<id>` | SSE: `node`, `answer`, `done`, `error` events while the graph runs. A company is always `mode=live` |
| `GET /api/runs` | run history, newest first |
| `GET /api/runs/{id}` | one full run, including the drift report |
| `GET /api/onboard?url=&name=` | Agent 1: crawl up to 6 of a company's own pages, extract the **claimed** layer (attributes, verbatim quotes, derived page counts) and **save** the company. Needs the same key as live mode. A company is always saved, never refused: a site where fewer than three claims survive quote validation carries a prominent warning that it states too little for a reliable claim percentage, and the existing insufficient-evidence rules withhold the scores rather than the company |
| `GET /api/companies` · `GET /api/companies/{id}` | onboarded companies, newest first, and one in full |
| `PATCH /api/companies/{id}` | the customer's own input: `{weights: {id: 0..1}, added: [{label, description, intended_weight}]}`. Intent arrives only here — never derived from their copy, and a weight of 0 leaves an extracted attribute unintended. An **added** claim is intended by construction, so its weight cannot go below 0.1 |
| `DELETE /api/companies/{id}/attributes/{attr}` | removes a claim the customer added. Refuses for a claim extracted from their own pages: that one is evidence, and excluding it from scoring is what its zero slider is for |

Comparison is done client-side from two `GET /api/runs/{id}` responses — no extra endpoint.

## Views

- **Measure** — pick a scenario, see intended attributes and how much of their own copy states each, run it, watch the live feed and progress bar
- **Onboard a company** — name, website, "Read their site": the claims it found as full statements with their supporting quote and the page count beside every percentage, an intent slider per claim starting at zero, and a row to add a claim their copy never states. Measuring from here is live-only and the screen says so
- **Report** — alignment headline, six zone counters (landed, lost claim, contested, never stated, imposed, unprioritised), the claim-vs-echo drift map, "whose problem is each gap" cards, "who AI named instead" (competitors discovered from the blind answers, plus the round-two comparison question built from those names), evidence behind a disclosure. **Unprioritised** is the zone for a claim the company's own pages state and AI repeats, but which the customer never weighted — the default state of every onboarded attribute until a slider moves, and the one case where "imposed" would otherwise accuse AI of asserting something the company demonstrably claims
- **History** — every saved run from `data/runs/`, click to open
- **Compare** — two runs side by side with the alignment delta and per-attribute zone changes (`lost claim → landed`)

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
- No tests for the React app; the API has one, over the stream endpoint's setup-error path (`tests/test_api_stream.py`)
- Streamlit `app.py` still prints raw probe and node ids; it is scheduled for deletion rather than relabelling
- Report-surface attribute descriptions still render nothing: `AttributeScore` carries no
  `description` field. The onboarding task added `claim_pages`/`claim_pages_total` there but left
  this one open
- Emergent attribute discovery from answers (an attribute nobody declared) is still not implemented;
  filed as `vd-discover`
- `/api/onboard` and `PATCH /api/companies/{id}` are unauthenticated, like the rest of the API
- `_useful_description` in `agents/onboarding_model.py` strips the description to `[a-z ]` but
  matches the label unnormalized, so a label containing a hyphen, digit or ampersand ("AI-native
  workspace") can never be found and the restatement check degrades to a bare word count; filed as a
  separate follow-up
- Three.js 3-axis drift visual (deferred deliberately; the three layers are literally three axes)
- No production build wiring — Vite dev server only, so nothing is deployable from here yet
