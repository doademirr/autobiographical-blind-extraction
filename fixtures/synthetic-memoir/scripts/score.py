"""Score a finished workspace against the sealed key (plan: Scoring rules, pre-registered).

Usage: score.py <repo> <workspace> <mapping-a.json> <mapping-b.json> [<out.json>]
A mapping file is {"constructs": {"<construct id>": {"trait": "<id>", "orientation": "same"|"inverse"} | null}},
made from codebook definitions alone before any status is read. Only constructs both mappings agree on count.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = json.loads((ROOT / "key/key.json").read_text())
ERAS = [e["id"] for e in KEY["eras"]]
STABLE = ("T1", "T2", "T3", "T10")
TRANSITIONS = {"T4": ("e3", "e4", "fade"), "T5": ("e2", "e3", "fade"), "T6": ("e3", "e4", "emergence"),
               "T7": ("e2", "e3", "emergence")}
SILENT = ("T0", "N1")
PAIR = {"fade": ("observed", "contradicted"), "emergence": ("contradicted", "observed")}


# --- matching ---

def agreed(a: dict, b: dict) -> tuple[dict, list[str]]:
    """Constructs both matchers map identically (trait and orientation); every disagreement is listed and counts
    as unmapped."""
    out, disputed = {}, []
    for cid in sorted(set(a) | set(b)):
        x, y = a.get(cid), b.get(cid)
        if x == y and x is not None:
            out[cid] = (x["trait"], x["orientation"])
        elif x != y:
            disputed.append(cid)
    return out, disputed


# --- reading a trait in an era (the decision table) ---

def reading(trait: str, era: str, mapping: dict, temporal: dict) -> str:
    """`observed`, `contradicted`, `conflict` or `undecided`; `unrecovered` when no construct maps to the trait.
    `temporal` is {construct id: {era: "observed" | "contradicted" | None}}."""
    same = [c for c, (t, o) in mapping.items() if t == trait and o == "same"]
    inverse = [c for c, (t, o) in mapping.items() if t == trait and o == "inverse"]
    if not same and not inverse:
        return "unrecovered"
    same_obs = any(temporal[c].get(era) == "observed" for c in same)
    inv_obs = any(temporal[c].get(era) == "observed" for c in inverse)
    if same_obs and inv_obs:
        return "conflict"
    if same_obs:
        return "observed"
    if inv_obs:
        return "contradicted"
    if same and all(temporal[c].get(era) == "contradicted" for c in same):
        return "contradicted"
    return "undecided"


def readings(trait: str, mapping: dict, temporal: dict) -> dict[str, str]:
    return {e: reading(trait, e, mapping, temporal) for e in ERAS}


# --- checks ---

def stable(mapping, temporal) -> dict:
    rows = {t: sum(r == "observed" for r in readings(t, mapping, temporal).values()) for t in STABLE}
    passed = [t for t, n in rows.items() if n >= 5]
    return {"eras_observed": rows, "passed": passed, "score": f"{len(passed)}/4", "pass": len(passed) >= 3}


def transitions(mapping, temporal) -> dict:
    rows = {}
    for t, (before, after, kind) in TRANSITIONS.items():
        r = readings(t, mapping, temporal)
        rows[t] = {"kind": kind, "boundary": f"{before}->{after}", "read": (r[before], r[after]),
                   "pass": (r[before], r[after]) == PAIR[kind]}
    n = sum(v["pass"] for v in rows.values())
    return {"traits": rows, "score": f"{n}/4", "pass": n >= 3}


def held(mapping, temporal) -> dict:
    r = readings("T8", mapping, temporal)
    want = {"e1": "observed", "e2": "observed", **{e: "undecided" for e in ERAS[2:]}}
    return {"read": r, "as_keyed": r == want}


def one_era(mapping, temporal) -> dict:
    r = readings("T9", mapping, temporal)
    return {"read": {e: r[e] for e in ("e4", "e5", "e6")},
            "as_keyed": (r["e4"], r["e5"], r["e6"]) == ("contradicted", "observed", "contradicted")}


def absence(mapping, temporal) -> dict:
    rows = {}
    for t in SILENT:
        hits = [c for c, (tt, o) in mapping.items() if tt == t and o == "same"
                and any(v == "observed" for v in temporal[c].values())]
        rows[t] = {"supported_same": hits, "pass": not hits}
    return {"traits": rows, "pass": all(v["pass"] for v in rows.values())}


def three_way(divergence_rows: list[dict]) -> dict:
    by_facet = {r["facet"]: r for r in divergence_rows}
    rows, firm_pass = {}, 0
    for row in KEY["three_way"]:
        got = by_facet.get(row["facet"])
        actual = got["class"] if got else None
        ok = actual == row["expected"]
        firm_pass += ok and row["firm"]
        rows[row["facet"]] = {"expected": row["expected"], "actual": actual, "firm": row["firm"], "match": ok,
                              "inductive": got and got["inductive"], "observer_band": got and got["observer_band"],
                              "self": got and got["self"], "test": got and got["test"]}
    firm = sum(r["firm"] for r in KEY["three_way"])
    return {"facets": rows, "score": f"{firm_pass}/{firm}", "pass": firm_pass >= 4}


def zoning(labels: dict, plant_ids: dict) -> dict:
    by_class = {}
    for era, plants in KEY["plants"].items():
        for p in plants:
            sid = plant_ids.get(p["id"])
            label = labels.get(sid) if sid else None
            ok = label in ("remove", "mixed") if p["class"] in ("R", "X", "trap") else label == "keep"
            by_class.setdefault(p["class"], []).append({"id": p["id"], "label": label, "ok": ok})
    rx = by_class["R"] + by_class["X"]
    removed, kept = sum(x["ok"] for x in rx), sum(x["ok"] for x in by_class["K"])
    return {"R+X removed": f"{removed}/{len(rx)}", "K kept": f"{kept}/{len(by_class['K'])}",
            "misses": [x for xs in by_class.values() for x in xs if not x["ok"]],
            "pass": removed >= 0.95 * len(rx) and kept >= 0.8 * len(by_class["K"]),
            "traps_excluded": {x["id"]: x["ok"] for x in by_class["trap"]},
            "traps_pass": all(x["ok"] for x in by_class["trap"])}


def future_blind(discovery: list[dict], substrate: dict[str, str]) -> dict:
    """`discovery`: [{"era", "text"}] where text is everything a discovery call for that era read or wrote.
    A sentinel passes only if it reached its own era's substrate and appears in no earlier era's discovery."""
    rows = {}
    for s in KEY["sentinels"]:
        reached = s["term"] in substrate.get(s["era"], "")
        early = sorted({d["era"] for d in discovery if ERAS.index(d["era"]) < ERAS.index(s["era"])
                        and s["term"] in d["text"]})
        rows[s["term"]] = {"reached_own_era": reached, "seen_early_in": early, "pass": reached and not early}
    return {"sentinels": rows, "pass": all(v["pass"] for v in rows.values())}


# --- workspace reading ---

def _discovery_texts(ws_root: Path, repo: Path) -> list[dict]:
    sys.path.insert(0, str(repo / "scripts"))
    from abx import artifacts, store
    ws = store.Workspace(ws_root)
    out = []
    for rec_path in sorted(ws.path("run/calls/extract/discovery").glob("*.json")):
        rec = store.read_json(rec_path)
        inputs = rec["input_artifacts"]
        parts = [artifacts.path_of(ws, aid).read_text() for aid in inputs if not aid.startswith(("template:", "schema:"))]
        parts.append(json.dumps(rec.get("output"), ensure_ascii=False))
        stem = rec_path.stem
        for extra in (ws.path(f"run/discovery/{stem}.hypotheses.md"),):
            if extra.exists():
                parts.append(extra.read_text())
        out.append({"era": rec["era"], "text": "\n".join(parts)})
    return out


def score(repo: Path, ws_root: Path, map_a: dict, map_b: dict, plant_ids: dict | None = None) -> dict:
    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(repo / "scripts"))
    from abx import store
    from tests import recompute
    ws = store.Workspace(ws_root)
    mapping, disputed = agreed(map_a, map_b)
    agreement = store.read_json(ws.path("run/agreement.json"))
    temporal = {row["construct_id"]: row["eras"] for row in agreement["temporal"]}
    unknown = sorted(set(mapping) - set(temporal))
    if unknown:
        raise SystemExit(f"mapping names constructs the run lacks: {unknown}")
    results = store.read_json(ws.path("report/results.json"))
    ws_eras = [e["id"] for e in store.read_json(ws.path("prepare/eras.json"))["eras"]]
    labels = {}
    for era in ws_eras:
        labels |= store.read_json(ws.path(f"prepare/zoning/{era}.json"))
    if plant_ids is None:
        plant_ids = json.loads((ROOT / "evidence/validation.json").read_text())["plant_sentence_ids"]
    substrate = {e: ws.path(f"prepare/substrate/{e}.md").read_text() for e in ws_eras}
    book = {c["id"]: c for c in store.read_json(ws.path("run/codebook/codebook.json"))["constructs"]}
    supported = sorted(c for c, eras in temporal.items() if "observed" in eras.values())
    trap_sids = {plant_ids[p["id"]] for ps in KEY["plants"].values() for p in ps if p["class"] == "trap"
                 and p["id"] in plant_ids}
    trap_citations = sorted({rec.name for rec in ws.path("run/calls/extract").rglob("*.json")
                             if any(re.search(rf"\b{sid}\b", rec.read_text()) for sid in trap_sids)})
    out = {
        "run": {"recompute_problems": recompute.problems(ws)},
        "matching": {"agreed": {c: list(v) for c, v in mapping.items()}, "disputed": disputed},
        "zoning": zoning(labels, plant_ids),
        "trap_citations_in_calls": trap_citations,
        "future_blind": future_blind(_discovery_texts(ws_root, repo), substrate),
        "stable": stable(mapping, temporal),
        "transitions": transitions(mapping, temporal),
        "held": held(mapping, temporal),
        "one_era": one_era(mapping, temporal),
        "absence": absence(mapping, temporal),
        "three_way": three_way(results["divergence"]["rows"]),
        "per_trait": {t: readings(t, mapping, temporal) for t in KEY["traits"]},
        "harness_temporal_of_matched": {c: next(r for r in agreement["temporal"] if r["construct_id"] == c)
                                        for c in mapping},
        "unkeyed": [{"id": c, "name": book[c]["name"], "definition": book[c]["definition"]}
                    for c in supported if c not in mapping and c in book],
    }
    out["run"]["pass"] = not out["run"]["recompute_problems"]
    return out


if __name__ == "__main__":
    repo, ws_root = Path(sys.argv[1]), Path(sys.argv[2]).resolve()
    a, b = (json.loads(Path(p).read_text())["constructs"] for p in sys.argv[3:5])
    result = score(repo, ws_root, a, b)
    text = json.dumps(result, indent=1, ensure_ascii=False, default=list)
    if len(sys.argv) > 5:
        Path(sys.argv[5]).write_text(text + "\n")
    print(text)
