---
name: evidence-modes
description: Load when touching providers/ (fixture replay, imported research snapshots, live API), provenance labels, API keys, or doing development-time web research on a company. Rules for what each evidence source may and may not claim, and live/research budgets.
---

# Evidence modes, provenance and budgets

Moved verbatim from agents.md section 2 and the execution limits in section 8. Where this disagrees with the code, README.md or WEB.md, the code wins: it was written for the first overnight build, before the React app, positioning drift and live mode existed.

## 2. No-key execution: three explicitly different modes

| Mode | Source | What works | Required label |
| --- | --- | --- | --- |
| Demo replay — default | Authored deterministic fixtures | Entire interactive workflow, graph routing, scores, follow-up selection, report and exports | Synthetic demo; no live chatbot measurements |
| Research snapshot — optional | Claude Code's available WebSearch/WebFetch tools during development; saved source records imported into app | Real company research and a saved search snapshot | Claude Code research snapshot; not cross-model chatbot visibility |
| Live API — optional adapter | Explicitly configured official provider API | Fresh neutral probes and model-powered agent decisions | Actual provider/model, timestamp, grounding status |

### Rules for free calls and Claude Code research

- Do not assume a free unauthenticated LLM endpoint exists. Free tiers may still need accounts, API keys, quotas and tool-specific billing. Do not waste tonight hunting for random endpoints.
- Claude Code may expose WebSearch/WebFetch depending on session configuration and permissions. Check tool availability and use them for bounded development-time research if available. They are not guaranteed free/unlimited and are not automatically callable from the Streamlit application.
- Claude Code can research the company, propose a profile/topics, and save structured outputs without a separate application API key. Those are prepared snapshots, not live autonomous app runs.
- A web-search result is not evidence that ChatGPT, Gemini, or Perplexity recommended a brand. Never convert search rankings/snippets into chatbot mention scores.
- This coding session already knows the target company; any answers it authors must not be represented as blind visibility measurements. Use such answers only as labeled illustrative fixtures.
- Do not call the Claude CLI from the app, reuse subscription session tokens as API credentials, automate consumer chatbot logins, or bypass permissions. Runtime CLI integration is out of scope.
- If tools or network access are unavailable, finish the fixture-based application anyway.
- If a genuine free-tier key is supplied later, verify current official docs and enable that provider through environment variables. Do not invent successful calls or hide rate-limit failures.

### Making the demo honest and useful

Every displayed record carries provenance. Show a permanent mode banner, add mode labels to exports and screenshots, and never label fixture results “live.” Simulated baseline and adaptive results may demonstrate the intended product behavior, but the app must state that model judgment is simulated in replay mode.

For arbitrary companies with no key: allow pasted facts and manual profile/topic edits, then show a research plan. Do not reuse Notion answers under a different company's name. Only bundled companies have replay results. Explain when generating new answers requires credentials or an imported research file.


### Execution limits (from section 8)

Live adapter, only if credentials are supplied: one official search-capable provider; configurable model; fresh probe context; max 16 unique probes, 4 extra probe retries, 40 total model attempts including internal decisions and repairs, concurrency 3, 25-second per-call timeout, 240-second investigation deadline. No automatic paid checks overnight. Track actual usage if available; do not invent dollar costs.

Research within Claude Code: at most 12 search/fetch operations for company and product context. Stop when the demo has enough supporting material. If tools fail or require unavailable authorization, record the limitation and continue offline; do not bypass access controls.
