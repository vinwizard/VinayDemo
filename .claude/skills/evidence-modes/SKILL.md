---
name: evidence-modes
description: Load when touching providers/ (fixture replay, live API), provenance labels, API keys, or doing development-time web research on a company. Rules for what each evidence source may and may not claim, and live/research budgets.
---

# Evidence modes, provenance and budgets

From the original brief. Where this disagrees with the code, README.md or WEB.md, the code wins.

## Three explicitly different modes

| Mode | Source | What works | Required label |
| --- | --- | --- | --- |
| Demo replay — default | Authored deterministic fixtures | Entire interactive workflow, graph routing, scores, report and exports | Synthetic demo; no live chatbot measurements |
| Research snapshot — optional | Claude Code's available WebSearch/WebFetch tools during development; saved source records | Real company research and a saved search snapshot | Claude Code research snapshot; not cross-model chatbot visibility |
| Live API — optional adapter | Explicitly configured official provider API | Fresh neutral probes and model-powered agent decisions | Actual provider/model, timestamp, grounding status |

### Rules for free calls and Claude Code research

- Do not assume a free unauthenticated LLM endpoint exists. Free tiers may still need accounts, API keys, quotas and tool-specific billing. Do not hunt for random endpoints.
- Claude Code may expose WebSearch/WebFetch depending on session configuration and permissions. Check tool availability and use them for bounded development-time research if available. They are not guaranteed free/unlimited and are not callable from the app.
- Claude Code can research the company, propose a profile/topics, and save structured outputs without a separate application API key. Those are prepared snapshots, not live autonomous app runs.
- A web-search result is not evidence that ChatGPT, Gemini, or Perplexity recommended a brand. Never convert search rankings/snippets into chatbot mention scores.
- This coding session already knows the target company; any answers it authors must not be represented as blind visibility measurements. Use such answers only as labeled illustrative fixtures.
- Do not call the Claude CLI from the app, reuse subscription session tokens as API credentials, automate consumer chatbot logins, or bypass permissions. Runtime CLI integration is out of scope.
- Do not invent successful calls or hide rate-limit failures.

### Making the demo honest and useful

Every displayed record carries provenance. Show a permanent mode banner, add mode labels to exports and screenshots, and never label fixture results “live.” A why-agent replay (`counterfactual_replay`) is an experiment on a reading list the model really read, never a measurement; copy it edits or injects that is not a page's own verbatim text is labelled hypothetical wherever it appears. A fleet's plan cites those replays as predictions; its verifier's live asks after a fix is published are `live_api` but live only in a `Verification` record, never on a run or in a score, and are shown beside the prediction, never pooled with it. Simulated results may demonstrate the intended product behavior, but the app must state that model judgment is simulated in replay mode. No fake provider latency, token bills or live-status indicators: `VISEXP_DEV_DELAY` is a development aid only, off by default, and never implies a provider was called.

Do not reuse Notion answers under a different company's name. Only bundled companies have replay results.

### Onboarding sources: what may count as claimed

Claimed means the company's own words, so what onboarding reads keeps its kind on `Evidence.source_type`
all the way to the report (WEB.md "Onboarding", `discovery.py`, `documents.py`):

- `page_fetch`: its own page, read directly. `search_copy`: its own page as a search engine saved it,
  with its age, used only when the page will not let us read it. Both count as claimed.
- An own page is on the confirmed domain or a subdomain AND names the company, decided in code; a URL
  counts only if a search result actually returned it, never because the model listed it.
- `uploaded_document`: the company's own words, but private (`Evidence.private`). A claim found only
  there is `private_only`: AI cannot read it, so its gap is a messaging gap, never an authority gap.
- `third_party` (Wikipedia, news, forums): stored apart on `Company.third_party`, shown, never
  extracted, never counted as claimed and never pooled with anything that is.
- A web search that finds the company is not a measurement of anything: it is not a chatbot
  visibility result and never feeds a score.

### Execution limits

Live adapter, only if credentials are supplied: one official search-capable provider; configurable model; fresh probe context. The live limits and budgets are in WEB.md ("Live mode"). No automatic paid checks. Track actual usage if available; do not invent dollar costs.

Research within Claude Code: at most 12 search/fetch operations for company and product context. Stop when the demo has enough supporting material. If tools fail or require unavailable authorization, record the limitation and continue offline; do not bypass access controls.
