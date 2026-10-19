"""IPIP-NEO-120 scoring (SPEC § Data Model, IPIP) and the band rule shared with observer scores.

Means and band boundaries are exact fractions: a domain mean of exactly 11/3 must land in the
same band on every Python version, which float sums do not guarantee.
"""

import csv
import io
from fractions import Fraction
from pathlib import Path

from . import store
from .errors import UsageError

__all__ = ["DOMAIN_MIN_FACETS", "FROZEN_COPY", "INSTRUMENT", "IPIP_HIGH", "IPIP_LOW", "OBSERVER_HIGH", "OBSERVER_LOW",
           "ipip_band", "load_instrument", "mean", "observer_band", "parse_responses", "score"]

INSTRUMENT = Path(__file__).resolve().parents[2] / "instruments" / "ipip-neo-120.json"

FACET_MIN_ITEMS = 3
DOMAIN_MIN_FACETS = 4
IPIP_LOW, IPIP_HIGH = Fraction(7, 3), Fraction(11, 3)
OBSERVER_LOW, OBSERVER_HIGH = Fraction(3), Fraction(5)
FROZEN_COPY = "prereg/instrument/ipip-neo-120.json"


def load_instrument(ws: store.Workspace | None = None) -> dict:
    """The workspace's frozen copy when given a workspace, else the repository's."""
    return store.read_json(ws.path(FROZEN_COPY) if ws else INSTRUMENT)


def parse_responses(csv_text: str, instrument: dict) -> dict[str, int | None]:
    """`item_id,response` rows; a blank response is missing. Every item must appear once."""
    ids = {i["id"] for i in instrument["items"]}
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows or [c.strip() for c in rows[0]] != ["item_id", "response"]:
        raise UsageError("ipip-120.csv: the header must be exactly item_id,response")
    out: dict[str, int | None] = {}
    for number, row in enumerate(rows[1:], start=2):
        if not row:
            continue
        if len(row) != 2:
            raise UsageError(f"ipip-120.csv line {number}: expected exactly two cells")
        item, raw = row[0].strip(), row[1].strip()
        if item not in ids or item in out:
            raise UsageError(f"ipip-120.csv line {number}: unknown or repeated item id")
        if raw and raw not in {"1", "2", "3", "4", "5"}:
            raise UsageError(f"ipip-120.csv line {number}: the response must be 1-5 or blank")
        out[item] = int(raw) if raw else None
    if set(out) != ids:
        raise UsageError(f"ipip-120.csv: {len(ids - set(out))} items missing")
    return out


def mean(values: list) -> Fraction:
    return Fraction(sum(Fraction(v) for v in values), len(values))


def score(responses: dict[str, int | None], instrument: dict) -> dict:
    """Facet means (negative keys reversed) and domain means, each missing below its minimum."""
    by_facet: dict[str, list[int]] = {f: [] for f in instrument["facets"]}
    for item in instrument["items"]:
        r = responses.get(item["id"])
        if r is not None:
            by_facet[item["facet"]].append(r if item["key"] == 1 else 6 - r)
    facets = {f: (mean(v) if len(v) >= FACET_MIN_ITEMS else None) for f, v in by_facet.items()}
    domains = {}
    for d in instrument["domains"]:
        present = [s for f, s in facets.items() if f.startswith(d) and s is not None]
        domains[d] = mean(present) if len(present) >= DOMAIN_MIN_FACETS else None
    return {"facets": facets, "domains": domains}


def ipip_band(value: Fraction | None) -> str | None:
    if value is None:
        return None
    return "low" if value <= IPIP_LOW else "high" if value >= IPIP_HIGH else "mid"


def observer_band(value: Fraction | None) -> str | None:
    if value is None:
        return None
    return "low" if value <= OBSERVER_LOW else "high" if value >= OBSERVER_HIGH else "mid"
