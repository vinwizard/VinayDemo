# core/ — what every part shares: data shapes, settings, storage, and who pays

- `schemas.py` is the one state contract. `web/src/api.ts` mirrors it: change both together.
- `access.py` meters every OpenAI call (`openai_response`, `openai_embedding`): it refuses at a pass's cap, charges from reported usage, and fails closed on the public demo. `passes.json` seeds the passes.
- `reports.py` stores runs, companies and investigations as JSON under `DATA_DIR`; `config.py` reads the root `.env`; `embeddings.py` meters and caches vectors; `labels.py` must say the same words as `web/src/labels.ts` (tests/test_labels.py).
- Must not: hold product logic, or reach a model except through `access`. One import leaves core today (`reports.py` uses `measure/ana.baseline_hash`); add no more.
