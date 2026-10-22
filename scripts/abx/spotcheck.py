"""The user's spot check of zoning: `prepare` shows a seeded sample of kept and removed sentences, the user marks any
that are wrongly labelled and approves, and `freeze` waits for that. Marks are frozen and counted in the report;
they never change the zoning, so the subject cannot edit the evidence.
"""

import random
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import NamedTuple

from . import calibration, store, text
from .errors import UsageError

__all__ = ["GROUPS", "PATH", "Checked", "approved", "check", "sample", "summary", "write"]

PATH = "prepare/spot-check.json"
PER_GROUP = 20
GROUPS = MappingProxyType({"kept": "keep", "removed": "removed"})  # file key -> stratum (mixed counts as removed)
NOTE = ("Read each sentence. A kept sentence is wrongly labelled if it carries reflection from the time of writing (on "
        "your character, a pattern, a lesson, a later verdict). A removed sentence is wrongly labelled only if it "
        "carries no such reflection at all: one that mixes an event with a later reflection belongs with the removed. "
        "Set \"wrong\": true on each wrongly labelled sentence, then \"approved\": true. Your marks are counted in the "
        "report; they never change what the raters see.")


class Checked(NamedTuple):
    """A validated spot check: whether it is approved, and the digest of the bytes validated."""

    approved: bool
    sha256: str


class _Pick(NamedTuple):
    era: str
    sentence: text.Sentence


def sample(eras: Sequence[Mapping], sents: Sequence[text.Sentence], labels: Mapping[str, str],
           redacted: str) -> dict[str, list[dict]]:
    """Up to 20 kept and 20 removed sentences, allocated across eras in proportion, in text order; seeded by the
    redacted text, so `freeze` draws the same sample."""
    rng = random.Random("spot-check:" + store.sha256_text(redacted))
    out = {}
    for group, stratum in GROUPS.items():
        pools = {e["id"]: [s for s in sents if s.segment_id in set(e["segment_ids"])
                           and calibration.collapse(labels[s.id]) == stratum] for e in eras}
        alloc = calibration.allocate({era: len(pool) for era, pool in pools.items()}, PER_GROUP)
        picked = sorted((_Pick(era, s) for era, pool in pools.items() for s in rng.sample(pool, alloc[era])),
                        key=lambda pick: pick.sentence.start)
        out[group] = [{"sentence_id": p.sentence.id, "era": p.era, "text": redacted[p.sentence.start:p.sentence.end],
                       "wrong": False} for p in picked]
    return out


def write(ws: store.Workspace, eras: Sequence[Mapping], sents: Sequence[text.Sentence], labels: Mapping[str, str],
          redacted: str) -> None:
    """The file the user reads and marks, written once; an existing one is never replaced."""
    if not ws.path(PATH).exists():
        store.write_json(ws.path(PATH), {"approved": False, "note": NOTE, **sample(eras, sents, labels, redacted)})


def _expected(ws: store.Workspace) -> dict[str, list[dict]]:
    eras = store.read_json(ws.path("prepare/eras.json"))["eras"]
    labels = {sid: lab for e in eras for sid, lab in store.read_json(ws.path(f"prepare/zoning/{e['id']}.json")).items()}
    sents = [text.Sentence(s["id"], s["segment_id"], s["start"], s["end"])
             for s in store.read_json(ws.path("prepare/sentences.json"))]
    return sample(eras, sents, labels, ws.path("prepare/redacted.txt").read_text(encoding="utf-8"))


def check(ws: store.Workspace) -> Checked:
    """Whether the user approved the spot check, read once, with the digest of the bytes read; a usage error if it is
    missing, malformed, or not the sample `prepare` drew. Only the ids, the marks and the approval are read."""
    if not ws.path(PATH).exists():
        raise UsageError(f"{PATH} is missing: this preparation predates the spot check; prepare a new workspace")
    raw = ws.path(PATH).read_bytes()
    try:
        doc = store.loads_strict(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UsageError(f"{PATH} is not valid JSON") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("approved"), bool) or \
            not all(isinstance(doc.get(g), list) and all(isinstance(x, dict) for x in doc[g]) for g in GROUPS):
        raise UsageError(f"{PATH}: expected \"approved\" (true or false) and the \"kept\" and \"removed\" lists")
    expected = _expected(ws)
    for group in GROUPS:
        if [x.get("sentence_id") for x in doc[group]] != [x["sentence_id"] for x in expected[group]]:
            raise UsageError(f"{PATH}: the {group} sentences differ from the sample prepare drew; restore them")
        if not all(isinstance(x.get("wrong"), bool) for x in doc[group]):
            raise UsageError(f"{PATH}: each \"wrong\" is true or false")
    return Checked(doc["approved"], store.sha256_bytes(raw))


def approved(ws: store.Workspace) -> bool:
    """For `status` only, which must always answer: a missing, unreadable or malformed file is not approved; `freeze`
    reports why."""
    try:
        return store.read_json(ws.path(PATH)).get("approved") is True
    except (OSError, UsageError, AttributeError):
        return False


def summary(doc: Mapping) -> dict:
    return {group: {"shown": len(doc[group]), "marked": sum(1 for x in doc[group] if x["wrong"])} for group in GROUPS}
