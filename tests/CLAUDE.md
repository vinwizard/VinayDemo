# tests/ — offline checks for the Python engine

- No test reaches the network, the real data folder or your `.env`: `conftest.py` stubs every fetch, search and embedding (the site audit fetches only through `audit.get`, which it refuses). A test that needs one records responses (`cassettes/`, `audit_fixtures/`, `discovery_fixtures/`).
- `fakes.py` holds shared stand-ins; `access._create` is replaced, so metering still runs.
- Prefer a parametrized row to a new test function. Run: `python -m pytest -q`.
