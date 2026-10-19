"""Prompt assembly from artifact ids, the role allowlists, and the secondary substring audit.

An artifact id is `kind:part:part…`. A prompt is built only from ids, each resolved to
text by the caller's resolver, so every call's provenance is the id list it records.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from . import store
from .errors import IsolationError, UsageError

# SPEC § Approach, role input allowlists. `template` and `schema` are every role's frame.
ROLE_KINDS: dict[str, set[str]] = {
    "zoner": {"chunk"},
    "discovery": {"era", "hypotheses"},
    "codebook_author": {"discovery"},
    "recode": {"card", "era"},
    "deductive_ledger": {"era"},
    "deductive_scorer": {"ledger"},
    "crosswalk": {"constructs", "self_prediction"},
    "probe": {"probe"},
}
FRAME_KINDS = {"template", "schema"}
# Roles that read zoned material and so must never carry text the zoner removed.
ZONED_CONSUMERS = {"discovery", "codebook_author", "recode", "deductive_ledger", "deductive_scorer", "crosswalk"}
MIN_REMOVED_LEN = 40

_SLOT = re.compile(r"\{\{([a-z_]+)\}\}")


@dataclass(frozen=True)
class Prompt:
    role: str
    text: str
    artifacts: dict[str, str]  # artifact id -> sha256 of its text


@dataclass
class Secrets:
    """Text that must not reach a model, checked by exact substring after assembly."""

    redacted_names: list[str] = field(default_factory=list)
    removed_sentences: list[str] = field(default_factory=list)
    self_prediction: list[str] = field(default_factory=list)
    ipip: list[str] = field(default_factory=list)


def kind(artifact_id: str) -> str:
    return artifact_id.split(":", 1)[0]


def check_allowlist(role: str, ids: list[str], rater: tuple[str, int] | None = None,
                    era: str | None = None, era_order: list[str] | None = None) -> None:
    allowed = ROLE_KINDS.get(role)
    if allowed is None:
        raise UsageError(f"unknown role {role!r}")
    for aid in ids:
        k = kind(aid)
        if k in FRAME_KINDS:
            continue
        if k not in allowed:
            raise IsolationError(f"{role} call may not receive {aid}")
        if k in {"hypotheses", "ledger"}:
            _, lineage, run, art_era = aid.split(":")
            if rater is None or (lineage, int(run)) != rater:
                raise IsolationError(f"{role} call for {rater} may not receive another rater's {aid}")
            if k == "hypotheses" and (era_order is None or era is None
                                      or era_order.index(art_era) >= era_order.index(era)):
                raise IsolationError(f"discovery for era {era} may not receive {aid}")
        if k in {"era", "chunk"} and era is not None and aid.split(":")[1] != era:
            raise IsolationError(f"{role} call for era {era} may not receive {aid}")


def assemble(role: str, slots: dict[str, str], resolve: Callable[[str], str],
             params: dict[str, str] | None = None, **allow_ctx) -> Prompt:
    """Fill `template:<role>`'s `{{slot}}`s from artifact ids; `params` are short labels only."""
    template_id = f"template:{role}"
    ids = [template_id, *slots.values()]
    check_allowlist(role, ids, **allow_ctx)
    texts = {aid: resolve(aid) for aid in ids}
    values = {**(params or {}), **{slot: texts[aid] for slot, aid in slots.items()}}
    template = texts[template_id]
    missing = set(_SLOT.findall(template)) - set(values)
    if missing:
        raise UsageError(f"template:{role} has unfilled slots {sorted(missing)}")
    text = _SLOT.sub(lambda m: values[m.group(1)], template)
    return Prompt(role, text, {aid: store.sha256_text(t) for aid, t in texts.items()})


def audit(prompt: Prompt, secrets: Secrets, after_blind_results: bool = False) -> None:
    """Secondary check by exact substring; the allowlist is the primary guarantee."""
    def hit(needles):
        return next((n for n in needles if n and n in prompt.text), None)

    if hit(secrets.redacted_names):
        raise IsolationError(f"{prompt.role} prompt carries an approved-redacted name")
    if prompt.role in ZONED_CONSUMERS and hit([s for s in secrets.removed_sentences
                                               if len(s) >= MIN_REMOVED_LEN]):
        raise IsolationError(f"{prompt.role} prompt carries a sentence the zoner removed")
    if hit(secrets.ipip):
        raise IsolationError(f"{prompt.role} prompt carries IPIP content")
    if hit(secrets.self_prediction) and not (prompt.role == "crosswalk" and after_blind_results):
        raise IsolationError(f"{prompt.role} prompt carries self-prediction content")
