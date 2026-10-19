"""Role policy: the single owner of what each model role may receive and how it is called.

SPEC § Approach, role input allowlists. Every consumer (prompt assembly, the substring
audit, the per-era budget check, the call boundary, the integrity audit) reads this table.
"""

from dataclasses import dataclass

from .errors import UsageError

__all__ = ["ROLES", "Role", "role"]


@dataclass(frozen=True)
class Role:
    name: str
    kinds: frozenset[str]          # artifact kinds the role may receive, besides its template and schema
    schema: str
    zoned_consumer: bool = False   # reads zoned material, so must never carry text the zoner removed
    per_era: bool = False          # one call per era; its era input must fit the budget at `prepare`
    params: frozenset[str] = frozenset()   # short labels the template may take outside artifacts
    rater_bound: frozenset[str] = frozenset()  # kinds that must belong to the calling rater


_ROLES = [
    Role("zoner", frozenset({"chunk"}), "zoner", per_era=True, params=frozenset({"era_label"})),
    Role("discovery", frozenset({"era", "hypotheses"}), "discovery", zoned_consumer=True, per_era=True,
         params=frozenset({"era_label", "hypotheses"}), rater_bound=frozenset({"hypotheses"})),
    Role("codebook_author", frozenset({"pool"}), "codebook", zoned_consumer=True),
    Role("recode", frozenset({"card", "era"}), "recode", zoned_consumer=True, per_era=True,
         params=frozenset({"era_label"})),
    Role("deductive_ledger", frozenset({"era"}), "ledger", zoned_consumer=True, per_era=True,
         params=frozenset({"era_label"})),
    Role("deductive_scorer", frozenset({"ledger"}), "scores", zoned_consumer=True, rater_bound=frozenset({"ledger"})),
    Role("crosswalk", frozenset({"constructs", "self_prediction"}), "crosswalk", zoned_consumer=True),
    Role("probe", frozenset(), "probe"),
]
ROLES: dict[str, Role] = {r.name: r for r in _ROLES}


def role(name: str) -> Role:
    if name not in ROLES:
        raise UsageError(f"unknown role {name!r}")
    return ROLES[name]
