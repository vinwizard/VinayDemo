---
name: build-history
description: Load only for project history - the original overnight Streamlit build brief (demo screens, file layout, implementation order, delivery and handoff requirements, references) and its milestone log with the acceptance results of 2026-09-18. Not current run instructions; README.md and WEB.md own those.
---

# Build history: the original overnight brief and milestone log

Historical. The brief below is agents.md's opening, sections 7, 8 (layout), 9, 11, 12 and References, moved verbatim; the milestone log is the former CHECKPOINT.md, moved verbatim. Both describe the Streamlit app that has since been deleted (`app.py` is gone). The instruction to make CLAUDE.md import agents.md is superseded: CLAUDE.md now stands alone and agents.md was split into the skills beside this one.

# Part 1 — original brief (from agents.md)

## agents.md — Visibility Explorer

## Start here: tonight's assignment

Build a complete localhost demo by tomorrow morning. Keep the product scope narrow: **discover a company's AI visibility gaps across its supported market topics, and explain where Profound could help investigate or address them.** Spend overnight time finishing, testing, and polishing this workflow, not adding new products.

This file replaces the earlier one-hour plan and expanded overnight brief. It is self-contained. The user currently has no API keys or cloud setup. A working, attractive, clearly labeled fixture demo is tonight's required deliverable. Live model calls are optional and must never block it.

Use Python, Streamlit, LangGraph, Pydantic, and local JSON files. No separate frontend/backend, database, accounts, billing, content publishing, outreach automation, scheduled monitoring, or multi-provider implementation tonight. Prepare a Dockerfile and deployment notes after the local demo works; actual cloud deployment is the next milestone.

The application is an independent portfolio demo relevant to Profound and LangChain, not a Profound integration or official product.

### Make these instructions visible to Claude Code

Claude Code documents `CLAUDE.md` as its project instruction file. Do not assume lowercase `agents.md` is automatically loaded. Read this file explicitly, then create a project-root `CLAUDE.md` containing the following import, preserving any existing instructions:

```markdown
@agents.md
```

Every coding worker must read the relevant scope below. The three product agents are logical application roles; they do not require three coding workers or three deployed services. Follow this plan even if working alone.

## 7. Make tomorrow's demo look convincing through clarity

Use a wide Streamlit layout, restrained colors, strong spacing and readable evidence. Product title: **Visibility Explorer**; subtitle: **Find the buyer questions where your brand is missing.**

### Screen 1 — Company setup

Mode banner at top. “Load Notion demo” primary action; URL/text input secondary. Profile summary, sources, positioning points and four topic cards. Show what is supported versus uncertain. Allow review before “Explore visibility.”

### Screen 2 — Investigation

Visible workflow stages: Onboarding, Topic planning, Baseline, Gap evaluation, Follow-up, Report. Show completed query count and a concise AnA decision log. In replay, button text is “Run demo replay.” No fake provider latency, token bills or live-status indicators.

### Screen 3 — Gap report

- Baseline topic table: recommendation fraction, score, evidence coverage, gap status.
- Topic cards with an expandable list of the three questions and full answer/evaluation details.
- Separate exploratory results tab.
- “Where Profound could help” panel showing a capability, a specific action, and supporting evidence for each gap.
- Download JSON and Markdown report buttons.
- Reset/replay control that reliably restores the original sample.

Bundle two synthetic scenarios with different weak topics, so switching scenarios changes AnA's next selected topic. This demonstrates feedback-dependent behavior without pretending live model inference occurred.

For the Notion fixture, topic labels may include team knowledge bases, project tracking, meeting documentation and personal organization. Clearly label these as illustrative until the company profile has been sourced. Use visibly fictional citation URLs such as `https://example.com/demo-source-1` for invented sources; do not fabricate quotes from real webpages.

Capture screenshots of setup and completed results once the app runs. Include a concise `DEMO.md` script for a two-minute presentation. If screenshot tooling is unavailable, state that limitation; still start and verify the local app.

## 8. Implementation layout and execution limits

```text
app.py
schemas.py
graph.py
agents/onboarding.py
agents/ana.py
agents/evaluation.py
providers/fixture.py
providers/imported.py
providers/live.py           # optional; disabled without key
scoring.py
reports.py
fixtures/demo_a.json
fixtures/demo_b.json
data/research/              # sourced development-time snapshots
data/runs/                 # completed local runs
tests/
requirements.txt
.env.example
.gitignore
.dockerignore
Dockerfile
README.md
DEMO.md
CHECKPOINT.md
CLAUDE.md                  # imports this file
agents.md
```

Prefer Python 3.12 if available; otherwise use an already installed supported Python version compatible with dependencies. Create a virtual environment; do not replace the system Python. Pin the dependency versions that passed checks.
## 9. Overnight implementation order

1. Read this file; inspect existing code and preserve unrelated changes. Add the CLAUDE.md import.
2. Scaffold the local environment and start an empty Streamlit page immediately.
3. Build contracts, two coherent fixture datasets, deterministic scoring and the graph.
4. Complete the entire no-key user journey. Missing API keys must cause no startup or demo failures.
5. Add bounded real company research/import only if the tools are available. Keep its provenance separate.
6. Test failure handling, provenance and feedback-dependent routing.
7. Polish the page, inspect it in a browser if available, and capture screenshots.
8. Add report downloads, the two-minute demo script and restart instructions.
9. Prepare Docker/deployment notes for later. Keep localhost running and stop adding features.

Maintain `CHECKPOINT.md` after each milestone: completed work, commands that worked, failures, next task. Usage limits, machine sleep or permission prompts may interrupt an overnight run; leave the project resumable. Do not claim all-night execution is guaranteed.

## 11. Local delivery and later deployment

Create a README with commands adapted to the user's actual environment, ordinarily:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Hand off the URL `http://localhost:8501` only after verifying it responds. If working on a remote coding host, clearly state that this is that host's localhost and provide steps to run on the user's Mac.

For future hosting, assume GCP Cloud Run (the earlier “JCP” interpreted as GCP). Prepare a Dockerfile listening on `$PORT`, `.dockerignore`, and documented Cloud Run source-deployment steps. Fixture mode should deploy without model keys. Later live mode uses server-side secrets and paid-run access controls.

Do not provision paid resources or publish anything tonight; first finish the local demo. Public deployment follows once the user has a cloud project, billing/permissions and has reviewed the demo. Cloud Run disk/session state is ephemeral: local JSON files are not durable hosted storage. Describe that limitation rather than adding a database tonight.

## 12. Final handoff required from Claude Code

- Working local URL and exact restart command.
- Screenshot paths if captured.
- Two-minute presentation steps in DEMO.md.
- Tests actually run and their outcomes.
- What is simulated, what uses genuine research, and what needs API credentials.
- Known blockers and the shortest path to deploy the existing demo.

Build the application now. Make ordinary implementation decisions autonomously. Do not stop at another plan, ask for keys before building the demo, or expand into publishing/content generation. Finish the defined acceptance checks, then stop.

## References

Use current official documentation for exact APIs. These references establish capabilities, not permission to assume free access:

- [Claude Code tools: WebSearch/WebFetch and availability](https://code.claude.com/docs/en/tools-reference)
- [Claude Code project memory and CLAUDE.md imports](https://code.claude.com/docs/en/memory)
- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [Gemini search grounding, if enabling a keyed adapter later](https://ai.google.dev/gemini-api/docs/google-search)
- [Cloud Run source deployment](https://docs.cloud.google.com/run/docs/deploying-source-code)
- [Profound Answer Engine Insights](https://www.tryprofound.com/features/answer-engine-insights)
- [Profound Agents](https://www.tryprofound.com/features/agents)
- [Profound template catalog](https://www.tryprofound.com/agent-templates)

# Part 2 — milestone log (former CHECKPOINT.md)

## Milestone 1 — environment (done)
- Added `CLAUDE.md` containing `@agents.md`. Existing `README.md` (one line) and `agents.md` preserved.
- Miniconda env `visexp` on Python 3.12 (conda-forge channel only; system python is 3.9). Pinned via pip inside the env: streamlit 1.64.0, langgraph 1.2.11, pydantic 2.13.5, pytest 9.1.1.
- Empty page verified: `curl localhost:8501/_stcore/health` → 200.

## Decisions log
- Python 3.12 from /usr/local/bin (3.13 also present; 3.12 preferred by spec).
- Single conda env `visexp` (not in the repo); `data/runs/*.json` gitignored (local runs are user data).

## Milestone 2 — contracts, fixtures, scoring, graph (done)
- `schemas.py`, `scoring.py`, `agents/{onboarding,ana,evaluation}.py`, `providers/{fixture,imported,live}.py`, `graph.py`, `reports.py`.
- `fixtures/demo_a.json` (weak: project tracking) and `demo_b.json` (weak: personal organization). Same profile/topics/baseline; different answers.
- Verified: A → AnA selects pt, mtg; B → po, kb. JSON round-trip preserves run.

### Decisions
- Fixtures generated once by a throwaway script; JSON files are the source of truth now.
- Fixture labels live on `Answer.fixture_labels` (validator: synthetic only). Evaluation re-checks every label against raw text.
- Alias match is case-sensitive + word-bounded ("the notion of" ≠ Notion). Brand-leak check is case-insensitive (stricter).
- Topic fit evidence is resolved from the approved profile's positioning points at plan time.
- Gap priority uses exact fractions (not rounded rates).
- URL fetching kept DISABLED (spec allows this); pasted text + bundled snapshots only. A safe fetcher (DNS-rebinding-proof) is real work with no demo payoff tonight.
- Live adapter is a disabled stub with limits + neutral prompt builder; never claims to work.

## Milestone 3 — no-key user journey (done)
- `app.py`: three screens (setup / investigation / gap report), permanent mode banner, sidebar scenario switch, reset, reopen saved runs, import JSON, live-adapter status.
- Runs execute only via a one-shot `run_requested` flag consumed before graph execution (rerenders never restart).
- Verified with Streamlit AppTest: load → review → explore → run A (pt, mtg) → switch to B → run (po, kb) → report renders, no exceptions.

### Decisions
- Screen navigation is a horizontal radio (tabs can't be switched programmatically).
- Switching scenario keeps approval (same profile) and clears the run.

## Milestone 4 — bounded research snapshot (done)
- 8 of 12 allowed operations: curl of 5 notion.com pages + 3 tryprofound.com pages.
- `data/research/notion_2026-09-18.json` (provenance `web_research_snapshot`): 7 verbatim excerpts, each string-checked against fetched HTML; plus notes confirming each Profound capability named in the mapping table appears on the official pages.
- App applies the snapshot to profile evidence by default (sidebar toggle). Answers remain synthetic; snapshot never feeds scores.

### Decisions
- Used curl + local string checks (not WebFetch's summarizer) so excerpts are guaranteed verbatim.
- pp4 reworded in both fixtures to what the source supports (dropped the unsourced "templates" claim).

## Milestone 5 — tests (done)
- `python -m pytest -q` → 46 passed. `tests/test_core.py` (engine, network blocked), `tests/test_ui.py` (AppTest journey per fixture, rerender, reopen, arbitrary company).

## Milestone 6 — polish + screenshots (done)
- `.streamlit/config.toml`: minimal toolbar, restrained indigo primary, no usage stats.
- "Where Profound could help" cards gained a Supporting evidence expander (probe text, explanation, verbatim quotes).
- Screenshots in `screenshots/` (1_setup, 2_investigation_A, 3_report_A, 4_profound_help_A, 5_followups_A, 6_investigation_B) captured with Playwright driving installed Google Chrome (dev-only tool, not in requirements.txt).

## Milestone 7 — docs + deployment prep (done)
- README (run/test/deploy), DEMO.md (2-minute script), .env.example, Dockerfile ($PORT), .dockerignore.

## Section 10 acceptance checks — results (2026-09-18)

| Check | Result | How verified |
| --- | --- | --- |
| Starts and completes both scenarios with no keys / no internet | PASS | `test_both_scenarios_complete_offline` (sockets blocked), `test_journey[A,B]`; app has no network code |
| Three agent roles implemented and visible | PASS | `agents/`, stage row in UI, `test_three_agent_roles_in_workflow` |
| Adaptive selection changes with fixture results | PASS | A→pt,mtg; B→po,kb; swapped-evaluation test |
| Baseline unchanged after follow-up | PASS | hash + recomputed baseline scores equal stored |
| Every query/topic explained with provenance | PASS | `test_every_query_and_topic_explained` |
| Every gap → capability or insufficient evidence | PASS | `test_every_gap_maps_to_capability_or_insufficient`, insufficient-evidence test |
| Synthetic never under a real provider / live timestamp | PASS | Answer validator + parametrized tests |
| Search snapshots never scored as chatbot visibility | PASS | `test_search_snapshot_never_scored` |
| [2,1,0] → 50; no eligible → null | PASS | `test_visibility_math`, `test_no_eligible_answers_gives_null` |
| Negative, citation-only, ambiguous alias, deceptive domain, timeout, ungrounded | PASS | dedicated tests each |
| Invalid quotes flagged; brand-leaking questions rejected | PASS | quote/competitor tests; leak tests incl. graph halt |
| Export/import preserves provenance, counts, baseline version | PASS | round-trip + tamper rejection |
| Arbitrary company can't get bundled report | PASS | engine + UI tests; structural edits also rejected |
| Rerenders don't restart runs | PASS | `test_rerenders_do_not_restart_runs` (answer-call counter) |
| Secrets not logged/exported/committed | PASS | `test_secrets_not_exported_or_committed`; `.env` gitignored |
| Local URL responds; completed report reopens | PASS | curl `/` 200 + health ok; Playwright reopen in fresh session |
| Live adapter | NOT TESTED — not implemented (no credentials) | reported honestly |
| Docker image build | NOT VERIFIED — Docker daemon not running | Dockerfile written only |

## Section 12 handoff

- **URL:** http://localhost:8501 (this Mac; verified responding).
- **Restart:** `cd ~/Projects/VinayDemo && conda activate visexp && python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501`
- **Screenshots:** `screenshots/1_setup.png`, `2_investigation_A.png`, `3_report_A.png`, `4_profound_help_A.png`, `5_followups_A.png`, `6_investigation_B.png`
- **Demo script:** `DEMO.md`
- **Tests:** `python -m pytest -q` → 46 passed (offline).
- **Simulated:** all AI answers and their labels, AnA follow-up policy, evaluator judgment, every score.
- **Genuine research:** Notion positioning evidence (7 verbatim excerpts from 5 notion.com pages, 2026-09-18) and the Profound capability names/links (3 official pages).
- **Needs API credentials:** live answers, model-backed AnA planning and evaluation (`providers/live.py` is a disabled stub).
- **Known blockers:** no API keys; Docker daemon was off so the image is unbuilt; URL fetching intentionally disabled; `data/runs/` is not durable on Cloud Run.
- **Shortest deploy path:** start Docker → `docker build -t ve . && docker run -p 8080:8080 ve` to check → `gcloud run deploy visibility-explorer --source . --region us-central1` after creating a GCP project with billing.

## Next task
Nothing required for the demo. Optional next: implement `providers/live.py` against one official search-grounded API once a key exists.
