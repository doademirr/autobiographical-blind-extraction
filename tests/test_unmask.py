import unittest

from abx import ipip, unmask


def codes(rows: list[tuple[str, str, str]]) -> list[dict]:
    return [{"prediction_id": p, "construct_id": c, "code": code, "polarity": "same"} for p, c, code in rows]


class PredictionRatesTest(unittest.TestCase):
    """Hand-computed against SPEC § Comparisons, inductive vs self-prediction."""

    def test_matched_partial_ambiguous_and_multiple(self):
        a = codes([("P1", "C01", "match"), ("P1", "C02", "match"),   # P1 matches two constructs: counts once
                   ("P2", "C01", "partial"), ("P2", "C02", "none"),
                   ("P3", "C01", "match"), ("P3", "C02", "none"),
                   ("P4", "C01", "none"), ("P4", "C02", "none")])
        b = codes([("P1", "C01", "match"), ("P1", "C02", "partial"),
                   ("P2", "C01", "partial"), ("P2", "C02", "none"),
                   ("P3", "C01", "partial"), ("P3", "C02", "none"),   # coders disagree: ambiguous
                   ("P4", "C01", "none"), ("P4", "C02", "none")])
        r = unmask.prediction_rates({"claude": a, "codex": b}, ["P1", "P2", "P3", "P4"], {"C01", "C02"})
        self.assertEqual(r["outcome"], {"P1": "matched", "P2": "partial", "P3": "ambiguous", "P4": "unmatched"})
        self.assertEqual(r["predictions_decided"], 3)
        self.assertAlmostEqual(r["predictions_matched_rate"], 1 / 3)
        self.assertEqual(r["constructs_matched"], ["C01"])
        self.assertAlmostEqual(r["supported_constructs_matched_rate"], 1 / 2)
        self.assertAlmostEqual(r["coder_agreement"], 6 / 8)

    def test_ineligible_constructs_are_descriptive_only(self):
        rows = codes([("P1", "C01", "match"), ("P1", "C02", "match")])
        r = unmask.prediction_rates({"claude": rows, "codex": rows}, ["P1"], {"C03"})
        self.assertEqual(r["outcome"], {"P1": "unmatched"})
        self.assertEqual(r["descriptive_matches"], ["P1~C01", "P1~C02"])
        self.assertEqual(r["constructs_matched"], [])

    def test_zero_denominators_are_none(self):
        rows = codes([("P1", "C01", "match")])
        ambiguous = codes([("P1", "C01", "none")])
        r = unmask.prediction_rates({"claude": rows, "codex": ambiguous}, ["P1"], set())
        self.assertEqual(r["outcome"], {"P1": "unmatched"})
        r = unmask.prediction_rates({"claude": rows, "codex": ambiguous}, ["P1"], {"C01"})
        self.assertIsNone(r["predictions_matched_rate"])
        empty = unmask.prediction_rates({"claude": [], "codex": []}, [], set())
        self.assertIsNone(empty["supported_constructs_matched_rate"])


class DomainComparisonTest(unittest.TestCase):
    def test_bands_and_rate(self):
        inst = ipip.load_instrument()
        collapsed = {"claude": dict.fromkeys(inst["facets"], 6), "codex": dict.fromkeys(inst["facets"], 5)}
        collapsed["codex"].update({f: None for f in inst["facets"] if f.startswith("N")})
        observer = unmask.deductive_domains(collapsed, inst)
        self.assertIsNone(observer["domains"]["N"])
        self.assertEqual(observer["domains"]["E"], 5.5)
        self_report = {"domains": {"N": 3.0, "E": 4.0, "O": 2.0, "A": 3.0, "C": None}}
        cmp = unmask.domain_comparison(observer, self_report)
        self.assertEqual(cmp["compared"], 3)
        self.assertEqual([cmp["domains"][d]["same_band"] for d in "EOA"], [True, False, False])
        self.assertAlmostEqual(cmp["agreement_rate"], 1 / 3)


if __name__ == "__main__":
    unittest.main()
