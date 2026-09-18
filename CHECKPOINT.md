# CHECKPOINT

## Milestone 1 — environment (done)
- Added `CLAUDE.md` containing `@agents.md`. Existing `README.md` (one line) and `agents.md` preserved.
- venv with `/usr/local/bin/python3.12` (system python is 3.9). Pinned: streamlit 1.64.0, langgraph 1.2.11, pydantic 2.13.5, pytest 9.1.1.
- Empty page verified: `curl localhost:8501/_stcore/health` → 200.

## Decisions log
- Python 3.12 from /usr/local/bin (3.13 also present; 3.12 preferred by spec).
- Single `.venv` in repo; `data/runs/*.json` gitignored (local runs are user data).
