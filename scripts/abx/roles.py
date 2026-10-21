"""Role policy: the single owner of what each model role may receive and how it is called.

Every consumer (prompt assembly, the substring audit, the per-era budget check, the call
boundary, the integrity audit) reads this table.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .errors import UsageError

__all__ = ["ROLES", "Role", "role"]


@dataclass(frozen=True)
class Role:
    name: str
    kinds: frozenset[str]          # artifact kinds the role may receive, besides its template and schema
    schema: str
    zoned_consumer: bool = False   # reads zoned material, so must never carry text the zoner removed
    per_era: bool = False          # calls per era; each must fit the budget at `prepare`
    chunked: bool = False          # per era in parts of at most 300 sentences, sized per part, never per era
    params: frozenset[str] = frozenset()   # labels the call boundary derives from the workspace, never callers
    rater_bound: frozenset[str] = frozenset()  # kinds that must belong to the calling rater
    single: str | None = None      # the config role naming the one lineage it runs on; None runs on every rater


_ROLES = [
    Role("zoner", frozenset({"chunk"}), "zoner", per_era=True, chunked=True, params=frozenset({"era_label"}),
         single="zoner"),
    # The zoner's output schema, so each judge label lines up one to one with a zoner label.
    Role("calibration_judge", frozenset({"excerpt"}), "zoner", per_era=True, chunked=True),
    Role("discovery", frozenset({"era", "hypotheses"}), "discovery", zoned_consumer=True, per_era=True,
         params=frozenset({"era_label", "hypotheses"}), rater_bound=frozenset({"hypotheses"})),
    Role("foil_author", frozenset({"era"}), "foils", zoned_consumer=True, per_era=True,
         params=frozenset({"era_label"}), single="foil_author"),
    Role("codebook_author", frozenset({"pool"}), "codebook", zoned_consumer=True, single="codebook_author"),
    Role("auditor", frozenset({"codebook", "foils", "era"}), "audit", zoned_consumer=True, per_era=True,
         params=frozenset({"era_label"}), single="auditor"),
    Role("facet_mapper", frozenset({"definitions", "facets"}), "facetmap", zoned_consumer=True,
         single="facet_mapper"),
    Role("recode", frozenset({"card", "era"}), "recode", zoned_consumer=True, per_era=True,
         params=frozenset({"era_label"})),
    Role("deductive_ledger", frozenset({"era", "facets"}), "ledger", zoned_consumer=True, per_era=True,
         params=frozenset({"era_label"})),
    Role("deductive_scorer", frozenset({"ledgers", "facets"}), "scores", zoned_consumer=True,
         rater_bound=frozenset({"ledgers"})),
    Role("crosswalk", frozenset({"constructs", "self_prediction", "facets"}), "crosswalk", zoned_consumer=True),
    Role("probe", frozenset(), "probe"),
]
ROLES: Mapping[str, Role] = MappingProxyType({r.name: r for r in _ROLES})


def role(name: str) -> Role:
    if name not in ROLES:
        raise UsageError(f"unknown role {name!r}")
    return ROLES[name]
