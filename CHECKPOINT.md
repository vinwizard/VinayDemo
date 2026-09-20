# CHECKPOINT

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
