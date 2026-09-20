# DEMO.md — two-minute presenter script

Setup beforehand: `conda activate visexp && python -m streamlit run app.py --server.port 8501`,
open http://localhost:8501, leave Scenario A selected. Everything is synthetic; say so once, up front.

**0:00 — the question (15s)**

> "Everyone measures whether AI mentions your brand. That is the easy question. The harder one is:
> when AI *does* talk about you, is it describing the company you are trying to be?"

**0:15 — what Notion wants to own (15s)**

Point at the four intended attributes on the setup screen. Note the third column: how much of their own
site actually states each one. Enterprise-ready is at 12% — they told us they want it, their copy barely says it.

**0:30 — run it (10s)**

Click **Measure drift**. Call out the stages as they stream: the named probes are answered, attribute
observations are extracted and validated, then classified. Real graph transitions, fixture-backed nodes.

**0:40 — the number (20s)**

> "Alignment 21%. Of everything Notion wants to be known for, AI echoes about a fifth of it."

One landed, two lost claims, one never stated, three imposed.

**1:00 — the drift map (30s)**

Grey bars are what they claim, coloured bars are what AI says. The asymmetry is the product:

- Long grey, no colour → they say it, AI ignores it
- No grey, long colour → AI says it, they never claimed it

> "Notion wants to be an AI-native workspace that replaces your tool stack. AI thinks it is a pretty
> note-taking app that is hard to learn."

**1:30 — whose problem is it (20s)**

This is the part a forward-deployed engineer gets paid for:

- **AI-native workspace** — stated on 75% of their pages, echoed in 1 of 8 answers. **Authority gap.**
  Their message is not reaching the models. That is the Profound-shaped problem.
- **Enterprise ready** — stated on 12% of pages, echoed 0 times. **Messaging gap.** Not an AI problem.
  No amount of crawling fixes a claim they never made. Saying this out loud is what earns trust.

**1:50 — prove it is not a slideshow (10s)**

Switch to **Scenario B**, click Measure drift. Alignment moves to 31% and "connected docs and databases"
flips from landed to lost. Different fixture data, different diagnosis — the policy reads the evidence.

**Close**

Open **How do you know?** — every named question asked, every answer, the limitations, the full workflow
log. Nothing on the screen is unsourced.

**If asked what is real:** the workflow, the validation, the arithmetic and the routing are real code.
The answers are authored fixtures. No model was called; there are no API keys in this build.
