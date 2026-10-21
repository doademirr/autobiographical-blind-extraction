"""The temporal read: what both lineages observed era by era, where that changed, and what is only assumed to persist,
computed at `extract` and frozen in generation C.

A trait stated once and then taken for granted stops producing scenes, so its present verdicts thin out while it is
stable. Only both lineages' absent verdicts count against a construct; insufficient is silence. So:
- an era is `observed` when the construct is supported there (the same status every comparison reads), and
  `contradicted` when every lineage's three-way collapse is absent; otherwise nothing decisive happened;
- fades and emergences are transitions between decisive eras, skipping the rest;
- an undecided era after an observation is held by the ratchet assumption, kept apart from observations;
- `now` reads the last era under the ratchet (the recency rule), for the end of the written record, never for today.
Descriptive only: no rate, no gate.
"""

from collections.abc import Mapping, Sequence

__all__ = ["era_reading", "read", "trajectory"]


def era_reading(status: str, collapsed: Sequence[str | None]) -> str | None:
    """`observed`, `contradicted` or None, from the era's per-construct status and each lineage's three-way collapse."""
    if status == "supported":
        return "observed"
    if collapsed and all(v == "absent" for v in collapsed):
        return "contradicted"
    return None


def trajectory(readings: Mapping[str, str | None], era_ids: Sequence[str]) -> dict:
    """Fades, emergences, held eras and the current state, walking `era_ids` in order."""
    fades, emergences, held = [], [], []
    decisive: tuple[str, str] | None = None  # (reading, era) of the latest decisive era so far
    last_observed = None
    for era in era_ids:
        reading = readings[era]
        if reading is None:
            if decisive and decisive[0] == "observed":
                held.append(era)
            continue
        if decisive and decisive[0] != reading:
            (fades if reading == "contradicted" else emergences).append({"from": decisive[1], "to": era})
        decisive = (reading, era)
        if reading == "observed":
            last_observed = era
    final = era_ids[-1]
    if readings[final] == "observed":
        now = {"state": "observed", "era": final}
    elif final in held:
        now = {"state": "held", "era": last_observed}
    elif fades and decisive and decisive[0] == "contradicted":
        now = {"state": "faded", "era": fades[-1]["to"]}
    else:
        now = {"state": "never observed", "era": None}
    return {"eras": {era: readings[era] for era in era_ids}, "fades": fades, "emergences": emergences, "held": held,
            "now": now}


def read(constructs: Sequence[Mapping], status: Mapping[str, Mapping[str, str]],
         three_way: Mapping[str, Mapping[tuple[str, str], str | None]], era_ids: Sequence[str]) -> list[dict]:
    """One row per construct. `status` is {construct id: {era: status}}; `three_way` is each lineage's collapse of
    present, absent and insufficient, keyed by (item id, era)."""
    rows = []
    for con in constructs:
        readings = {era: era_reading(status[con["id"]][era],
                                     [three_way[lin][(con["item_id"], era)] for lin in sorted(three_way)])
                    for era in era_ids}
        rows.append({"construct_id": con["id"], **trajectory(readings, era_ids)})
    return rows
