# Web frontend (React + FastAPI)

Replaces the Streamlit UI. The Python engine is **unchanged** — `graph.py`, `drift.py`, `agents/`,
`scoring.py` and the fixtures are imported, not modified. `app.py` still runs; this is additive until
the React app reaches parity.

## Why not Streamlit

`st.status` can only render when a graph **node** returns. `execute_or_replay` answers the whole batch
inside one node call, so the page froze for the entire batch with no feedback — 24 seconds at 1s/answer,
and 50–130s with a real search-grounded provider.

The API runs the graph on a worker thread and pushes an SSE event per **answer** as well as per node.
Measured with `VISEXP_DEV_DELAY=1`, events arrive once per second throughout the batch instead of all at
the end. That is the whole reason for the move; Three.js and other rendering choices are irrelevant to it.

## Run it

Two processes. Terminal 1 — the API, from the repo root:

```bash
conda activate visexp && python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Terminal 2 — the frontend:

```bash
conda activate visexp && cd web && npm run dev
```

Open http://localhost:5173. The API must be on port 8000; CORS allows only the Vite dev origin.

To watch the streaming do its job, start the API with an artificial per-answer stall:

```bash
VISEXP_DEV_DELAY=1 python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

`node` and `npm` come from the `visexp` conda env — nothing is installed system-wide.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | liveness + known scenarios |
| `GET /api/scenarios` | scenario list with each company's intended attributes and claim strength |
| `GET /api/stream?scenario=A` | SSE: `node`, `answer`, `done`, `error` events while the graph runs |
| `GET /api/runs` | run history, newest first |
| `GET /api/runs/{id}` | one full run, including the drift report |

Comparison is done client-side from two `GET /api/runs/{id}` responses — no extra endpoint.

## Views

- **Measure** — pick a scenario, see intended attributes and how much of their own copy states each, run it, watch the live feed and progress bar
- **Report** — alignment headline, four zone counters, the claim-vs-echo drift map, "whose problem is each gap" cards, evidence behind a disclosure
- **History** — every saved run from `data/runs/`, click to open
- **Compare** — two runs side by side with the alignment delta and per-attribute zone changes (`lost claim → landed`)

## Not done yet

- No tests for the API or the React app
- Three.js 3-axis drift visual (deferred deliberately; the three layers are literally three axes)
- No production build wiring — Vite dev server only, so nothing is deployable from here yet
- `app.py` (Streamlit) is still the demo of record until this reaches parity
