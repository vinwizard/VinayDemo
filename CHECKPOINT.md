# CHECKPOINT

## Milestone 1 — environment (done)
- Added `CLAUDE.md` containing `@agents.md`. Existing `README.md` (one line) and `agents.md` preserved.
- venv with `/usr/local/bin/python3.12` (system python is 3.9). Pinned: streamlit 1.64.0, langgraph 1.2.11, pydantic 2.13.5, pytest 9.1.1.
- Empty page verified: `curl localhost:8501/_stcore/health` → 200.

## Decisions log
- Python 3.12 from /usr/local/bin (3.13 also present; 3.12 preferred by spec).
- Single `.venv` in repo; `data/runs/*.json` gitignored (local runs are user data).

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
