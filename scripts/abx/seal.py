"""`seal`: check the sealed comparators are complete and record their hashes.

The harness reads sealed files only to validate and hash them (and, internally, for the
substring audit); their contents are never printed or sent before generation C.
"""

import re

from . import ipip, lifecycle, store
from .errors import UsageError
from .lifecycle import HASHES, SEALED

__all__ = ["HASHES", "SEALED", "predictions", "seal"]
PREDICTION = re.compile(r"^(P\d{1,3}):[ \t]*(.*)$", re.M)


def predictions(text: str) -> dict[str, str]:
    """`P<n>: claim` lines. An empty claim is an error, never silently merged with the next line."""
    found = [(pid, claim.strip()) for pid, claim in PREDICTION.findall(text)]
    ids = [pid for pid, _ in found]
    if len(ids) != len(set(ids)):
        raise UsageError("self-prediction.md: prediction ids must be unique")
    empty = [pid for pid, claim in found if not claim]
    if empty:
        raise UsageError(f"self-prediction.md: {', '.join(empty)} has no text; fill it in or delete the line")
    return dict(found)


def seal(ws: store.Workspace) -> dict:
    lifecycle.enter(ws, "seal")
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
