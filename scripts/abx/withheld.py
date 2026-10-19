"""Text no prompt may carry, gathered from the workspace for the secondary substring audit.

Read only to check prompts against; nothing here is printed or sent.
"""

import re
from dataclasses import dataclass, field

from . import store

__all__ = ["MIN_REMOVED_LEN", "Withheld", "load"]

MIN_REMOVED_LEN = 40
_PREDICTION_TEXT = re.compile(r"^P\d{1,3}:[ \t]*(\S.*)$", re.M)
_ANSWER = re.compile(r"^i\d{3},[1-5]$")


@dataclass
class Withheld:
    redacted_names: list[str] = field(default_factory=list)
    removed_sentences: list[str] = field(default_factory=list)
    self_prediction: list[str] = field(default_factory=list)
    ipip: list[str] = field(default_factory=list)


def load(ws: store.Workspace) -> Withheld:
    w = Withheld()
    redactions = ws.path("prepare/redactions.json")
    if redactions.exists():
        w.redacted_names = list(store.read_json(redactions)["names"])
    removed = ws.path("prepare/zoning/removed.json")
    if removed.exists():
        w.removed_sentences = store.read_json(removed)
    prediction = ws.path("sealed/self-prediction.md")
    if prediction.exists():
        w.self_prediction = [t.strip() for t in _PREDICTION_TEXT.findall(prediction.read_text(encoding="utf-8"))
                             if len(t.strip()) >= 12]
    answers = ws.path("sealed/ipip-120.csv")
    if answers.exists():
        w.ipip = [line for line in answers.read_text(encoding="utf-8").splitlines()[1:] if _ANSWER.match(line)]
    return w
