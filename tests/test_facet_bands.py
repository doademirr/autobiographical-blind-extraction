import unittest
from fractions import Fraction

from abx import report, unmask

INSTRUMENT = {"facets": {"N1": "Anxiety", "N2": "Anger", "E1": "Friendliness", "E2": "Gregariousness"}}


class FacetComparisonTest(unittest.TestCase):
    def test_hand_fixture(self):
        observer = {"facets": {"N1": Fraction(6), "N2": None, "E1": Fraction(4), "E2": Fraction(2)}}
        self_report = {"facets": {"N1": Fraction(4), "N2": Fraction(2), "E1": Fraction(3), "E2": None}}
        got = unmask.facet_comparison(observer, self_report, INSTRUMENT)
        self.assertEqual(list(got["facets"]), ["N1", "N2", "E1", "E2"])
        self.assertEqual(got["facets"]["N1"], {"observer": 6.0, "observer_band": "high", "ipip": 4.0,
                                               "ipip_band": "high", "same_band": True})
        self.assertEqual(got["facets"]["N2"]["same_band"], None)  # observer missing (a lineage lacked a score)
        self.assertEqual(got["facets"]["E1"]["observer_band"], "mid")
        self.assertEqual(got["facets"]["E1"]["same_band"], True)  # 4 is mid on 1-7, 3 is mid on 1-5
        self.assertEqual(got["facets"]["E2"]["same_band"], None)  # IPIP missing (too few items answered)
        self.assertEqual((got["observer_missing"], got["ipip_missing"], got["compared"], got["same_band_rate"]),
                         (1, 1, 2, 1.0))

    def test_different_bands(self):
        observer = {"facets": dict.fromkeys(INSTRUMENT["facets"], Fraction(2))}
        self_report = {"facets": dict.fromkeys(INSTRUMENT["facets"], Fraction(4))}
        got = unmask.facet_comparison(observer, self_report, INSTRUMENT)
        self.assertEqual((got["compared"], got["same_band_rate"]), (4, 0.0))

    def test_nothing_compared_still_shows_every_row(self):
        observer = {"facets": dict.fromkeys(INSTRUMENT["facets"])}
        self_report = {"facets": {**dict.fromkeys(INSTRUMENT["facets"], Fraction(3)), "N1": None}}
        got = unmask.facet_comparison(observer, self_report, INSTRUMENT)
        self.assertEqual((len(got["facets"]), got["compared"], got["same_band_rate"]), (4, 0, None))
        lines = report._facet_bands({"facet_bands": got, "facet_names": INSTRUMENT["facets"]})
        self.assertIn("Same band in n/a of 0 facets compared.", "\n".join(lines))
        self.assertEqual(sum(line.startswith("| N") or line.startswith("| E") for line in lines), 4)


if __name__ == "__main__":
    unittest.main()
