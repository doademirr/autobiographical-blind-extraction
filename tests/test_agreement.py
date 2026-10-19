import random
import unittest

from abx import agreement as ag

N = None


def _matrix(rows: dict[str, list]) -> dict[str, dict[str, object]]:
    return {r: {f"u{i:02d}": v for i, v in enumerate(vs)} for r, vs in rows.items()}


class KrippendorffWorkedExamplesTest(unittest.TestCase):
    """Krippendorff (2011), 'Computing Krippendorff's Alpha-Reliability'."""

    def test_binary_two_observers(self):
        m = _matrix({"A": [0, 1, 0, 0, 0, 0, 0, 0, 1, 0], "B": [1, 1, 1, 0, 0, 1, 0, 0, 0, 0]})
        self.assertAlmostEqual(ag.alpha(m, "nominal")[0], 0.095, places=3)

    def test_four_observers_with_missing(self):
        m = _matrix({
            "A": [1, 2, 3, 3, 2, 1, 4, 1, 2, N, N, N],
            "B": [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, N, 3],
            "C": [N, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, N],
            "D": [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, N],
        })
        self.assertAlmostEqual(ag.alpha(m, "nominal")[0], 0.743, places=3)
        self.assertAlmostEqual(ag.alpha(m, "ordinal")[0], 0.815, places=3)

    def test_uniform_is_undefined_and_identical_is_one(self):
        self.assertIsNone(ag.alpha(_matrix({"A": ["x"] * 5, "B": ["x"] * 5}), "nominal")[0])
        same = ["present", "absent", "present", "absent"]
        self.assertEqual(ag.alpha(_matrix({"A": same, "B": same}), "nominal")[0], 1.0)

    def test_no_pairable_unit_is_undefined(self):
        self.assertIsNone(ag.alpha(_matrix({"A": [1, N], "B": [N, 2]}), "nominal")[0])


class CollapseTest(unittest.TestCase):
    def test_mode_needs_two_valid_runs_and_no_tie(self):
        self.assertEqual(ag.collapse_mode(["present", "present", "absent"]), "present")
        self.assertEqual(ag.collapse_mode(["present", N, "present"]), "present")
        self.assertIsNone(ag.collapse_mode(["present", "absent", N]))
        self.assertIsNone(ag.collapse_mode(["present", N, N]))

    def test_rounded_median(self):
        self.assertEqual(ag.collapse_median([3, 5, 6]), 5)
        self.assertEqual(ag.collapse_median([4, 5, N]), 5)
        self.assertEqual(ag.collapse_median([2, 3]), 3)
        self.assertIsNone(ag.collapse_median([4, N, N]))


def _runs(per_lineage: dict[str, list[list]]) -> dict:
    return {lin: {f"r{i + 1}": {f"u{j:02d}": v for j, v in enumerate(run)} for i, run in enumerate(runs)}
            for lin, runs in per_lineage.items()}


class ArmTest(unittest.TestCase):
    UNITS = tuple(f"u{j:02d}" for j in range(12))

    def test_random_matrix_is_not_reportable(self):
        rng = random.Random(7)

        def draw():
            return [rng.choice(["present", "absent"]) for _ in self.UNITS]

        res = ag.arm(_runs({"claude": [draw() for _ in range(3)], "codex": [draw() for _ in range(3)]}),
                     list(self.UNITS), "nominal")
        self.assertEqual(res.verdict, "not_reportable")
        self.assertFalse(res.integrity_audit_due)

    def test_high_agreement_triggers_audit(self):
        base = ["present", "absent"] * 6
        res = ag.arm(_runs({"claude": [base] * 3, "codex": [base] * 3}), list(self.UNITS), "nominal")
        self.assertEqual(res.alpha, 1.0)
        self.assertEqual(res.verdict, "report")
        self.assertTrue(res.integrity_audit_due)
        self.assertEqual(res.raw_agreement, 1.0)
        self.assertEqual(res.stability["claude"], 1.0)

    def test_mixed_matrix_yields_each_status(self):
        claude = ["present", "present", "absent", "absent", "present", N] + ["present", "absent"] * 3
        codex = ["present", "absent", "absent", "present", N, N] + ["present", "absent"] * 3
        res = ag.arm(_runs({"claude": [claude] * 3, "codex": [codex] * 3}), list(self.UNITS), "nominal")
        statuses = [ag.status([res.collapsed[lin][u] for lin in ("claude", "codex")]) for u in self.UNITS[:6]]
        self.assertEqual(statuses, ["supported", "contested", "absent-supported", "contested",
                                    "one-lineage", "no-verdict"])

    def test_low_pairing_makes_alpha_undefined(self):
        claude = ["present", "absent", "present"] + [N] * 9
        codex = ["present", "absent", "present", "absent"] + [N] * 8
        res = ag.arm(_runs({"claude": [claude] * 3, "codex": [codex] * 3}), list(self.UNITS), "nominal")
        self.assertIsNone(res.alpha)
        self.assertEqual(res.verdict, "not_reportable")
        self.assertEqual(res.reason, "low_pairing")

    def test_one_lineage_is_never_supported(self):
        self.assertEqual(ag.status(["present", N]), "one-lineage")

    def test_units_filter_excludes_foils(self):
        constructs = ["present", "absent"] * 3
        foils_c, foils_x = ["present"] * 6, ["absent"] * 6
        runs = _runs({"claude": [constructs + foils_c] * 3, "codex": [constructs + foils_x] * 3})
        only = ag.arm(runs, list(self.UNITS[:6]), "nominal")
        both = ag.arm(runs, list(self.UNITS), "nominal")
        self.assertEqual(only.alpha, 1.0)
        self.assertLess(both.alpha, only.alpha)

    def test_ordinal_arm_collapses_by_median(self):
        units = list(self.UNITS[:6])
        claude = [[1, 2, 4, 5, 6, 7], [2, 2, 4, 5, 6, 7], [1, 3, 4, 5, 7, 7]]
        codex = [[1, 2, 4, 5, 6, 7]] * 3
        res = ag.arm(_runs({"claude": claude, "codex": codex}), units, "ordinal")
        self.assertEqual(res.collapsed["claude"]["u00"], 1)
        self.assertGreater(res.alpha, 0.95)


class IntegrityAuditTest(unittest.TestCase):
    def test_every_check_runs_and_only_failures_invalidate(self):
        ran = []

        def check(name, ok):
            def run():
                ran.append(name)
                return ok, name
            return run

        res = ag.integrity_audit({"requalify": check("requalify", True), "events": check("events", True),
                                  "allowlist": check("allowlist", True), "manifest": check("manifest", True)})
        self.assertEqual(ran, ["requalify", "events", "allowlist", "manifest"])
        self.assertTrue(all(r["ok"] for r in res.values()))
        res = ag.integrity_audit({"events": check("events", False)})
        self.assertFalse(res["events"]["ok"])

        def broken():
            raise RuntimeError("cannot read records")

        res = ag.integrity_audit({"requalify": broken, "manifest": check("manifest", True)})
        self.assertFalse(res["requalify"]["ok"])
        self.assertIn("RuntimeError", res["requalify"]["detail"])
        self.assertNotIn("cannot read records", res["requalify"]["detail"])
        self.assertTrue(res["manifest"]["ok"])


if __name__ == "__main__":
    unittest.main()
