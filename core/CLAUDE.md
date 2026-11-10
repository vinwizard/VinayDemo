# core/ — what every part shares: data shapes, settings, storage, and who pays

- `schemas.py` is the one state contract. `web/src/api.ts` mirrors it: change both together.
- `llm.py` is the one door to OpenAI (`openai_response`, `openai_embedding`, `json_object`): it paces 429s, prices and charges each call. `access.py` decides who pays: passes, caps (refused at the cap, fail closed on the public demo), the ledger, a fleet's purse; `passes.json` seeds the passes. `llm` imports `access`, never the reverse.
- `reports.py` stores runs, companies and investigations as JSON under `DATA_DIR`; `config.py` reads the root `.env`; `embeddings.py` meters and caches vectors; `labels.py` must say the same words as `web/src/labels.ts` (tests/test_labels.py).
- Must not: hold product logic, or reach a model except through `llm`. One import leaves core today (`reports.py` uses `measure/ana.baseline_hash`); add no more.
