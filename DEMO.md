# Two-minute demo script

Setup beforehand: `conda activate visexp && python -m streamlit run app.py --server.port 8501`, open
http://localhost:8501, click **Reset to original sample** in the sidebar.

**0:00 — Frame it (15s).** "Visibility Explorer finds the buyer questions where a brand is missing from AI answers.
Everything you'll see runs locally; the yellow banner is permanent — the answers are synthetic fixtures, not live
chatbot measurements."

**0:15 — Company setup (25s).** Click **Load Notion demo**. "Agent 1, Onboarding, establishes what the company
actually offers. These positioning points are backed by verbatim excerpts from notion.com, captured as a research
snapshot — green 'sourced' badges, with URLs and retrieval dates. pp5 has no topic, so it's reported as *not tested*."
Scroll to the four topic cards. Tick **I reviewed…**, click **Explore visibility**.

**0:40 — Investigation (30s).** Click **Run demo replay**. "These are real LangGraph transitions. Agent 2, AnA, plans
four topics with three neutral questions each — the brand name, domains and branded features are blocked from the
questions — and the baseline is frozen and hashed. Agent 3 evaluates each answer, then AnA reads those evaluations
and picks up to two topics for one follow-up round." Point at the decision log: project tracking (candidate gap) and
meeting docs (mixed), each citing the probe IDs that motivated it.

**1:10 — Feedback-dependence (15s).** Sidebar → **Scenario B**, **Run demo replay** again. "Different fixture
results, different choice: personal organization and knowledge bases. It's a policy over the evaluations, not an
animation."

**1:25 — Gap report (30s).** **View gap report →**. Show the baseline table ("simulated score", "heuristic
investigation priority — not revenue"). Open a personal-organization question: verbatim quote, flags, lookalike-domain
and ambiguous-alias warnings. Tab **Where Profound could help**: candidate gap → Answer Engine Insights; a
possibly outdated 'offline-limited' claim → FactCheck; content gap explicitly *not confirmed* because owned pages
weren't examined. **Exploratory follow-ups** tab: never merged into baseline.

**1:55 — Close (5s).** **Download Markdown report**. "Every record carries its provenance, and the next step is
swapping the fixture provider for a live, search-grounded one behind the same interface."
