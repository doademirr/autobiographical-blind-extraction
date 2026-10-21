"""Outputs the fake CLIs generate, by role, from the prompt they receive.

Deterministic in (prompt, lineage, occurrence), and shaped so the offline smoke exercises
every path: lineage-specific traits (one-lineage discovery), contested and not-shown verdicts
(insufficient and absent agree under the binary reading), run-to-run drift, insufficient
facets, and prediction matches.
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


def foil_author(prompt, lineage, occurrence):
    """A clear and a near-miss foil, plus an anchored one when the era has paragraphs far enough apart."""
    segs = segments(prompt)
    era = era_label(prompt)
    out = [{"id": "F1", "type": "clear", "name": f"Love of solitude {era}", "definition": "Seeks time alone.",
            "sufficiency_rule": "Two separate retreats from company.", "support": [],
            "counter_sentence_ids": [segs[0][0]]},
           {"id": "F2", "type": "near_miss", "name": f"Fondness for gambling {era}",
            "definition": "Stakes money on chance.", "sufficiency_rule": "Two separate wagers.",
            "support": [{"sentence_ids": [segs[0][0]], "event": "a risky bargain"}],
            "counter_sentence_ids": [segs[-1][0]]}]
    if len(segs) >= 3:
        out.append({"id": "F3", "type": "anchored", "name": f"Habit of early rising {era}",
                    "definition": "Starts the day early.", "sufficiency_rule": "Two separate early starts.",
                    "support": [{"sentence_ids": [segs[0][0]], "event": "one morning"},
                                {"sentence_ids": [segs[-1][0]], "event": "another morning"}],
                    "counter_sentence_ids": []})
    return {"foils": out}


def auditor(prompt, lineage, occurrence):
    """Keeps every foil but the near-miss of one Franklin era (by a hash of its label). Flags the first construct in
    every era, or with ABX_FAKE_PLANTED only in an era whose text holds that planted sentence, citing it."""
    segs = segments(prompt)
    era = era_label(prompt)
    decisions = [{"foil_id": fid, "decision": "drop" if (kind == "near_miss" and h(era, "drop") % 2 == 0) else "keep",
                  "reason": "judged against the era"} for fid, kind in re.findall(r"^- (F\d) \((\w+),", prompt, re.M)]
    constructs = re.findall(r"^- (C\d{2}): ", prompt, re.M)
    planted = os.environ.get("ABX_FAKE_PLANTED")
    if planted:
        hit = re.search(rf"^\[(s\d{{5}})\] .*{re.escape(planted)}", prompt, re.M)
        flags = [{"construct_id": constructs[0], "counter_sentence_ids": [hit.group(1)], "reason": "contradicts it"}] \
            if hit and constructs else []
    else:
        flags = [{"construct_id": constructs[0], "counter_sentence_ids": [segs[0][0]], "reason": "contradicts it"}] \
            if constructs else []
    return {"foils": decisions, "flags": flags}


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


def zoner_label(sentence_id: str) -> str:
    n = int(sentence_id[1:])
    return "remove" if n % 9 == 0 else "mixed" if n % 9 == 1 else "keep"


def calibration_judge(prompt, lineage, occurrence):
    """Agrees with the fake zoner once collapsed; codex calls mixed sentences remove, so three-label agreement drops.
    ABX_FAKE_JUDGE (`lineage:label,…`) makes a lineage give every sentence that label; ABX_FAKE_JUDGE_FLIP
    (`lineage:n`) makes it flip keep and remove on every nth sentence, so the judges dispute those."""
    forced = dict(item.split(":") for item in filter(None, os.environ.get("ABX_FAKE_JUDGE", "").split(",")))
    flips = dict(item.split(":") for item in filter(None, os.environ.get("ABX_FAKE_JUDGE_FLIP", "").split(",")))
    labels = []
    for i in SENT.findall(prompt):
        label = forced.get(lineage) or zoner_label(i)
        if lineage in flips and int(i[1:]) % int(flips[lineage]) == 0:
            label = "remove" if label == "keep" else "keep"
        labels.append({"sentence_id": i, "label": "remove" if lineage == "codex" and label == "mixed" else label})
    return {"labels": labels}


ROLES = {"calibration_judge": calibration_judge, "foil_author": foil_author, "auditor": auditor,
         "discovery": discovery, "codebook_author": codebook_author, "recode": recode, "deductive_ledger": ledger,
         "deductive_scorer": scorer, "crosswalk": crosswalk}


def respond(prompt: str, lineage: str, occurrence: int, leak: str | None):
    role = role_of(prompt)
    if role == "probe":
        return {"answer": leak or "NONE"}
    if role == "echo":
        return {"answer": f"{lineage}:{occurrence}"}
    if role == "zoner":
        return {"labels": [{"sentence_id": i, "label": zoner_label(i)} for i in SENT.findall(prompt)]}
    if role in ROLES:
        return ROLES[role](prompt, lineage, occurrence)
    raise SystemExit(f"fake: no response for role {role!r}")
