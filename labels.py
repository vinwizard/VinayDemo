"""Human names for internal identifiers, for strings the engine builds and the UI prints verbatim.

The ids themselves never change — `np-4` stays `np-4` in the data, the JSON export and the saved
run. This module only decides how an id is *spoken*. Mirrors `web/src/labels.ts`, which does the
same job for identifiers the browser already has in hand.
"""
import re

from schemas import Probe


def probe_name(probe: Probe) -> str:
    """`np-4` -> "Brand question 4", `kb-2` -> "Buyer question 2", `kb-f1` -> "Follow-up question 1".

    The number comes from the id, not from a list position, so the same question is called the same
    thing on every screen and in every rerender.
    """
    m = re.search(r"(\d+)$", probe.id)
    n = m.group(1) if m else "?"
    if probe.kind == "named":
        return f"Brand question {n}"
    if probe.phase == "followup":
        return f"Follow-up question {n}"
    return f"Buyer question {n}"
