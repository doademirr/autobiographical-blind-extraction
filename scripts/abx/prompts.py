"""Prompt assembly from artifact ids, the allowlist check, and the secondary substring audit.

A prompt is built only from artifact ids (resolved to workspace files) plus the short labels
its role declares, so every call's provenance is the id list it records.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from . import artifacts, store
from .errors import IsolationError, UsageError
from .roles import role as get_role
from .withheld import MIN_REMOVED_LEN, Withheld

__all__ = ["Prompt", "assemble", "audit", "check_allowlist"]

FRAME_KINDS = {"template", "schema"}
MAX_PARAM_LEN = 200
_SLOT = re.compile(r"\{\{([a-z_]+)\}\}")


@dataclass(frozen=True)
class Prompt:
    role: str
    text: str
    artifacts: dict[str, str]  # artifact id -> sha256 of its text


def check_allowlist(role: str, ids: list[str], rater: tuple[str, int] | None = None,
                    era: str | None = None, era_order: list[str] | None = None) -> None:
    policy = get_role(role)
    for aid in ids:
        ref = artifacts.parse(aid)
        if ref.kind in FRAME_KINDS:
            if ref.kind == "template" and ref.role != role:
                raise IsolationError(f"{role} call may not use another role's template {aid}")
            continue
        if ref.kind not in policy.kinds:
            raise IsolationError(f"{role} call may not receive {aid}")
        if ref.kind in policy.rater_bound and (rater is None or (ref.lineage, ref.run) != rater):
            raise IsolationError(f"{role} call for {rater} may not receive another rater's {aid}")
        if ref.kind == "hypotheses":
            order = era_order or []
            if era not in order or ref.era not in order or order.index(ref.era) >= order.index(era):
                raise IsolationError(f"discovery for era {era} may not receive {aid}")
        if ref.kind in {"era", "chunk"} and era is not None and ref.era != era:
            raise IsolationError(f"{role} call for era {era} may not receive {aid}")


def assemble(role: str, slots: dict[str, str], resolve: Callable[[str], str],
             params: dict[str, str] | None = None, **allow_ctx) -> Prompt:
    """Fill `template:<role>`'s `{{slot}}`s from artifact ids and the role's declared labels."""
    policy = get_role(role)
    params = params or {}
    for name, value in params.items():
        if name not in policy.params:
            raise UsageError(f"{role} takes no {name!r} label")
        if len(value) > MAX_PARAM_LEN or "\n" in value:
            raise UsageError(f"{role} label {name!r} must be one short line")
    template_id = f"template:{role}"
    ids = [template_id, *slots.values()]
    check_allowlist(role, ids, **allow_ctx)
    texts = {aid: resolve(aid) for aid in ids}
    values = {**params, **{slot: texts[aid] for slot, aid in slots.items()}}
    template = texts[template_id]
    missing = set(_SLOT.findall(template)) - set(values)
    if missing:
        raise UsageError(f"template:{role} has unfilled slots {sorted(missing)}")
    text = _SLOT.sub(lambda m: values[m.group(1)], template)
    return Prompt(role, text, {aid: store.sha256_text(t) for aid, t in texts.items()})


def audit(prompt: Prompt, withheld: Withheld, after_blind_results: bool = False) -> None:
    """Secondary check by exact substring; the allowlist is the primary guarantee."""
    def hit(needles):
        return next((n for n in needles if n and n in prompt.text), None)

    if hit(withheld.redacted_names):
        raise IsolationError(f"{prompt.role} prompt carries an approved-redacted name")
    if get_role(prompt.role).zoned_consumer and hit([s for s in withheld.removed_sentences
                                                     if len(s) >= MIN_REMOVED_LEN]):
        raise IsolationError(f"{prompt.role} prompt carries a sentence the zoner removed")
    if hit(withheld.ipip):
        raise IsolationError(f"{prompt.role} prompt carries IPIP content")
    if hit(withheld.self_prediction) and not (prompt.role == "crosswalk" and after_blind_results):
        raise IsolationError(f"{prompt.role} prompt carries self-prediction content")
