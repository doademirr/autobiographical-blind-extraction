"""Era size limits, checked before any model call: does each era fit every per-era role's input budget?

The check is an upper bound on what a call will send: the era rendered as if zoning kept every sentence (the
substrate's own format, ids and segment headers included), each role's template, schema and fixed inputs, the
hypotheses of every earlier era for discovery, and for recode the largest card the codebook schema allows. The zoner
is checked per chunk. A failure names the era, its words, the role and the most words an era can hold.
"""

from . import config, extract, invoke, store, text
from .errors import UsageError
from .roles import ROLES

__all__ = ["MAX_HYPOTHESES_CHARS", "check_eras", "max_era_words"]

# The most hypotheses text one earlier era can pass to discovery: the schema allows 40 of 300 characters,
# plus list markers. Era k carries the hypotheses of every era before it.
MAX_HYPOTHESES_CHARS = 40 * 303


def _largest_card(ws: store.Workspace) -> str:
    props = store.read_json(ws.path("prereg/schemas/codebook.json"))["properties"]["constructs"]["items"]["properties"]
    widest = {"item_id": "K000000", **{f: "x" * props[f]["maxLength"] for f in ("name", "definition",
                                                                                 "sufficiency_rule")}}
    return extract.card_line(widest) * extract.MAX_CONSTRUCTS


def _fixed(ws: store.Workspace, role: str, position: int, label: str) -> str:
    """Everything a per-era call carries besides the era text, at its largest."""
    policy = ROLES[role]
    fixed = (ws.path(f"prereg/prompts/{role}.md").read_text() + ws.path(f"prereg/schemas/{policy.schema}.json")
             .read_text() + label)
    if "facets" in policy.kinds:
        fixed += ws.path("prereg/facets.md").read_text()
    if "hypotheses" in policy.kinds:
        fixed += "x" * (MAX_HYPOTHESES_CHARS * position)
    if "card" in policy.kinds:
        fixed += _largest_card(ws)
    return fixed


def _lineages(cfg: config.Config, role: str) -> list[config.Lineage]:
    return [cfg.lineage(cfg.zoner)] if role == "zoner" else list(cfg.lineages.values())


def _words_that_fit(fixed: str, lin: config.Lineage, chars_per_word: float) -> int:
    room = lin.input_budget_tokens - lin.reserve_output_tokens - invoke.estimate_tokens(fixed)
    return max(0, int(room / 1.2 * 4 / chars_per_word))


def max_era_words(ws: store.Workspace, cfg: config.Config, position: int, chars_per_word: float) -> int:
    """The most words an era at this position (0 for the first) can hold under this config, across every
    per-era rater role. An estimate where the text's characters per word are an average."""
    return min(_words_that_fit(_fixed(ws, role, position, "x" * 80), lin, chars_per_word)
               for role, policy in ROLES.items() if policy.per_era and role != "zoner"
               for lin in _lineages(cfg, role))


def check_eras(ws: store.Workspace, cfg: config.Config, eras: list[dict], sents: list[text.Sentence],
               redacted: str) -> None:
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
            fixed = _fixed(ws, role, position, label)
            for lin in _lineages(cfg, role):
                if all(invoke.estimate_tokens(fixed + b) + lin.reserve_output_tokens <= lin.input_budget_tokens
                       for b in bodies):
                    continue
                if role == "zoner":
                    raise UsageError(f"era {era['id']}: a zoning chunk is too large for {lin.name}'s budget "
                                     f"({lin.input_budget_tokens} tokens); its sentences are unusually long")
                fits = _words_that_fit(fixed, lin, len(body) / max(words, 1))
                raise UsageError(f"era {era['id']} has {words} words; {role} on {lin.name} fits about {fits} words "
                                 f"in this era ({lin.input_budget_tokens} tokens, {lin.reserve_output_tokens} kept for "
                                 "output). Split it into smaller eras.")
