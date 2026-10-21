import unittest

from abx import agreement, extract, temporal

OB, CO, NO = "observed", "contradicted", None

# (readings, fades, emergences, held, now): written out from the rules, independently of `trajectory`.
TABLE = [
    ([OB, CO], [("e1", "e2")], [], [], ("faded", "e2")),
    ([CO, OB], [], [("e1", "e2")], [], ("observed", "e2")),
    ([OB, CO, CO], [("e1", "e2")], [], [], ("faded", "e2")),
    ([CO, OB, OB], [], [("e1", "e2")], [], ("observed", "e3")),
    ([OB, NO, CO, NO, CO], [("e1", "e3")], [], ["e2"], ("faded", "e3")),
    ([OB, NO, NO], [], [], ["e2", "e3"], ("held", "e1")),
    ([OB, CO, NO], [("e1", "e2")], [], [], ("faded", "e2")),
    ([OB, CO, OB], [("e1", "e2")], [("e2", "e3")], [], ("observed", "e3")),
    ([OB, CO, OB, NO], [("e1", "e2")], [("e2", "e3")], ["e4"], ("held", "e3")),
    ([NO, NO], [], [], [], ("never observed", None)),
    ([CO, NO], [], [], [], ("never observed", None)),
    ([NO, OB], [], [], [], ("observed", "e2")),
    ([OB, OB, NO], [], [], ["e3"], ("held", "e2")),
]


class EraReadingTest(unittest.TestCase):
    def test_observed_comes_from_the_support_status(self):
        self.assertEqual(temporal.era_reading("supported", ["present", "insufficient"]), OB)
        self.assertEqual(temporal.era_reading("supported", ["present", "present"]), OB)

    def test_contradicted_needs_every_lineage_absent(self):
        self.assertEqual(temporal.era_reading("not-shown", ["absent", "absent"]), CO)
        for collapsed in (["absent", "insufficient"], ["absent", None], ["insufficient", "insufficient"],
                          ["present", "absent"], []):
            with self.subTest(collapsed=collapsed):
                self.assertIsNone(temporal.era_reading("not-shown", collapsed))

    def test_other_statuses_are_not_decisive(self):
        for status in ("contested", "one-lineage", "no-verdict"):
            with self.subTest(status=status):
                self.assertIsNone(temporal.era_reading(status, ["present", "insufficient"]))


class TrajectoryTest(unittest.TestCase):
    def test_hand_table(self):
        for readings, fades, emergences, held, (state, era) in TABLE:
            eras = [f"e{i + 1}" for i in range(len(readings))]
            with self.subTest(readings=readings):
                got = temporal.trajectory(dict(zip(eras, readings, strict=True)), eras)
                self.assertEqual(got["fades"], [{"from": a, "to": b} for a, b in fades])
                self.assertEqual(got["emergences"], [{"from": a, "to": b} for a, b in emergences])
                self.assertEqual(got["held"], held)
                self.assertEqual(got["now"], {"state": state, "era": era})
                self.assertEqual(got["eras"], dict(zip(eras, readings, strict=True)))


class ReadTest(unittest.TestCase):
    """Collapse and reading together, as `extract` wires them."""

    def three_way(self, runs: dict[str, dict[str, list[str]]]) -> dict:
        """{lineage: {era: [verdict per run]}} for item K1 → each lineage's three-way collapse."""
        shaped = {lin: {r: {extract.Unit("K1", era): verdicts[r] for era, verdicts in by_era.items()}
                        for r in range(len(next(iter(by_era.values()))))}
                  for lin, by_era in runs.items()}
        units = [extract.Unit("K1", era) for era in next(iter(runs.values()))]
        return agreement.collapse_runs(shaped, units, agreement.collapse_mode)

    def test_three_way_present_that_ties_binary_is_not_observed(self):
        runs = {lin: {"e1": ["present", "present", "absent", "insufficient"]} for lin in ("claude", "codex")}
        three = self.three_way(runs)
        self.assertEqual(three["claude"][extract.Unit("K1", "e1")], "present")
        binary = agreement.collapse_mode(["present", "present", "not_present", "not_present"])
        self.assertIsNone(binary)
        status = {"C01": {"e1": agreement.status([binary, binary])}}
        rows = temporal.read([{"id": "C01", "item_id": "K1"}], status, three, ["e1"])
        self.assertEqual(rows[0]["eras"], {"e1": None})
        self.assertEqual(rows[0]["now"], {"state": "never observed", "era": None})

    def test_a_three_way_tie_is_not_decisive(self):
        runs = {lin: {"e1": ["absent", "insufficient"]} for lin in ("claude", "codex")}
        rows = temporal.read([{"id": "C01", "item_id": "K1"}], {"C01": {"e1": "not-shown"}}, self.three_way(runs),
                             ["e1"])
        self.assertEqual(rows[0]["eras"], {"e1": None})

    def test_one_lineage_absent_between_observations_is_held(self):
        runs = {"claude": {"e1": ["present"] * 3, "e2": ["absent"] * 3, "e3": ["present"] * 3},
                "codex": {"e1": ["present"] * 3, "e2": ["insufficient"] * 3, "e3": ["present"] * 3}}
        status = {"C01": {"e1": "supported", "e2": "not-shown", "e3": "supported"}}
        rows = temporal.read([{"id": "C01", "item_id": "K1"}], status, self.three_way(runs), ["e1", "e2", "e3"])
        self.assertEqual((rows[0]["fades"], rows[0]["held"]), ([], ["e2"]))

    def test_both_lineages_absent_is_a_fade(self):
        runs = {lin: {"e1": ["present"] * 3, "e2": ["absent", "absent", "present"]} for lin in ("claude", "codex")}
        status = {"C01": {"e1": "supported", "e2": "not-shown"}}
        rows = temporal.read([{"id": "C01", "item_id": "K1"}], status, self.three_way(runs), ["e1", "e2"])
        self.assertEqual(rows[0]["fades"], [{"from": "e1", "to": "e2"}])
        self.assertEqual(rows[0]["now"], {"state": "faded", "era": "e2"})


if __name__ == "__main__":
    unittest.main()
