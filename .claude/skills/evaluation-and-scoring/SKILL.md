---
name: evaluation-and-scoring
description: Load when changing agents/evaluation.py, scoring.py, gap findings, the suggested-action table, or the offline acceptance tests. Per-query evaluation rules, scoring formulas, gap-to-action mapping and the acceptance checklist.
---

# Evaluation, scoring, suggested actions and acceptance checks

Moved verbatim from agents.md sections 4, 6 and 10. Where this disagrees with the code, README.md or WEB.md, the code wins: it was written for the first overnight build, before the React app, the drift layer and live mode existed.

## 4. Suggested next steps

Keep this mapping as a small reviewed configuration table (`ACTIONS` in `agents/evaluation.py`). It names no vendor or product.

| Observed issue | Suggested next step |
| --- | --- |
| Company absent in a relevant topic while competitors appear | Track a wider fixed prompt set over time to assess whether the gap persists |
| Competitors repeatedly appear in cited pages | Inspect frequently cited sources and identify coverage the customer lacks |
| Relevant questions lack useful company-owned content | Review owned pages and propose an evidence-backed brief for the uncovered questions |
| Answers repeat outdated or inaccurate product facts | Compare the claim with current authoritative facts and investigate cited sources |
| Brand is mentioned but poorly matched to a specific use case | Examine how the brand is described and whether product-fit evidence is clear |

Do not label a content gap “confirmed” unless the relevant company pages were examined. Citations alone do not prove why a model chose a brand. Where evidence is insufficient, say what additional research is needed.

Every finding includes: topic, observation, probe/evidence IDs, fit evidence, interpretation, suggested action, limitations, and provenance.

## 6. Evaluations and scoring

Per-query strength: 0 = absent or negative-only; 1 = descriptive mention; 2 = positively recommended. Expose the underlying flags to distinguish absence from criticism. Quote evidence must exist verbatim in the answer. A citation-only domain reference is not an answer-body mention. Match parsed domain names exactly or through a dot-delimited subdomain, never substring matching.

Live eligible answers: successful, on-topic, search-grounded, validly evaluated. Exclude timeouts, missing grounding and needs-review records from the denominator. Display their counts explicitly.

Demo eligible answers: valid synthetic observations within the demo dataset, used only for **simulated** scores. Never mark `search_executed=true` on a fixture to satisfy live validation. Research snapshots do not have chatbot visibility scores unless independently imported, provenance-validated chatbot observations exist; tonight use them for sourced company/context research only.

For each topic and phase separately:

```text
n = eligible observations in that mode/phase
mention_rate = mentions / n
recommendation_rate = recommendations / n
citation_rate = owned_domain_citations / n
visibility_score = 100 * sum(strength) / (2*n)
competitor_rate = answers_recommending_a_competitor_and_never_mentioning_the_brand / n
fit_weight = strong:1.0, partial:0.5, unsupported:0.0
gap_priority = 100 * fit_weight * (1-recommendation_rate) * competitor_rate
```

If n=0 return null, not zero. Label priority “heuristic investigation priority,” not revenue potential. Every topic is small-sample. With fewer than three eligible baseline answers, flag insufficient evidence and omit priority ranking. With three: 3 recommendations = observed presence; 1–2 = mixed; 0 plus strong fit and competitors in at least two answers = candidate gap; otherwise unclear.

Every question gets a score/explanation or failure card. Every topic gets counts, rates, evidence, fit, limitations and suggested next action. Every positioning point gets mapped topic results or “not tested.” Do not combine adaptive and baseline scores, or turn scores into causal claims.

## 10. Acceptance checks

- App starts and completes both demo scenarios with no API keys and no internet.
- Three logical agent roles are implemented and visible in the workflow.
- Adaptive selection changes when the fixture results change.
- Baseline remains unchanged after follow-up execution.
- Every query/topic has an explanation and traceable evidence/provenance.
- Every gap suggests a mapped next step, or states insufficient evidence.
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

