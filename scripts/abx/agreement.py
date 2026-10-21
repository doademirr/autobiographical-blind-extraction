"""Agreement arithmetic. Every number the report states about reliability comes from here.

Matrices are `{rater: {unit: value or None}}`, with any hashable unit (a named tuple in the
engine); None is a missing value (insufficient, a collapse tie, or no rating) and never takes
part in the coincidence counts. Undefined results carry a reason code, rendered by the report.
"""

import itertools
import math
from collections import Counter
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import NamedTuple

from .errors import AbxError

__all__ = ["INTEGRITY_TRIGGER", "MIN_PAIRED", "REPORT", "TENTATIVE", "ArmResult", "Check", "alpha", "arm", "band",
           "collapse_median", "collapse_mode", "collapse_runs", "integrity_audit", "status"]

REPORT = 0.80
TENTATIVE = 0.667
MIN_PAIRED = 0.50
INTEGRITY_TRIGGER = 0.95


def alpha(matrix: dict[str, dict[Hashable, object]], metric: str) -> tuple[float | None, str]:
    """Krippendorff's alpha (nominal or ordinal), after Krippendorff (2011).

    Returns (None, reason) when undefined: no unit has two values, or there is no
    variation to disagree about.
    """
    units = sorted({u for row in matrix.values() for u in row})
    coincidence: Counter = Counter()
    for u in units:
        vals = [row[u] for row in matrix.values() if row.get(u) is not None]
        if len(vals) < 2:
            continue
        for a, b in itertools.permutations(vals, 2):
            coincidence[(a, b)] += 1.0 / (len(vals) - 1)
    if not coincidence:
        return None, "no_pairable_unit"
    values = sorted({v for pair in coincidence for v in pair})
    marginal = {c: sum(coincidence[(c, k)] for k in values) for c in values}
    n = sum(marginal.values())

    def delta(c, k) -> float:
        if c == k:
            return 0.0
        if metric == "nominal":
            return 1.0
        if metric == "ordinal":
            lo, hi = sorted((c, k))
            between = sum(marginal[v] for v in values if lo <= v <= hi)
            return (between - (marginal[lo] + marginal[hi]) / 2.0) ** 2
        raise ValueError(f"unknown metric {metric!r}")

    observed = sum(delta(c, k) * w for (c, k), w in coincidence.items())
    expected = sum(delta(c, k) * marginal[c] * marginal[k] for c in values for k in values) / (n - 1)
    if expected == 0:
        return None, "no_variation"
    return 1.0 - observed / expected, ""


def collapse_mode(values: list) -> object:
    """Nominal collapse of one lineage's runs: the unique mode of at least two valid runs."""
    valid = [v for v in values if v is not None]
    if len(valid) < 2:
        return None
    top = Counter(valid).most_common()
    if len(top) > 1 and top[0][1] == top[1][1]:
        return None
    return top[0][0]


def collapse_median(values: list) -> int | None:
    """Ordinal collapse: the median of at least two valid runs, halves rounded up."""
    valid = sorted(v for v in values if v is not None)
    if len(valid) < 2:
        return None
    mid = len(valid) // 2
    median = valid[mid] if len(valid) % 2 else (valid[mid - 1] + valid[mid]) / 2
    return math.floor(median + 0.5)


def collapse_runs(runs: dict[str, dict[int, dict[Hashable, object]]], units: list[Hashable],
                  collapse: Callable[[list], object]) -> dict[str, dict[Hashable, object]]:
    """Each lineage's runs collapsed per unit: {lineage: {unit: value or None}}."""
    return {lineage: {u: collapse([by_run[r].get(u) for r in sorted(by_run)]) for u in units}
            for lineage, by_run in sorted(runs.items())}


def band(value: float | None) -> str:
    if value is None:
        return "not_reportable"
    if value >= REPORT:
        return "report"
    if value >= TENTATIVE:
        return "tentative"
    return "not_reportable"


@dataclass
class ArmResult:
    """One arm's gate: cross-lineage alpha on collapsed runs, plus its context figures."""

    metric: str
    units: list[Hashable]
    collapsed: dict[str, dict[Hashable, object]]
    paired_fraction: float
    alpha: float | None
    reason: str
    verdict: str
    stability: dict[str, float | None] = field(default_factory=dict)
    raw_agreement: float | None = None
    missing_rate: float = 0.0

    @property
    def integrity_audit_due(self) -> bool:
        return self.alpha is not None and self.alpha >= INTEGRITY_TRIGGER


def arm(runs: dict[str, dict[int, dict[Hashable, object]]], units: list[Hashable], metric: str) -> ArmResult:
    """`runs` is {lineage: {run: {unit: value}}}; units outside `units` are ignored."""
    collapsed = collapse_runs(runs, units, collapse_mode if metric == "nominal" else collapse_median)
    lineages = list(collapsed)
    paired = [u for u in units if all(collapsed[lin][u] is not None for lin in lineages)]
    paired_fraction = len(paired) / len(units) if units else 0.0
    missing = sum(1 for lin in lineages for u in units if collapsed[lin][u] is None)
    result = ArmResult(
        metric=metric, units=list(units), collapsed=collapsed, paired_fraction=paired_fraction,
        alpha=None, reason="", verdict="not_reportable",
        missing_rate=missing / (len(units) * len(lineages)) if units and lineages else 0.0,
    )
    if paired:
        result.raw_agreement = sum(
            1 for u in paired if len({collapsed[lin][u] for lin in lineages}) == 1
        ) / len(paired)
    for lineage, by_run in sorted(runs.items()):
        result.stability[lineage] = alpha(
            {r: {u: by_run[r].get(u) for u in units} for r in by_run}, metric
        )[0]
    if not units:
        result.reason = "no_units"
    elif len(lineages) < 2:
        result.reason = "fewer_lineages"
    elif paired_fraction < MIN_PAIRED:
        result.reason = "low_pairing"
    else:
        result.alpha, result.reason = alpha(collapsed, metric)
    result.verdict = band(result.alpha)
    return result


def status(values: list[object]) -> str:
    """Per construct per era, from the lineages' collapsed verdicts."""
    present = [v for v in values if v is not None]
    if not present:
        return "no-verdict"
    if len(present) < len(values):
        return "one-lineage"
    if len(set(present)) > 1:
        return "contested"
    return "supported" if present[0] == "present" else "not-shown"


class Check(NamedTuple):
    """One integrity check's outcome: a reason code and named counts, rendered by the report."""

    ok: bool
    code: str
    counts: dict


def integrity_audit(checks: dict[str, Callable[[], Check]]) -> dict[str, dict]:
    """Run every check, even after one fails; high agreement alone never invalidates.

    A check that fails on the harness's own typed errors (a broken manifest, a refused requalification)
    is a failed check and the rest still run; any other exception is a defect and propagates.
    """
    results = {}
    for name, check in checks.items():
        try:
            outcome = check()
        except AbxError as exc:
            outcome = Check(False, f"error_{type(exc).__name__}", {})
        results[name] = outcome._asdict()
    return results
