# VinayDemo — Positioning Drift

You take a company, and an agentic workflow runs a research methodology that shows how different
AIs perceive that company, from what they can see on the internet, against what the company wants
to be. That gap is the product. Everything else serves it.

## Three layers, never merged

- **Intended** — what the company wants to be known for. Stated by the customer, aspirational, never
  counted as product fit.
- **Claimed** — what its own public pages actually say. Evidence-backed, with verbatim quotes.
- **Perceived** — what AI says when asked. Measured by probes.

Claimed vs perceived is an *authority gap* (they say it, AI does not repeat it). Intended vs claimed
is a *messaging gap* (AI does not say it because they never clearly did). Naming which one is the point.

## Two probe families, never leaking into each other

- **Blind (buyer) probes** never name the brand, its aliases, its domain or the vendor ("your
  platform") → measure **visibility**. A blind probe that names the brand has already answered
  itself.
- **Named (brand) probes** name the brand but never the attribute being measured → measure
  **perception**. A named probe that names the attribute invites the model to agree.

Leaks are rejected in code (`agents/ana.py`: `attribute_leaks`, `vendor_address`, `brand_leaks`).
The measured model gets only the neutral question in a fresh context, never the company
profile.

## Authored evidence is never presented as measured

Every record carries its provenance (`synthetic`, `web_research_snapshot`, `live_api`). Fixture
answers are replays, labelled as such everywhere they appear; a web-search snapshot is company
research, never a chatbot visibility score; provenances are never pooled into one metric. Without a
key, live mode errors rather than falling back to fixtures. Arithmetic lives in code, quotes must be
verbatim in the answer they cite, and nothing is invented to fill a gap.

## Where things are

- Run, test, layout: `README.md`. API, live mode, offline fallback, views, wording: `WEB.md`.
  Presenter script: `DEMO.md`. Tests: `python -m pytest -q`.
- Detailed rules load on demand from `.claude/skills/`: `product-workflow` (agents, graph, state),
  `evidence-modes` (providers, provenance, budgets), `evaluation-and-scoring` (scoring, Profound
  mapping, acceptance checks), `build-history` (the original overnight brief and milestone log).
- Independent portfolio demo — not a Profound product or integration.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
