"""Human names for internal identifiers, for strings the engine builds and the UI prints verbatim.

The ids themselves never change — `np-4` stays `np-4` in the data, the JSON export and the saved
run. This module only decides how an id is *spoken*. Mirrors `web/src/labels.ts`, which does the
same job for identifiers the browser already has in hand.
"""
import re

from schemas import Evidence, Probe, Topic


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


def source_names(evidence: list[Evidence]) -> dict[str, str]:
    """`ev2` -> "Source 2 — notion.com/product", or the source type when there is no URL.

    Numbering follows the profile's own evidence order, so a source keeps its name across exports.
    """
    out = {}
    for i, e in enumerate(evidence, start=1):
        where = re.sub(r"^https?://(www\.)?", "", e.url) if e.url else e.source_type.replace("_", " ")
        out[e.id] = f"Source {i} — {where}"
    return out


def probe_names(probes: list[Probe], topics: list[Topic] = ()) -> dict[str, str]:
    """id -> "Buyer question 3 — Project tracking". Buyer questions carry their topic; brand ones have none."""
    label = {t.id: t.label for t in topics}
    return {p.id: probe_name(p) + (f" — {label[p.topic_id]}" if p.kind == "blind" and p.topic_id in label else "")
            for p in probes}


def with_ids(ids, names: dict[str, str]) -> str:
    """"Buyer question 3 — Project tracking (`pt-3`)": the name a reader needs, the id traceability needs."""
    return ", ".join(f"{names.get(i, i)} (`{i}`)" for i in ids)
