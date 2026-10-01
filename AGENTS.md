# VinayDemo — Off Message

You take a company, and an agentic workflow runs a research methodology that shows how different
AIs perceive that company, from what they can see on the internet, against what the company wants
to be. That gap is the product. Everything else serves it.

## Three layers, never merged

- **Intended** — what the company wants to be known for. Stated by the customer, aspirational, never
  counted as product fit.
- **Claimed** — what its own public pages actually say. Evidence-backed, with verbatim quotes. Read
  directly, or as a dated search copy when the site turns us away, plus documents it uploads
  (private: a claim only there is a messaging gap). Third-party pages are kept apart, never claimed.
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
The measured model gets only the neutral question in a fresh context, never the company profile.
`run.answers` holds one answer per probe; re-asks live in `run.repeat_answers`. Reused answers
(`sharing.py`, planned on the graph thread) never count twice. The why agent's and fleet's replays are
`counterfactual_replay`, kept in their own record, never scored. Only the graph thread writes a run, in
`graph.canonical` order. A thread pool must copy the context in the submitting thread (`access.pmap`,
or `pool.submit(copy_context().run, ...)`), or the paying pass and purse are lost. Every live ask
forces web search (`live.TOOL_CHOICE`) and retries once when none ran. Settings: WEB.md "Live mode".

## Authored evidence is never presented as measured

Every record carries its provenance (`synthetic`, `web_research_snapshot`, `live_api`,
`counterfactual_replay`). Fixture answers are replays, labelled as such everywhere they appear; a
web-search snapshot is company research, never a chatbot visibility score; provenances are never
pooled into one metric. Without a key, live mode errors rather than falling back to fixtures.
Arithmetic lives in code, quotes must be verbatim in the answer they cite, and nothing is invented to
fill a gap.

## Where things are

- Run, test, layout: `README.md`. API, live mode, offline fallback, views, wording: `WEB.md`.
  Presenter script: `DEMO.md`. Tests: `python -m pytest -q`.
- Detailed rules load on demand from `.claude/skills/`: `product-workflow` (agents, graph, state),
  `evidence-modes` (providers, provenance, budgets), `evaluation-and-scoring` (scoring, acceptance
  checks).
- Tests never touch the network: `audit.py` (the no-model site check) fetches only through
  `audit.get`, which `tests/conftest.py` refuses unless a test records responses.
- Every OpenAI call goes through `access.openai_response` (embeddings: `access.openai_embedding`,
  via `demand.py` and `embeddings.py`): it refuses at an access pass's cap, charges the pass from
  reported usage, and fails closed on the public demo when no pass is set. A new model call site
  must use it. Passes, admin and hosting: WEB.md "Deploy to Render".
- Independent portfolio demo.

## Keep it small

Before adding a module, option, env setting, schema field or doc section, check that something reads it;
delete what nothing reads in the same PR. Prefer a parametrized row to a new test function, and a pointer to the
docstring over restating it in WEB.md. CI prints each PR's net lines per area; say why in the PR when it is large.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
