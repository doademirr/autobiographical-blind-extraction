"""The era proposal `prepare` writes on first run: local and deterministic, from the original text's headings, dated
passages and size alone, never its content. The user moves the cuts to life events, writes the labels and approves.

Every paragraph boundary may start an era, as a heading, a dated passage or a bare paragraph break. The count follows
the era rule (5-6 eras of 10k words where the text allows) and the per-era size cap; among partitions into that many
eras, each within the cap (or a lone paragraph over it) and at least half the target size where possible, the
proposal takes the fewest bare paragraph breaks, then the fewest dated cuts, then the most balanced sizes, then the
earliest cuts.
"""

import math
import re
from collections.abc import Callable, Sequence
from typing import NamedTuple

from .text import Segment

__all__ = ["Boundary", "Proposal", "candidates", "partition", "propose"]

MAX_HEADING = 80
TARGET_ERAS = 6
MIN_ERA_WORDS = 10_000
_YEAR = re.compile(r"(?<![\w])(1[5-9]\d\d|20\d\d)(?![\w])")
_MARKDOWN = re.compile(r"#{1,6}\s+\S")
_DIVISION = re.compile(r"(chapter|part|book|section)\s+(\d+|[ivxlcdm]+|[a-z]+)\b", re.IGNORECASE)


class Boundary(NamedTuple):
    """What starts at a paragraph: its kind, the heading's text, the years the paragraph mentions."""

    kind: str
    heading: str
    years: tuple[int, ...]


class Proposal(NamedTuple):
    """The proposed eras; `room` is False when the config leaves no room for era text, and `eras` is then the whole
    text as one era."""

    eras: list[dict]
    room: bool


class _Cost(NamedTuple):
    """A partial partition's cost, compared field by field in this order."""

    paragraph_cuts: int
    dated_cuts: int
    deviation: int
    cuts: tuple[int, ...]


def _is_heading(line: str) -> bool:
    if "\n" in line or len(line) > MAX_HEADING:
        return False
    if _MARKDOWN.match(line) or _DIVISION.match(line):
        return True
    bare = line.rstrip("\"'”’)]")
    return any(c.isalpha() for c in bare) and not any(c.islower() for c in bare) and bare[-1] not in ".!?,"


def candidates(text: str, segments: Sequence[Segment]) -> list[Boundary]:
    """One boundary per segment, in order. A heading must be a paragraph of its own: one with prose directly under
    it (no blank line between) is a single segment and is not detected."""
    out = []
    for seg in segments:
        body = text[seg.start:seg.end]
        years = tuple(int(y) for y in _YEAR.findall(body))
        kind = "heading" if _is_heading(body) else "dated" if years else "paragraph"
        out.append(Boundary(kind, body if kind == "heading" else "", years))
    return out


def _count(total: int, cap: int, paragraphs: int) -> int:
    return max(1, min(paragraphs, max(math.ceil(total / cap), min(TARGET_ERAS, total // MIN_ERA_WORDS))))


def partition(words: Sequence[int], kinds: Sequence[str], cap: int, n: int) -> list[int] | None:
    """The start index of each of `n` eras (the first is 0), or None if no partition into `n` admissible eras exists.
    `kinds[i]` is the kind of the boundary before paragraph i; `cap` > 0."""
    total = sum(words)
    prefix = [0]
    for w in words:
        prefix.append(prefix[-1] + w)
    for floor in (total / n / 2, 0):
        best = _search(prefix, kinds, cap, n, floor, total)
        if best is not None:
            return best
    return None


def _search(prefix: list[int], kinds: Sequence[str], cap: int, n: int, floor: float, total: int) -> list[int] | None:
    """Exact dynamic programme over (paragraphs covered, eras used). Costs compare as tuples: paragraph cuts, dated
    cuts, the sum of (era words * n - total)^2 (the squared deviation from the target, in integers), then the cut
    positions."""
    size = len(prefix) - 1
    best: list[dict[int, _Cost]] = [{} for _ in range(n + 1)]
    best[0][0] = _Cost(0, 0, 0, ())
    for k in range(1, n + 1):
        for start, cost in best[k - 1].items():
            for end in range(start + 1, size - (n - k) + 1):
                words = prefix[end] - prefix[start]
                if words > cap and end - start > 1:
                    break
                if words < floor:
                    continue
                cut = kinds[start] if start else None
                candidate = _Cost(cost.paragraph_cuts + (cut == "paragraph"), cost.dated_cuts + (cut == "dated"),
                                  cost.deviation + (words * n - total) ** 2, (*cost.cuts, start) if start else ())
                if end not in best[k] or candidate < best[k][end]:
                    best[k][end] = candidate
    final = best[n].get(size)
    return None if final is None else [0, *final.cuts]


def _date_range(years: list[int]) -> str:
    if not years:
        return ""
    ys = sorted(years)
    trim = (len(ys) - 1) // 10 if len(ys) >= 5 else 0
    lo, hi = ys[trim], ys[len(ys) - 1 - trim]
    return str(lo) if lo == hi else f"{lo}–{hi}"


def _basis(position: int, boundary: Boundary) -> str:
    if position == 0:
        return "start of text"
    if boundary.kind == "heading":
        return f"heading: {boundary.heading}"
    if boundary.kind == "dated":
        return f"dated passage (year {boundary.years[0]})"
    return "paragraph break: no heading or dated boundary fits the size limit"


def _era(k: int, segments: Sequence[Segment], bounds: Sequence[Boundary]) -> dict:
    return {"id": f"e{k + 1}", "label": "", "date_range": _date_range([y for b in bounds for y in b.years]),
            "segment_ids": [s.id for s in segments], "basis": _basis(k, bounds[0])}


def propose(text: str, segments: Sequence[Segment], cap_for: Callable[[int], int]) -> Proposal:
    """`cap_for(n)` is the per-era word cap when there are `n` eras; it shrinks as `n` grows, so the cap for the final
    count covers every era."""
    bounds = candidates(text, segments)
    words = [len(text[s.start:s.end].split()) for s in segments]
    kinds = [b.kind for b in bounds]
    assumed = 1
    while True:
        cap = cap_for(assumed)
        if cap <= 0:
            return Proposal([_era(0, segments, bounds)], room=False)
        n = _count(sum(words), cap, len(segments))
        starts = partition(words, kinds, cap, n)
        while starts is None:
            n += 1
            starts = partition(words, kinds, cap, n)
        if n <= assumed:
            break
        assumed = n
    ends = [*starts[1:], len(segments)]
    return Proposal([_era(k, segments[first:end], bounds[first:end])
                     for k, (first, end) in enumerate(zip(starts, ends, strict=True))], room=True)
