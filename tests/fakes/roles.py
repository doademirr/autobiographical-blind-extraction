"""Outputs the fake CLIs generate, by role, from the prompt they receive.

Deterministic in (prompt, lineage, occurrence), and shaped so the offline smoke exercises
every path: lineage-specific traits (one-lineage discovery), contested and one-lineage
verdicts, run-to-run drift, insufficient facets, and prediction matches.
"""

import hashlib
import json
import os
import re

ROLE_LINE = re.compile(r"^# abx-role: ([a-z_]+)", re.M)
SENT = re.compile(r"^\[(s\d{5})\]", re.M)
TRAITS = ["Thrift with money", "Love of reading", "Drive to argue", "Self-directed study", "Resentment of authority",
          "Practical ingenuity", "Concern for reputation", "Willingness to leave home"]
FACETS = [f"{d}{i}" for d in "NEOAC" for i in range(1, 7)]


def h(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def role_of(prompt: str) -> str:
    m = ROLE_LINE.search(prompt)
    return m.group(1) if m else "unknown"


def segments(prompt: str) -> list[list[str]]:
    """Sentence ids grouped by `## pNNNN` header, in prompt order."""
    groups: list[list[str]] = []
    for line in prompt.splitlines():
        if re.match(r"^## p\d{4}$", line):
            groups.append([])
        elif groups and SENT.match(line):
            groups[-1].append(line[1:7])
    return [g for g in groups if g]


def era_label(prompt: str) -> str:
    m = re.search(r"^Era: (.+)$", prompt, re.M)
    return m.group(1) if m else ""


def _two_episodes(segs: list[list[str]]) -> list[dict]:
    return [{"sentence_ids": [segs[0][0]]}, {"sentence_ids": [segs[-1][0]]}]


def discovery(prompt, lineage, occurrence):
    segs = segments(prompt)
    names = TRAITS[:6] if lineage == "claude" else TRAITS[2:]
    return {"bias_memo": "I lean toward reading recurring conduct as disposition.",
            "traits": [{"trait": n, "alexander_id": "frequency", "occurrences": _two_episodes(segs)} for n in names],
            "hypotheses": [f"The next era will show more {names[0].lower()}."]}


def codebook_author(prompt, lineage, occurrence):
    groups: dict[str, list[str]] = {}
    for ref, trait, _ in re.findall(r"^(c\d{3,4}) \| (.+?) \| (\w+)$", prompt, re.M):
        groups.setdefault(trait, []).append(ref)
    return {"constructs": [{"id": f"C{i + 1:02d}", "name": trait, "definition": f"Shows {trait.lower()} in conduct.",
                            "sufficiency_rule": f"Two separate episodes of {trait.lower()}.", "trace": refs}
                           for i, (trait, refs) in enumerate(groups.items())],
            "appendix": []}


def recode(prompt, lineage, occurrence):
    segs = segments(prompt)
    era = era_label(prompt)
    verdicts = []
    for item, name in re.findall(r"^- (K[0-9a-f]{6}): (.+?)\. ", prompt, re.M):
        base = "present" if h(name, era) % 3 else "absent"
        if lineage == "codex" and name == "Self-directed study":
            base = "absent" if base == "present" else "present"
        if lineage == "codex" and name == "Resentment of authority" and base == "absent":
            base = "insufficient"  # insufficient and absent agree under the binary reading
        if occurrence == 2 and h(name, era, "drift") % 4 == 0 and base != "insufficient":
            base = "absent" if base == "present" else "present"
        episodes = _two_episodes(segs)
        if name == "Practical ingenuity" and lineage == "claude" and occurrence == 1:
            episodes = [{"sentence_ids": [segs[0][0]]}, {"sentence_ids": [segs[1][0]]}]  # one scene, adjacent
        verdicts.append({"item_id": item, "verdict": base,
                         "occurrences": [{**o, "event": "an episode"} for o in episodes] if base == "present" else [],
                         "counter_sentence_ids": [segs[0][0]] if base == "absent" else []})
    return {"verdicts": verdicts}


def ledger(prompt, lineage, occurrence):
    segs = segments(prompt)
    facets = []
    for f in FACETS:
        pole = h(f) % 3
        evidence = [] if pole == 2 else [{"sentence_ids": [segs[i][0]], "pole": "high" if pole == 0 else "low",
                                          "note": "conduct in the scene"} for i in (0, -1)]
        facets.append({"facet": f, "evidence": evidence})
    return {"facets": facets}


def scorer(prompt, lineage, occurrence):
    body = prompt[prompt.index("Ledgers:") + len("Ledgers:"):]
    ledgers = json.loads(body)
    tally: dict[str, int] = dict.fromkeys(FACETS, 0)
    cited: dict[str, list[str]] = {f: [] for f in FACETS}
    for era in ledgers:
        for fac in era["facets"]:
            for ev in fac["evidence"]:
                tally[fac["facet"]] += 1 if ev["pole"] == "high" else -1
                cited[fac["facet"]] += ev["sentence_ids"]
    scores = []
    donor = next((f for f in FACETS if cited[f]), None)
    for f in FACETS:
        if not cited[f] and os.environ.get("ABX_FAKE_CROSS_FACET") and donor:
            scores.append({"facet": f, "score": 7, "cited_sentence_ids": cited[donor][:1]})
            continue
        if not cited[f]:
            score = None
        else:
            score = 4 + tally[f]
            if lineage == "codex" and h(f) % 4 == 0:
                score += 1
            if occurrence == 1 and h(f, "run") % 5 == 0:
                score -= 1
            score = max(1, min(7, score))
        stray = ["s99999"] if os.environ.get("ABX_FAKE_STRAY_CITATION") and score is not None else []
        scores.append({"facet": f, "score": score, "cited_sentence_ids": (cited[f] + stray)[:12]})
    return {"scores": scores}


def crosswalk(prompt, lineage, occurrence):
    constructs = re.findall(r"^- (C\d{2}): (.+?)\.", prompt, re.M)
    predictions = re.findall(r"^(P\d{1,3}):\s*(\S.*)$", prompt, re.M)
    codes = []
    for pid, ptext in predictions:
        for cid, name in constructs:
            words = set(re.findall(r"[a-z]{5,}", name.lower()))
            hit = any(w in ptext.lower() for w in words)
            code = "match" if hit else "none"
            if lineage == "codex" and hit and h(pid, cid) % 3 == 0:
                code = "partial"
            codes.append({"prediction_id": pid, "construct_id": cid, "code": code, "polarity": "same"})
    return {"codes": codes}


ROLES = {"discovery": discovery, "codebook_author": codebook_author, "recode": recode, "deductive_ledger": ledger,
         "deductive_scorer": scorer, "crosswalk": crosswalk}


def respond(prompt: str, lineage: str, occurrence: int, leak: str | None):
    role = role_of(prompt)
    if role == "probe":
        return {"answer": leak or "NONE"}
    if role == "echo":
        return {"answer": f"{lineage}:{occurrence}"}
    if role == "zoner":
        ids = SENT.findall(prompt)
        labels = ["remove" if int(i[1:]) % 9 == 0 else "mixed" if int(i[1:]) % 9 == 1 else "keep" for i in ids]
        return {"labels": [{"sentence_id": i, "label": lab} for i, lab in zip(ids, labels, strict=True)]}
    if role in ROLES:
        return ROLES[role](prompt, lineage, occurrence)
    raise SystemExit(f"fake: no response for role {role!r}")
