"""Human names for internal identifiers, for strings the engine builds and the UI prints verbatim.

The ids themselves never change — `np-4` stays `np-4` in the data, the JSON export and the saved
run. This module only decides how an id is *spoken*. Mirrors `web/src/labels.ts`, which does the
same job for identifiers the browser already has in hand; tests/test_labels.py runs both and fails
when their words differ.
"""
import re

from schemas import Probe


PROVENANCE_LABEL = {"synthetic": "Sample data", "demo_replay": "Sample run",
                    "live_api": "Measured live", "page_fetch": "From their website",
                    "counterfactual_replay": "Experiment — a replayed reading list, not a measurement",
                    "user_provided": "You told us", "web_research_snapshot": "Research snapshot"}



def probe_name(probe: Probe) -> str:
    """`np-4` -> "Branded question 4", `kb-2` -> "Unbranded question 2", a front's control question
    -> "Control question".

    The number comes from the id, not from a list position, so the same question is called the same
    thing on every screen and in every rerender. The comparison question is the one probe
    that is not an nth of anything — there is exactly one per run — so it is named, not numbered.
    """
    m = re.search(r"(\d+)$", probe.id)
    n = m.group(1) if m else "?"
    if probe.kind == "named":
        return "Comparison question" if probe.phase == "followup" else f"Branded question {n}"
    if probe.phase == "control":
        return "Control question"
    return f"Unbranded question {n}"
