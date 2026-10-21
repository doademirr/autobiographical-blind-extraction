"""The three-way map: where the blind extraction, the user's self-view and the questionnaire meet on the IPIP-NEO
facets, computed at `unmask`.

Each side gets a pole per facet (high, low, `conflict` or none):
- blind: the supported constructs the facet map links to the facet, and the observer facet estimate's band. A
  construct conflict is never hidden by the estimate.
- self: the predictions both crosswalk coders tag to the facet with the same polarity; a tag the coders don't share
  is ambiguous and placed nowhere.
- test: the IPIP facet band (never a conflict).
Divergence is checked first, so any opposite pair or conflict is divergent whatever else agrees. Descriptive only:
constructs give directions on facets, never scores.
"""

from collections.abc import Mapping
from fractions import Fraction

from . import ipip

__all__ = ["CLASSES", "blind_pole", "build_map", "classify", "pole", "prediction_facets"]

CLASSES = ("divergent", "all three", "blind and self", "blind only", "self only", "test only")
_POLE_OF = {"+": "high", "-": "low"}


def pole(polarities: list[str]) -> str | None:
    """The shared pole of `+`/`-` directions, `conflict` when they disagree, None when there are none."""
    poles = {_POLE_OF[p] for p in polarities}
    return None if not poles else poles.pop() if len(poles) == 1 else "conflict"


def blind_pole(inductive: str | None, observer_band: str | None) -> str | None:
    """The parts' shared pole, either part's pole, or none; `conflict` when they differ. A construct conflict differs
    from any observer pole and survives an observer without one, so it is never hidden."""
    deductive = observer_band if observer_band in ("high", "low") else None
    if inductive and deductive and inductive != deductive:
        return "conflict"
    return inductive or deductive


def classify(blind: str | None, self_: str | None, test: str | None) -> str | None:
    """The facet's class, divergence first; None when no side has anything."""
    sides = [s for s in (blind, self_, test) if s is not None]
    if not sides:
        return None
    if "conflict" in sides or len(set(sides)) > 1:
        return "divergent"
    if blind and self_:
        return "all three" if test else "blind and self"
    return "blind only" if blind else "self only" if self_ else "test only"


def prediction_facets(tags: Mapping[str, list[dict]]) -> tuple[dict[str, list[dict]], list[dict]]:
    """Per facet, the predictions every coder tagged to it with the same polarity; and the (prediction, facet) tags
    the coders don't share."""
    by_coder = {coder: {(p["prediction_id"], f["facet"]): f["polarity"] for p in rows for f in p["facets"]}
                for coder, rows in tags.items()}
    keys = sorted(set().union(*by_coder.values())) if by_coder else []
    agreed: dict[str, list[dict]] = {}
    ambiguous = []
    for pid, facet in keys:
        given = {coder: table.get((pid, facet)) for coder, table in by_coder.items()}
        if len(set(given.values())) == 1:
            agreed.setdefault(facet, []).append({"prediction_id": pid, "polarity": given.popitem()[1]})
        else:
            ambiguous.append({"prediction_id": pid, "facet": facet})
    return agreed, ambiguous


def _num(value: Fraction | None) -> float | None:
    return None if value is None else float(value)


def build_map(facet_map: Mapping[str, list[dict]], supported: set[str], observer: Mapping[str, Fraction | None],
              ipip_facets: Mapping[str, Fraction | None], tags: Mapping[str, list[dict]], reportable: bool) -> dict:
    """Every facet any side speaks to, with each side's evidence and pole, ordered by class then facet code."""
    agreed, ambiguous = prediction_facets(tags)
    rows = []
    for facet in sorted(ipip_facets):
        constructs = [{"construct_id": cid, "polarity": f["polarity"]} for cid in sorted(supported)
                      for f in facet_map.get(cid, []) if f["facet"] == facet]
        inductive = pole([c["polarity"] for c in constructs])
        o_band = ipip.observer_band(observer.get(facet))
        predictions = agreed.get(facet, [])
        t_band = ipip.ipip_band(ipip_facets[facet])
        sides = {"blind": blind_pole(inductive, o_band), "self": pole([p["polarity"] for p in predictions]),
                 "test": t_band if t_band in ("high", "low") else None}
        kind = classify(sides["blind"], sides["self"], sides["test"])
        if kind is None:
            continue
        rows.append({"facet": facet, "class": kind, "constructs": constructs, "inductive": inductive,
                     "observer": _num(observer.get(facet)), "observer_band": o_band, "predictions": predictions,
                     "ipip": _num(ipip_facets[facet]), "ipip_band": t_band, **sides})
    rows.sort(key=lambda r: (CLASSES.index(r["class"]), r["facet"]))
    return {"rows": rows, "counts": {c: sum(r["class"] == c for r in rows) for c in CLASSES},
            "ambiguous": ambiguous, "inductive_reportable": reportable}
