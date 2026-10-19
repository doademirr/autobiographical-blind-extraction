"""`seal`: check the sealed comparators are complete and record their hashes.

The harness reads sealed files only to validate and hash them (and, internally, for the
substring audit); their contents are never printed or sent before generation C.
"""

import re

from . import ipip, store
from .errors import IntegrityError, UsageError

SEALED = ("sealed/self-prediction.md", "sealed/ipip-120.csv")
HASHES = "prereg/sealed-hashes.json"
PREDICTION = re.compile(r"^(P\d{1,3}):\s*(\S.*)$", re.M)


def predictions(text: str) -> dict[str, str]:
    found = PREDICTION.findall(text)
    ids = [pid for pid, _ in found]
    if len(ids) != len(set(ids)):
        raise UsageError("self-prediction.md: prediction ids must be unique")
    return dict(found)


def seal(ws: store.Workspace) -> dict:
    for rel in SEALED:
        if not ws.path(rel).exists():
            raise UsageError(f"{rel} is missing")
    count = len(predictions(ws.path(SEALED[0]).read_text(encoding="utf-8")))
    if count == 0:
        raise UsageError("self-prediction.md holds no predictions (lines like `P1: …`)")
    responses = ipip.parse_responses(ws.path(SEALED[1]).read_text(encoding="utf-8"), ipip.load_instrument())
    answered = sum(1 for r in responses.values() if r is not None)
    if answered < 90:
        raise UsageError(f"ipip-120.csv: only {answered} of 120 items answered; at least 90 are needed")
    store.write_json(ws.path(HASHES), {rel: store.sha256_file(ws.path(rel)) for rel in SEALED})
    return {"predictions": count, "ipip_answered": answered}


def verify_sealed(ws: store.Workspace) -> None:
    if not ws.path(HASHES).exists():
        raise UsageError("sealed files are not sealed yet; run `seal`")
    for rel, digest in store.read_json(ws.path(HASHES)).items():
        if not ws.path(rel).exists() or store.sha256_file(ws.path(rel)) != digest:
            raise IntegrityError(f"{rel} changed after sealing")
