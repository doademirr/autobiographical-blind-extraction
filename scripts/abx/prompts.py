"""Prompt assembly from artifact ids, the allowlist check, and the secondary substring audit.

A prompt is built only from artifact ids (resolved to workspace files) plus the short labels
its role declares, so every call's provenance is the id list it records.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from . import artifacts, store
from .errors import IsolationError, UsageError
from .roles import role as get_role
from .text import name_pattern
from .withheld import MIN_REMOVED_LEN, Withheld

__all__ = ["MAX_PARAM_LEN", "Prompt", "assemble", "audit", "check_allowlist"]

FRAME_KINDS = {"template", "schema"}
MAX_PARAM_LEN = 200
_SLOT = re.compile(r"\{\{([a-z_]+)\}\}")


SHIPPED_TEMPLATES = Path(__file__).resolve().parents[2] / "prompts"


@dataclass(frozen=True)
class Prompt:
    """`supplied` is what filled the template's slots (inputs, schema and labels); `shipped_template` says the
    template is byte-identical to the one this harness ships, so its own wording is not the user's text."""

    role: str
    text: str
    artifacts: Mapping[str, str]  # artifact id -> sha256 of its text
    supplied: str = ""
    shipped_template: bool = False


def check_allowlist(role: str, ids: list[str], rater: tuple[str, int] | None = None,
                    era: str | None = None, era_order: list[str] | None = None, revealed: bool = False) -> None:
    """`revealed`: generation C is frozen, so sealed comparators may reach the roles allowed them."""
    policy = get_role(role)
    if policy.per_era and era is None:
        raise IsolationError(f"{role} runs per era; its call must name the era")
    for aid in ids:
        ref = artifacts.parse(aid)
        if ref.kind == "self_prediction" and not revealed:
            raise IsolationError(f"{role} call may not receive the sealed self-prediction before generation C")
        if ref.kind in FRAME_KINDS:
            if ref.kind == "template" and ref.role != role:
                raise IsolationError(f"{role} call may not use another role's template {aid}")
            if ref.kind == "schema" and ref.name != policy.schema:
                raise IsolationError(f"{role} call may not use another role's schema {aid}")
            continue
        if ref.kind not in policy.kinds:
            raise IsolationError(f"{role} call may not receive {aid}")
        if ref.kind in policy.rater_bound and (rater is None or (ref.lineage, ref.run) != rater):
            raise IsolationError(f"{role} call for {rater} may not receive another rater's {aid}")
        if ref.kind == "hypotheses":
            order = era_order or []
            if era not in order or ref.era not in order or order.index(ref.era) >= order.index(era):
                raise IsolationError(f"discovery for era {era} may not receive {aid}")
        # Every input named by era belongs to the call's own era; hypotheses (earlier eras) are checked above.
        if ref.kind != "hypotheses" and ref.era is not None and era is not None and ref.era != era:
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
    shipped = SHIPPED_TEMPLATES / f"{role}.md"
    return Prompt(role, _SLOT.sub(lambda m: values[m.group(1)], template),
                  MappingProxyType({aid: store.sha256_text(t) for aid, t in texts.items()}),
                  supplied="\n".join(values[k] for k in sorted(values)),
                  shipped_template=shipped.exists() and shipped.read_text(encoding="utf-8") == template)


def audit(prompt: Prompt, withheld: Withheld, after_blind_results: bool = False) -> None:
    """Secondary check; the allowlist is the primary guarantee. Approved-redacted names match whole-word, as redaction
    does, outside an unchanged shipped template; the rest match as exact substrings of the whole prompt."""
    def hit(needles):
        return next((n for n in needles if n and n in prompt.text), None)

    names = [n for n in withheld.redacted_names if n]
    if names and name_pattern(names).search(prompt.supplied if prompt.shipped_template else prompt.text):
        raise IsolationError(f"{prompt.role} prompt carries an approved-redacted name")
    if get_role(prompt.role).zoned_consumer and hit([s for s in withheld.removed_sentences
                                                     if len(s) >= MIN_REMOVED_LEN]):
        raise IsolationError(f"{prompt.role} prompt carries a sentence the zoner removed")
    if hit(withheld.ipip):
        raise IsolationError(f"{prompt.role} prompt carries IPIP content")
    if hit(withheld.self_prediction) and not (prompt.role == "crosswalk" and after_blind_results):
        raise IsolationError(f"{prompt.role} prompt carries self-prediction content")
