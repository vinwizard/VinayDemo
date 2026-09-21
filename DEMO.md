# DEMO.md — two-minute presenter script

Setup beforehand: start the API with `VISEXP_OFFLINE_REPLAY=1` and the React app as in
[`README.md`](README.md), and open http://localhost:5173 on the Notion tab. With that variable the
Notion run replays the first bundled scenario (Notion, scenario A), and the numbers below are its.
Everything is synthetic; say so once, up front. Without the variable the same tab measures live, and
the numbers will differ.

The page does not offer the second scenario, so run it once from the API before the demo; it lands
in History:

```bash
curl -sN 'http://127.0.0.1:8000/api/stream?scenario=B&mode=demo' > /dev/null
```

**0:00 — the question (15s)**

> "Everyone measures whether AI mentions your brand. That is the easy question. The harder one is:
> when AI *does* talk about you, is it describing the company you are trying to be?"

**0:15 — what Notion wants to own (15s)**

Point at Notion's intended attributes before anything runs, and at how much of their own site actually
states each one. Enterprise-ready is at 12% — they told us they want it, their copy barely says it.

**0:30 — run it (10s)**

Start the measurement. Call out the stages as they complete: each brand and buyer question is answered
one by one, the observations are extracted and validated, then classified. Real graph transitions,
fixture-backed nodes.

**0:40 — the number (20s)**

> "Alignment 21%. Of everything Notion wants to be known for, AI echoes about a fifth of it."

The number stays pinned at the top of the report while you move between its tabs. Walk the zone
counts on the Overview: what landed, what was lost, what they never stated, what AI imposed.

**1:00 — the claim cards (30s)**

Each claim card shows what they claim beside what AI says; tap one to open its drawer with the
site's quotes, what AI said and its win-back fix. The asymmetry is the product:

- Strong claim, no echo → they say it, AI ignores it
- No claim, strong echo → AI says it, they never claimed it

> "Notion wants to be an AI-native workspace that replaces your tool stack. AI thinks it is a pretty
> note-taking app that is hard to learn."

**1:30 — whose problem is it (20s)**

This is the part a forward-deployed engineer gets paid for:

- **AI-native workspace** — stated on 75% of their pages, echoed in 1 of 8 answers. **Authority gap.**
  Their message is not reaching the models. That is the Profound-shaped problem.
- **Enterprise ready** — stated on 12% of pages, echoed 0 times. **Messaging gap.** Not an AI problem.
  No amount of crawling fixes a claim they never made. Saying this out loud is what earns trust.

**1:50 — prove it is not a slideshow (10s)**

Open the second scenario's run from History. Alignment moves to 27.9% and "connected docs and databases"
flips from landed to lost. Different fixture data, different diagnosis — the policy reads the evidence.
If there is time, put the two runs side by side in the comparison view to show the per-attribute moves.

**Close**

Open the evidence behind the report — the Buyer and Brand questions tabs hold every question asked
and every answer; the Overview ends with the limitations and the workflow log. Nothing on the screen is unsourced.

**If asked what is real:** the workflow, the validation, the arithmetic and the routing are real code.
The answers in both scenarios are authored fixtures; no model was called for them. Live measurement
against a real model exists and needs an `OPENAI_API_KEY` — see [`WEB.md`](WEB.md).
