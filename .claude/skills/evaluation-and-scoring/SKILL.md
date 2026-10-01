---
name: evaluation-and-scoring
description: Load when changing agents/evaluation.py, scoring.py, or the offline acceptance tests. Per-query evaluation rules and the acceptance checklist.
---

# Evaluation, scoring and acceptance checks

From the original brief. Where this disagrees with the code, README.md or WEB.md, the code wins; the formulas live in `scoring.py` and its tests.

## Evaluations and scoring

Per-query strength: 0 = absent or negative-only; 1 = descriptive mention; 2 = positively recommended. Expose the underlying flags to distinguish absence from criticism. Quote evidence must exist verbatim in the answer. A citation-only domain reference is not an answer-body mention. Match parsed domain names exactly or through a dot-delimited subdomain, never substring matching.

Live eligible answers: successful, on-topic, search-grounded, validly evaluated. Exclude timeouts, missing grounding and needs-review records from the denominator. Display their counts explicitly.

Demo eligible answers: valid synthetic observations within the demo dataset, used only for **simulated** scores. Never mark `search_executed=true` on a fixture to satisfy live validation. Research snapshots do not have chatbot visibility scores unless independently imported, provenance-validated chatbot observations exist; use them for sourced company/context research only.

If n=0 return null, not zero. Every topic is small-sample; with too few eligible answers, flag insufficient evidence rather than a number.

Every question gets a score/explanation or failure card. Do not combine exploratory and baseline scores, or turn scores into causal claims.

## Acceptance checks

- App starts and completes both demo scenarios with no API keys and no internet.
- Three logical agent roles are implemented: onboarding, AnA and evaluation.
- Every query/topic has an explanation and traceable evidence/provenance.
- Synthetic data never appears under a real provider name or live timestamp.
- Search snapshots never masquerade as chatbot visibility measurements.
- Scores [2,1,0] give visibility 50; no eligible answers gives null.
- Negative mention, citation-only reference, ambiguous alias, deceptive domain, timeout and ungrounded answer cases behave correctly.
- Invalid evidence quotes are flagged; brand-leaking questions are rejected.
- Export/import preserves provenance, counts and baseline version.
- Arbitrary company input cannot silently receive the bundled company's report.
- App rerenders do not restart runs or issue requests.
- API secrets, if ever provided, are not logged, exported or committed.
- Local URL actually responds and the completed report can be reopened.

Use focused offline tests and one UI smoke journey per fixture. Report untested live adapters honestly. Do not weaken tests to make them pass.

