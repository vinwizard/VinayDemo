# measure/ — what does AI say when asked? (one run)

- `graph.py` is the run: LangGraph nodes, routing, budgets. Only the graph thread writes a run, in `graph.canonical` order.
- `ana.py` writes the questions and rejects leaks: buyer questions never name the brand or the vendor (`brand_leaks`, `vendor_address`); brand questions never name the attribute (`attribute_leaks`). `demand.py` grounds buyer questions in real searches; `sampler.py` sizes how many to ask; `dispatch.py` is the one process-wide queue for live asks; `sharing.py` reuses answers across runs.
- `run.answers` holds one answer per question; re-asks go in `run.repeat_answers`; a reused answer never counts twice.
- Must not: give the measured model the company profile, or ask from a thread that did not copy the context (`access.pmap`).
- More: skill `product-workflow`.
