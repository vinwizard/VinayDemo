# Off Message

Give it a company's website and it shows how AI assistants describe that company, compared with
what the company wants to be known for.

## Code map

```
web/          React app: the product UI
api/          FastAPI server the UI talks to, the why agent's endpoints, and the /admin page
agents/       the steps of a run: onboarding a company, planning questions, reading answers
providers/    where answers come from: live model calls, or bundled sample replays
graph.py      wires the agents into one run
why.py        the why agent: investigates why AI does or does not repeat a claim
sampler.py    decides how many buyer questions a run asks
sharing.py    reuses buyer questions and answers across brands in one category
schemas.py    shared data types
other *.py    supporting modules: site crawling and checks, scoring, reports, access passes, config
fixtures/     bundled sample scenarios for offline demos and tests
data/         saved companies, runs and research snapshots
tests/        Python test suite (offline, no network)
```

Other docs: [`WEB.md`](WEB.md) (API, configuration, views, hosting), [`DEMO.md`](DEMO.md)
(presenter script), [`AGENTS.md`](AGENTS.md) (notes for coding agents).

## Setup

### Prerequisites

- Python 3.12 (the project uses a Miniconda env named `visexp`)
- Node.js 22 and npm
- An OpenAI API key for live runs

### Install

```bash
conda create -y -n visexp --override-channels -c conda-forge python=3.12
conda activate visexp
python -m pip install -r requirements.txt
(cd web && npm install)
```

### Environment variables

Put them in `.env` at the repo root (gitignored); [`.env.example`](.env.example) lists them.
Only the key is needed locally; everything else has a default.

| Variable | For |
| --- | --- |
| `OPENAI_API_KEY` | live runs and onboarding |
| `MEASURED_MODEL`, `EVALUATOR_MODEL`, `ONBOARDING_MODEL` | choosing which models are used |
| `TARGET_MARGIN`, `WOBBLE_AUDIT` | how many questions a run asks |
| `RUN_BUDGET_USD`, `WHY_BUDGET_USD` | optional spending caps per run and per investigation |
| `DATA_DIR` | where companies, runs and passes are stored |
| `VISEXP_OFFLINE_REPLAY` | replay the bundled sample instead of calling a model |
| `VISEXP_PUBLIC_DEMO` | hosted-demo mode |
| `SESSION_SECRET`, `ADMIN_PASSWORD`, `CONTACT_EMAIL` | access passes and the admin page |

[`WEB.md`](WEB.md#live-mode) describes each one.

### Run locally

Two terminals, from the repo root, both in the `visexp` env:

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000   # API
cd web && npm run dev                                          # web app
```

Open http://localhost:5173. With no key or network, start the API with `VISEXP_OFFLINE_REPLAY=1`.
If `conda activate` is not found in your shell, see [`WEB.md`](WEB.md#why-not-conda-activate).

### Run the tests

```bash
python -m pytest -q                              # Python, offline
cd web && npx tsc -b && npx oxlint && npm test   # web typecheck, lint, unit tests
```

CI runs the same on every pull request ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

### Deploy to Render

1. Sign in at [render.com](https://render.com) with GitHub.
2. **New → Blueprint** and pick this repository; it reads [`render.yaml`](render.yaml).
3. Enter the secrets it asks for (`OPENAI_API_KEY`, `ADMIN_PASSWORD`) and **Apply**.
4. Check `<site>/api/health` shows persistent storage, then open `<site>/admin` to hand out access links.

Passes, the admin page and storage checks: [`WEB.md`](WEB.md#deploy-to-render).
