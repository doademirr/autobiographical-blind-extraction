"""Era size limits, checked before any model call: does each era fit every per-era role's input budget?

The check is an upper bound on what a call will send, built by the same `prompts.assemble` the call uses, so every
placeholder expands as it will: the era rendered as if zoning kept every sentence (the substrate's own format, ids
and segment headers included), the staged template and schema, the hypotheses of every earlier era for discovery, for
recode the largest card the codebook and foil schemas allow, and for the auditor the largest codebook and foils. The
zoner is checked per chunk. A failure names the era, its words, the role and the most words an era can hold.
"""

from . import audit, card, config, foils, invoke, prompts, store, text
from .errors import UsageError
from .roles import ROLES

__all__ = ["MAX_HYPOTHESES_CHARS", "check_eras", "max_era_words"]

# The most hypotheses text one earlier era can pass to discovery: the schema allows 40 of 300 characters,
# plus list markers. Era k carries the hypotheses of every era before it.
MAX_HYPOTHESES_CHARS = 40 * 303


def _widest(ws: store.Workspace, schema: str, key: str) -> tuple[dict, int]:
    """An item of a staged schema's `key` list with every card field at its maximum, and how many the list allows."""
    items = store.read_json(ws.path(f"prereg/schemas/{schema}.json"))["properties"][key]
    props = items["items"]["properties"]
    return ({"id": "C00", "item_id": "K000000", **{f: "x" * props[f]["maxLength"]
                                                   for f in ("name", "definition", "sufficiency_rule")}},
            items["maxItems"])


def _largest_card(ws: store.Workspace, eras: int) -> str:
    """Every construct the codebook schema allows plus every foil the foils schema allows per era, at their widest."""
    construct, n_constructs = _widest(ws, "codebook", "constructs")
    foil, n_foils = _widest(ws, "foils", "foils")
    return card.line(construct) * n_constructs + card.line(foil) * (n_foils * eras)


def _prompt(ws: store.Workspace, role: str, era_ids: list[str], position: int, label: str, body: str) -> str:
    """The prompt `role` would send for the era at `position`, assembled from the staged template with every input at
    its largest and `body` standing in for the era (or chunk) text."""
    policy = ROLES[role]
    era = era_ids[position]
    slots = {"schema": f"schema:{policy.schema}"}
    texts = {f"template:{role}": ws.path(f"prereg/prompts/{role}.md").read_text(),
             slots["schema"]: ws.path(f"prereg/schemas/{policy.schema}.json").read_text()}
    for kind in sorted(policy.kinds):
        if kind == "hypotheses" and position == 0:
            continue
        aid, value = _largest_input(ws, kind, era_ids, position, body)
        slots[kind], texts[aid] = aid, value
    params = {"era_label": label} if "era_label" in policy.params else {}
    if "hypotheses" in policy.params and position == 0:
        params["hypotheses"] = invoke.FIRST_ERA_MARKER
    return prompts.assemble(role, slots, texts.__getitem__, params, rater=("x", 1), era=era,
                            era_order=era_ids).text


def _largest_input(ws: store.Workspace, kind: str, era_ids: list[str], position: int, body: str) -> tuple[str, str]:
    """(artifact id, text) for one input kind of the call at `position`, at its largest."""
    era = era_ids[position]
    if kind in {"chunk", "era"}:
        return (f"chunk:{era}:1" if kind == "chunk" else f"era:{era}"), body
    if kind == "card":
        return "card:B", _largest_card(ws, len(era_ids))
    if kind == "codebook":
        construct, n = _widest(ws, "codebook", "constructs")
        return "codebook:B", audit.render_codebook([construct] * n)
    if kind == "foils":
        foil, n = _widest(ws, "foils", "foils")
        widest = {**foil, "id": "F1", "type": "near_miss", "expected": {era: "absent"}}
        return f"foils:{era}", foils.render_for_audit([widest] * n, era)
    if kind == "facets":
        return "facets:all", ws.path("prereg/facets.md").read_text()
    if kind == "hypotheses":
        return f"hypotheses:x:1:{era_ids[position - 1]}", "x" * (MAX_HYPOTHESES_CHARS * position)
    raise UsageError(f"no size rule for a per-era {kind} input")


def _lineages(cfg: config.Config, role: str) -> list[config.Lineage]:
    """The lineages a role runs on: the one its config role names, or every rater."""
    single = ROLES[role].single
    return [cfg.lineage(getattr(cfg, single))] if single else list(cfg.lineages.values())


# Stands in for the era text to count how many times a template expands it.
_MARK = "\u2063era\u2063"


def _words_that_fit(ws: store.Workspace, role: str, era_ids: list[str], position: int, label: str,
                    lin: config.Lineage, chars_per_word: float) -> int:
    copies = max(1, _prompt(ws, role, era_ids, position, label, _MARK).count(_MARK))
    room = lin.input_budget_tokens - lin.reserve_output_tokens - \
        invoke.estimate_tokens(_prompt(ws, role, era_ids, position, label, ""))
    return max(0, int(room / 1.2 * 4 / chars_per_word / copies))


def _fits(prompt: str, lin: config.Lineage) -> bool:
    return invoke.estimate_tokens(prompt) + lin.reserve_output_tokens <= lin.input_budget_tokens


def max_era_words(ws: store.Workspace, cfg: config.Config, position: int, chars_per_word: float) -> int:
    """The most words an era at this position (0 for the first) can hold under this config, across every
    per-era rater role. An estimate where the text's characters per word are an average."""
    era_ids = [f"e{k + 1}" for k in range(position + 1)]
    label = "x" * prompts.MAX_PARAM_LEN
    return min(_words_that_fit(ws, role, era_ids, position, label, lin, chars_per_word)
               for role, policy in ROLES.items() if policy.per_era and role != "zoner"
               for lin in _lineages(cfg, role))


def check_eras(ws: store.Workspace, cfg: config.Config, eras: list[dict], sents: list[text.Sentence],
               redacted: str) -> None:
    era_ids = [e["id"] for e in eras]
    for position, era in enumerate(eras):
        era_sents = [s for s in sents if s.segment_id in set(era["segment_ids"])]
        words = sum(len(redacted[s.start:s.end].split()) for s in era_sents)
        body = text.render_zoned(redacted, era["segment_ids"], era_sents, {s.id for s in era_sents})
        label = era["label"] or era["id"]
        for role, policy in ROLES.items():
            if not policy.per_era:
                continue
            bodies = ([text.render_numbered(redacted, chunk) for chunk in text.zoning_chunks(era_sents)]
                      if role == "zoner" else [body])
            for lin in _lineages(cfg, role):
                if all(_fits(_prompt(ws, role, era_ids, position, label, b), lin) for b in bodies):
                    continue
                if role == "zoner":
                    raise UsageError(f"era {era['id']}: a zoning chunk is too large for {lin.name}'s budget "
                                     f"({lin.input_budget_tokens} tokens); its sentences are unusually long")
                fits = _words_that_fit(ws, role, era_ids, position, label, lin, len(body) / max(words, 1))
                raise UsageError(f"era {era['id']} has {words} words; {role} on {lin.name} fits about {fits} words "
                                 f"in this era ({lin.input_budget_tokens} tokens, {lin.reserve_output_tokens} kept for "
                                 "output). Split it into smaller eras.")
