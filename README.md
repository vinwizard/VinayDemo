# VinayDemo — Visibility Explorer

*Find the buyer questions where your brand is missing.*

A localhost demo that discovers a company's AI-visibility gaps across its supported buyer topics and explains
where Profound capabilities could help investigate them. Independent portfolio demo — not a Profound product or
integration. Spec: [`agents.md`](agents.md). Progress log: [`CHECKPOINT.md`](CHECKPOINT.md). Presenter script: [`DEMO.md`](DEMO.md).

> **Default mode is a synthetic demo.** Answers are authored fixtures, AnA follow-up selection is a deterministic
> simulated policy, and evaluation is fixture labels + deterministic validation. No chatbot was measured.

## Run it (macOS, this machine)

```bash
cd ~/Projects/VinayDemo
/usr/local/bin/python3.12 -m venv .venv          # first time only
source .venv/bin/activate
python -m pip install -r requirements.txt       # first time only
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open http://localhost:8501. No API keys, accounts, or internet needed.

Tests: `python -m pytest -q` (offline; 46 tests incl. one Streamlit UI journey per scenario).

## What's what

| Piece | Status |
| --- | --- |
| Answers, mention/recommendation labels | **Synthetic** fixtures (`fixtures/demo_a.json`, `demo_b.json`) |
| AnA follow-up choice | Deterministic **simulated** policy over the current evaluations |
| Scores, quote/citation/domain validation | Deterministic code (`scoring.py`, `agents/evaluation.py`) |
| Notion profile evidence | **Genuine** Claude Code research snapshot, `data/research/notion_2026-09-18.json` (verbatim excerpts, 2026-09-18) |
| Profound capability links | Official pages, checked the same night |
| Live model calls | **Not implemented** — `providers/live.py` is a disabled stub (needs an API key + implementation) |
| URL fetching for arbitrary companies | **Disabled** — paste facts instead |

## Layout

```
app.py            Streamlit UI (setup → investigation → gap report)
graph.py          LangGraph orchestrator: plan_baseline → validate_and_freeze → execute_or_replay → evaluate → choose_followup ⟲ → build_gap_report
schemas.py        Pydantic contracts
agents/           onboarding.py (Agent 1), ana.py (Agent 2), evaluation.py (Agent 3 + Profound mapping table)
providers/        fixture.py (replay), imported.py (research snapshots), live.py (disabled)
scoring.py        arithmetic only
reports.py        JSON/Markdown export, import, data/runs persistence
```

Completed runs are saved to `data/runs/<id>.json` and can be reopened from the sidebar after a restart.

## Deploying later (GCP Cloud Run)

Not done tonight — needs a GCP project, billing and your review. Shortest path once you have them:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT
gcloud run deploy visibility-explorer --source . --region us-central1 --allow-unauthenticated
```

`--source .` builds the included `Dockerfile` (listens on `$PORT`). Fixture mode needs no secrets.
Caveats: Cloud Run disk and sessions are ephemeral, so `data/runs/` is **not** durable there — download JSON
reports instead, or add storage later. Live mode would need server-side secrets (Secret Manager) and access
control on paid runs before going public. Local Docker check: `docker build -t ve . && docker run -p 8080:8080 ve`.
