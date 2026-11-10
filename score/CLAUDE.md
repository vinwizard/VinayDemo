# score/ — what do the numbers say? Arithmetic in code, no model judgment.

- `scoring.py`: per-question strength, eligibility, intervals. `drift.py`: intended vs claimed vs perceived per claim. `insights.py`: cited sites, share of voice, what AI searched. `positioning.py`: where AI places the brand and its rivals (embeddings via core/).
- With no eligible answers return null, not zero; flag small samples instead of printing a number.
- Must not: ask a model to judge, pool provenances (`synthetic`, `live_api`, ...) into one number, or present a score as a cause.
- More: skill `evaluation-and-scoring`.
