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

Perception can also add attributes nobody declared. In a live run, after the brand answers come
back, one model call reads all of them together and proposes other ways they describe the brand.
Code keeps a proposal only when its quote is verbatim in the answer it cites, at least two different
eligible answers raise it, and it does not rephrase an attribute already being measured
(`evaluation.discover_attributes`). Nobody intended or claimed a kept one, so it lands as *imposed*,
marked "discovered from the answers".

The gap between **claimed** and **perceived** is an *authority gap* — you say it and the models do not
repeat it. The gap between **intended** and **claimed** is a *messaging gap* — AI does not say it because
you never clearly said it either. A claim AI does repeat, mostly to contradict it, is *contested* — a
different problem from silence. Naming which one you are looking at is the point of the product.

Two probe families measure two different things:

- **Blind probes** never name the brand → **visibility**. Do you show up at all? They are asked on
  two fronts side by side — where AI already places you (what the brand answers endorse most) and
  where your site aims to be (its core category) — each asked three times (visibility is the mean,
  shown with its range and a bootstrap 95% confidence interval, because the same question gets a
  different answer on every run; the gap between fronts says whether it is real, or that there are too few
  questions to call it), and each
  front's control question flags it low confidence when the model does not count you among that
  category's leading tools.
  Details: "Why a rerun gives a different number" in [`WEB.md`](WEB.md).
- **Named probes** name the brand but never name an attribute → **perception**. What does AI say you are?

The ids and these code names stay internal; on screen they are *unbranded questions* and *branded questions*
(see the wording rules in [`WEB.md`](WEB.md)).

A named probe that contains the attribute it measures invites the model to agree, so `ana.attribute_leaks`
rejects it. This is as load-bearing as the brand-leak rule on blind probes. A blind probe addressed to
the vendor ("your platform", "this product") is rejected the same way by `ana.vendor_address`: a buyer
who has never heard of the brand asks about a need and a kind of product, not about the vendor.

Independent portfolio demo — not a Profound product or integration. Agent instructions:
[`CLAUDE.md`](CLAUDE.md), with the detailed spec split into skills under [`.claude/skills/`](.claude/skills)
(the original overnight brief and milestone log are in `build-history`).
Presenter script: [`DEMO.md`](DEMO.md).

> **The page measures live; the bundled samples are synthetic.** The page has no demo mode. The two
> bundled Notion scenarios — reachable from the page only through the `VISEXP_OFFLINE_REPLAY=1` server
> fallback — are authored fixtures: answers, attribute observations and page-level claim counts. No
> chatbot was measured for them, and every run from them is labelled a replay. Every quote is verified
> verbatim against the answer it came from (a mention's quote ignoring only markdown emphasis and
> case), and unverifiable observations are dropped rather than repaired.

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

Conda supplies the Python interpreter; the project pins in `requirements.txt` are installed with `pip`
inside the env, which keeps the versions identical to the ones that passed the acceptance checks.

### Every time — run the app

The product is the React app in `web/` over the FastAPI server in `api/`: two processes, both in the
`visexp` env. From the repo root:

```bash
~/miniconda3/envs/visexp/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

and in a second terminal:

```bash
cd web && export PATH="$HOME/miniconda3/envs/visexp/bin:$PATH" && npm install && npm run dev
```

Open http://localhost:5173. The page measures live only, so it needs an OpenAI key in `.env`; for a
demo with no key or internet, start the API with `VISEXP_OFFLINE_REPLAY=1` and the preloaded Notion
company replays the bundled Notion sample, labelled as such. Stop either process with `Ctrl+C`.
[`WEB.md`](WEB.md) has the details, live mode and the API reference.

Tests: `conda activate visexp && python -m pytest -q` (offline; 457 passing,
incl. one journey per bundled scenario end to end through the `/api/stream` event stream, the API over
HTTP via fastapi's TestClient, the live adapter under an injected
transport — including how it classifies a refused key or a region block — no API key, no network).

CI runs those tests plus the web typecheck (`npx tsc -b`), lint (`npx oxlint`) and unit tests
(`npm test`: the positioning map's label placement and the report tab badges, under `node --test`) on every pull request.
`.github/workflows/ci.yml` states what a green tick does and does not cover.

### If you get `command not found: conda`

`conda activate` is a shell function from `~/.zshrc`, so it only exists in an **interactive** shell.
It works in a fresh Terminal tab and fails in scripts, non-interactive shells and some embedded
terminals. Either run `source ~/.zshrc` first, or skip it entirely by calling the env's Python by
absolute path, as the API command above already does.

For anything needing `npm`, export the env onto PATH instead (npm's shebang has to find `node`):

```bash
export PATH="$HOME/miniconda3/envs/visexp/bin:$PATH"
```

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
| Live model calls | **Implemented** in `providers/live.py` (OpenAI Responses API + web search) — needs `OPENAI_API_KEY`; setup in [`WEB.md`](WEB.md) |
| URL fetching for arbitrary companies | **Real** — `fetching.py` crawls up to 6 public pages (SSRF-safe) for the API's `/api/onboard`, which needs an OpenAI key |
| Can AI read your site? | **Real, no model** — `audit.py` re-fetches the claim pages as a no-JavaScript crawler, reads robots.txt, JSON-LD, headings and llms.txt, and looks the brand up on Wikidata/Wikipedia; tests replay recorded responses (`tests/audit_fixtures/`) |
| Measuring an onboarded company | **Live only.** A company crawled from a URL has no authored answers, so there is nothing to replay: it needs `OPENAI_API_KEY`. The two bundled scenarios still run offline with no key |

## Layout

```
web/              React frontend (the product UI)
api/main.py       FastAPI server over the engine; streams each run as server-sent events
api/admin.py      /admin: access passes for the hosted demo (see "Deploy to Render")
access.py         access passes, sessions, and the metered gateway every OpenAI call goes through
graph.py          LangGraph orchestrator: plan_brand → execute_or_replay → evaluate → perceive → plan_buyer → validate_and_freeze → execute_or_replay → evaluate → choose_followup ⟲ → measure_drift → build_gap_report
schemas.py        Pydantic contracts
agents/           onboarding.py (Agent 1), ana.py (Agent 2), evaluation.py (Agent 3 + Profound mapping table)
providers/        fixture.py (replay), company.py (an onboarded company), imported.py (research snapshots), live.py
scoring.py        arithmetic only
audit.py          can AI read the site: robots.txt, no-JS text, markup, speed, Wikidata/Wikipedia; no model
reports.py        JSON/Markdown export, import, data/runs and data/companies persistence (under DATA_DIR if set)
```

Completed runs are saved to `data/runs/<id>.json` and can be reopened from the History view after a restart.
Onboarded companies are saved the same way, to `data/companies/<id>.json`, and carry the same caveat:
both are local JSON files, so neither survives a Cloud Run redeploy (see below).

## Deploy to Render (public replay link, live passes)

[`render.yaml`](render.yaml) deploys the app as one paid web service with a persistent disk: the
`Dockerfile` builds the web app and FastAPI serves it with the API on the same origin. It sets
`VISEXP_PUBLIC_DEMO=1`, so a visitor **without a pass** gets the saved Notion replay and the committed
Profound live run only — no model calls, no cost. Live runs, onboarding and company edits are refused
with a message saying so. A visitor's replay is shown to them but never saved, so its report offers no
re-scoring; the saved example reports in History can be re-scored, and that is not saved either, so
one visitor cannot change what the next one sees. The two bundled scenarios are replayed once at
startup so History and Compare are not empty.

**Access passes** let chosen people run it live on your OpenAI key. Each pass has a name, a dollar
cap and a personal link, `<site>/?pass=<code>`. Opening the link signs the browser in (an HttpOnly
session cookie; the code leaves the address bar), after which the holder can onboard and measure
companies live, sees a meter such as "$1.40 of $5.00 used", and sees the saved demo reports plus their
own runs and companies — nobody else's. Every OpenAI call is checked against the cap before it is
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
   passes, spend, the visit log, runs and companies survive a redeploy. A disk needs a paid instance
   (`plan: starter`), and a service with a disk cannot scale past one instance, which is what the pass
   database expects.
5. **Check your storage**: `<site>/api/health` must show `"storage": {"persistent": true, ...}`. If it
   is `false`, the admin page shows a red banner (and the startup log a warning) saying why: passes
   then vanish on the next deploy. Fix it by giving the service a disk (Settings → Disks) and setting
   `DATA_DIR` to exactly that disk's mount path, e.g. `/var/data`.
6. Open `<site>/admin`, sign in, and **Generate link** for each person.

**Tuning a live run** (Render → the service → Environment). Every one of these has a working
default, so leave them alone unless you want to change what a run costs or how sure its numbers are;
the full table, with what each one does, is in [WEB.md](WEB.md#live-mode).

| Variable | Default | Raise it to… | Lower it to… |
| --- | --- | --- | --- |
| `MEASURED_MODEL` | `gpt-6-luna` | — set it to a bigger searching model (`gpt-5.6-luna`, `gpt-5.4-mini`, `gpt-5.5`) if the answers read thin | — |
| `EVALUATOR_MODEL` | `gpt-6-luna` | — set it to `gpt-4.1-mini` so the judge is not grading its own answers | — |
| `BUYER_QUESTIONS` | `12` per front | narrow the confidence range further | spend less per run |
| `REPEAT_SAMPLE` | `2` | see the wobble on more questions | `0` removes repeats, the wobble and the interval |
| `BUYER_TRIES` | `3` | — | — |

`<site>/api/health` shows what is actually in force: `measured_model`, `evaluator_model`,
`search_mode`, `forced_search`, `buyer_questions`, `repeat_sample` and `buyer_tries`. If OpenAI
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

## Deploying later (GCP Cloud Run)

Not done tonight — needs a GCP project, billing and your review. Shortest path once you have them:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT
gcloud run deploy visibility-explorer --source . --region us-central1 --allow-unauthenticated
```

`--source .` builds the included `Dockerfile`, which serves the web app and the API on `$PORT`.
Add `--set-env-vars VISEXP_PUBLIC_DEMO=1` for a replay-only public link; that needs no secrets.
Caveats: Cloud Run disk and sessions are ephemeral, so `data/runs/` and `data/companies/` are **not** durable
there — download JSON reports instead, and expect an onboarded company to have to be onboarded again after a
redeploy, or add storage later. Live mode would need server-side secrets (Secret Manager) and access
control on paid runs before going public. Local Docker check: `docker build -t ve . && docker run -p 8080:8080 ve`, then `curl localhost:8080/api/health`.
