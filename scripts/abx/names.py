"""The candidate-name scan `prepare` runs on first use: local and deterministic, no model. It pre-fills the unapproved
redaction list with placeholders and lists every candidate in a preview; the user deletes what isn't a person, adds
what it missed, and approves.

A candidate is a run of one to three capitalised words seen somewhere other than the start of a sentence, where
capitals are ordinary. A title word before a run marks it titled and is not part of it. Counts use the whole-word,
case-sensitive matching that redaction uses.
"""

import re
from collections.abc import Sequence
from typing import NamedTuple

from .text import Sentence, name_pattern

__all__ = ["Candidate", "prefill", "preview", "scan"]

MAX_RUN = 3
# The first stem no chosen name uses, so no placeholder contains a name on the list. The last holds a digit, which no
# scanned word does, so it can never collide.
PLACEHOLDER_STEMS = ("Name", "Person", "Someone", "Party", "Name0")
TITLES = frozenset({"Mr", "Mrs", "Ms", "Miss", "Dr", "Sir", "Lady", "Lord", "Aunt", "Uncle", "Captain", "Rev", "St"})
FUNCTION_WORDS = frozenset({"The", "A", "An", "And", "But", "Or", "In", "On", "At", "To", "Of", "For", "With", "My",
                            "Our", "His", "Her", "Their", "That", "This", "These", "Those", "Without", "When", "If",
                            "As", "So", "It", "We", "He", "She", "They", "You", "There", "Here", "What", "Which",
                            "Who", "Not", "No", "All", "Some"})
NOT_NAMES = frozenset({"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "January",
                       "February", "March", "April", "May", "June", "July", "August", "September", "October",
                       "November", "December", "God", "Christmas", "Easter", "English", "French", "Mother", "Father",
                       "Mum", "Dad"}) | TITLES
_TOKEN = re.compile(r"[^\W\d_](?:[^\W\d_]|['’\-])*")
_OPENERS = " \t\n\"'“‘([{"
# A capital after one of these inside a sentence starts a clause, not a name.
_CLAUSE_BREAKS = ":;—–-"


class Candidate(NamedTuple):
    name: str
    count: int
    titled: bool
    first_segment: str


class _Word(NamedTuple):
    text: str
    start: int
    end: int
    possessive: bool


def _words(body: str) -> list[_Word]:
    out = []
    for m in _TOKEN.finditer(body):
        raw = m.group(0)
        word = raw[:-2] if raw.endswith(("'s", "’s")) else raw.rstrip("'’-")
        out.append(_Word(word, m.start(), m.end(), word != raw.rstrip("-")))
    return out


def _capitalised(word: str) -> bool:
    return bool(word) and word[0].isupper() and any(c.islower() for c in word)


def _sightings(body: str) -> list[tuple[str, bool]]:
    """(run, titled) for each run in one sentence that does not start it."""
    words = _words(body)
    out = []
    i = 0
    while i < len(words):
        word = words[i]
        gap = body[word.end:words[i + 1].start] if i + 1 < len(words) else ""
        titled = word.text in TITLES and gap in (" ", ". ") and _capitalised(words[i + 1].text) and \
            words[i + 1].text not in TITLES
        if titled:
            i += 1
        elif not _capitalised(word.text):
            i += 1
            continue
        before = body[:words[i].start].rstrip(_OPENERS)
        initial = not titled and (not before or before[-1] in _CLAUSE_BREAKS)
        run = [words[i]]
        while len(run) < MAX_RUN and not run[-1].possessive and i + 1 < len(words) and \
                body[words[i].end:words[i + 1].start] == " " and _capitalised(words[i + 1].text):
            i += 1
            run.append(words[i])
        while i + 1 < len(words) and body[words[i].end:words[i + 1].start] == " " and \
                _capitalised(words[i + 1].text) and not words[i].possessive:
            i += 1  # a run longer than MAX_RUN words keeps its first ones; the rest are not a run of their own
        i += 1
        texts = [w.text for w in run]
        while texts and texts[0] in FUNCTION_WORDS:
            texts.pop(0)
        if initial or not texts or (len(texts) == 1 and texts[0] in NOT_NAMES):
            continue
        out.append((" ".join(texts), titled))
    return out


def scan(text: str, sentences: Sequence[Sentence]) -> list[Candidate]:
    """Every candidate, in order of first sighting."""
    first: dict[str, str] = {}
    titled: set[str] = set()
    for sent in sentences:
        for name, was_titled in _sightings(text[sent.start:sent.end]):
            first.setdefault(name, sent.segment_id)
            if was_titled:
                titled.add(name)
    return [Candidate(name, len(name_pattern([name]).findall(text)), name in titled, segment)
            for name, segment in first.items()]


def prefill(candidates: Sequence[Candidate]) -> dict[str, str]:
    """Placeholders for the candidates seen twice or after a title, numbered by first sighting; a one-word candidate
    that is a word of exactly one chosen multi-word candidate shares its placeholder."""
    chosen = [c.name for c in candidates if c.count >= 2 or c.titled]
    multi = [n for n in chosen if " " in n]
    owner = {n: owners[0] for n in chosen if " " not in n
             for owners in [[m for m in multi if n in m.split(" ")]] if len(owners) == 1}
    stem = next(s for s in PLACEHOLDER_STEMS if not any(s in n.split(" ") for n in chosen))
    placeholders: dict[str, str] = {}
    for name in chosen:
        if name not in owner:
            placeholders[name] = f"{stem} {len(placeholders) + 1}"
    for name, full in owner.items():
        placeholders[name] = placeholders[full]
    return {name: placeholders[name] for name in chosen}


def preview(candidates: Sequence[Candidate], names: dict[str, str]) -> str:
    """Pre-filled candidates by count, then those seen once and left out."""
    kept = sorted((c for c in candidates if c.name in names), key=lambda c: (-c.count, c.name))
    rest = [c for c in candidates if c.name not in names]
    lines = ["Pre-filled in redactions.json (name, times in the text, replacement, first paragraph seen mid-sentence):"]
    lines += [f"{c.name}\t{c.count}\t{names[c.name]}\t{c.first_segment}" + ("\t(after a title)" if c.titled else "")
              for c in kept]
    lines += ["", "Seen once and not pre-filled (add any that are people you want hidden):"]
    lines += [f"{c.name}\t{c.first_segment}" for c in rest]
    return "\n".join(lines) + "\n"
