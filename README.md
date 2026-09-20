# VinayDemo — Positioning Drift

*How different is your brand in AI answers from the brand you are trying to be?*

Most AI-visibility tooling asks "are you mentioned?". This asks the harder question: **when AI does
describe you, is it describing the company you are trying to be?** A brand can be highly visible and
still badly misrepresented, and a presence/absence check scores that as a win.

Three layers are kept deliberately separate:

| Layer | What it is | Source |
| --- | --- | --- |
| **Intended** | What you want to be known for | Stated by the customer (aspirational; never counts as product fit) |
| **Claimed** | What your own public copy actually says | Evidence-backed |
| **Perceived** | What AI says when asked | Measured probes |

The gap between **claimed** and **perceived** is an *authority gap* — you say it and the models do not
repeat it. The gap between **intended** and **claimed** is a *messaging gap* — AI does not say it because
you never clearly said it either. Naming which one you are looking at is the point of the product.

Two probe families measure two different things:

- **Blind probes** never name the brand → **visibility**. Do you show up at all?
- **Named probes** name the brand but never name an attribute → **perception**. What does AI say you are?

A named probe that contains the attribute it measures invites the model to agree, so `ana.attribute_leaks`
rejects it. This is as load-bearing as the brand-leak rule on blind probes.

Independent portfolio demo — not a Profound product or integration. Spec: [`agents.md`](agents.md).
Architecture of the original visibility engine still applies: [`CHECKPOINT.md`](CHECKPOINT.md).
Presenter script: [`DEMO.md`](DEMO.md).

> **Default mode is a synthetic demo.** Answers, attribute observations and page-level claim counts are
> authored fixtures. No chatbot was measured. Every quote is verified verbatim against the answer it
> came from, and unverifiable observations are dropped rather than repaired.

## Run it (macOS, Miniconda)

The environment is managed with **Miniconda**, in a conda env named `visexp` (Python 3.12).

### First time only — install Miniconda

Skip if `conda --version` already works.

```bash
curl -fsSL -o /tmp/miniconda.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh
bash /tmp/miniconda.sh -b -p "$HOME/miniconda3"
"$HOME/miniconda3/bin/conda" init zsh
```

On Intel Macs use `Miniconda3-latest-MacOSX-x86_64.sh` instead. Restart your shell (or `source ~/.zshrc`) afterwards.

This project uses the **conda-forge** channel only, which avoids the Anaconda `defaults` Terms-of-Service
prompt. If `~/.condarc` does not already say so:

```bash
printf 'channels:\n  - conda-forge\nchannel_priority: strict\n' > ~/.condarc
```

### First time only — create the environment

```bash
cd ~/Projects/VinayDemo
conda create -y -n visexp --override-channels -c conda-forge python=3.12
conda activate visexp
python -m pip install -r requirements.txt
```

Conda supplies the Python interpreter; the four project pins in `requirements.txt` are installed with `pip`
inside the env, which keeps the versions identical to the ones that passed the acceptance checks.

### Every time — run the app

```bash
cd ~/Projects/VinayDemo
conda activate visexp
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open http://localhost:8501. No API keys, accounts, or internet needed. Stop the server with `Ctrl+C`.

Tests: `conda activate visexp && python -m pytest -q` (offline; 79 tests incl. one UI journey per
scenario and the live adapter under an injected transport — no API key, no network).

### If you get `command not found: conda`

`conda activate` is a shell function from `~/.zshrc`, so it only exists in an **interactive** shell.
It works in a fresh Terminal tab and fails in scripts, non-interactive shells and some embedded
terminals. Either run `source ~/.zshrc` first, or skip it entirely by calling the env directly:

```bash
cd ~/Projects/VinayDemo && ~/miniconda3/envs/visexp/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

For anything needing `npm`, export the env onto PATH instead (npm's shebang has to find `node`):

```bash
export PATH="$HOME/miniconda3/envs/visexp/bin:$PATH"
```

### Web frontend

A React + FastAPI frontend with live OpenAI measurement lives on the `worktree-web-frontend` branch.
See [`WEB.md`](WEB.md). The Streamlit app here remains the offline demo of record.

### Rebuilding the environment from scratch

```bash
conda env remove -y -n visexp
```

Then repeat the create step above.

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
