import itertools
import unittest
from fractions import Fraction

from abx import divergence, prompts, store, unmask
from abx.errors import IsolationError

from .helpers import FakeWorkspace, build
from .recompute import _record, problems


def expected_class(b, s, t):
    """Written out from the class table, independently of `classify`."""
    present = [x for x in (b, s, t) if x is not None]
    if not present:
        return None
    if "conflict" in present:
        return "divergent"
    if "high" in present and "low" in present:
        return "divergent"
    if b and s and t:
        return "all three"
    if b and s:
        return "blind and self"
    if b:
        return "blind only"
    if s:
        return "self only"
    return "test only"


class ClassifyTest(unittest.TestCase):
    def test_every_combination_of_poles(self):
        sides = (None, "high", "low", "conflict")
        cases = list(itertools.product(sides, sides, (None, "high", "low")))
        self.assertEqual(len(cases), 48)
        for b, s, t in cases:
            with self.subTest(blind=b, self_=s, test=t):
                self.assertEqual(divergence.classify(b, s, t), expected_class(b, s, t))

    def test_named_cases(self):
        self.assertEqual(divergence.classify("high", None, "low"), "divergent")  # test contradicts the lone view
        self.assertEqual(divergence.classify(None, "low", "high"), "divergent")
        self.assertEqual(divergence.classify("high", "high", "low"), "divergent")
        self.assertEqual(divergence.classify("high", None, "high"), "blind only")
        self.assertEqual(divergence.classify(None, None, "low"), "test only")
        self.assertIsNone(divergence.classify(None, None, None))


class PoleTest(unittest.TestCase):
    def test_poles(self):
        self.assertEqual(divergence.pole([]), None)
        self.assertEqual(divergence.pole(["+", "+"]), "high")
        self.assertEqual(divergence.pole(["-"]), "low")
        self.assertEqual(divergence.pole(["+", "-"]), "conflict")

    def test_a_construct_conflict_is_never_hidden_by_the_observer(self):
        for band in ("high", "low", "mid", None):
            self.assertEqual(divergence.blind_pole("conflict", band), "conflict")
        self.assertEqual(divergence.blind_pole("high", "low"), "conflict")
        self.assertEqual(divergence.blind_pole("high", "high"), "high")
        self.assertEqual(divergence.blind_pole(None, "low"), "low")
        self.assertEqual(divergence.blind_pole("low", "mid"), "low")
        self.assertEqual(divergence.blind_pole(None, "mid"), None)

    def test_a_prediction_tag_counts_only_when_both_coders_give_it(self):
        tags = {"claude": [{"prediction_id": "P1", "facets": [{"facet": "N1", "polarity": "+"},
                                                              {"facet": "C5", "polarity": "+"}]},
                           {"prediction_id": "P2", "facets": [{"facet": "E1", "polarity": "-"}]}],
                "codex": [{"prediction_id": "P1", "facets": [{"facet": "N1", "polarity": "+"},
                                                             {"facet": "C5", "polarity": "-"}]},
                          {"prediction_id": "P2", "facets": []}]}
        agreed, ambiguous = divergence.prediction_facets(tags)
        self.assertEqual(agreed, {"N1": [{"prediction_id": "P1", "polarity": "+"}]})
        self.assertEqual(ambiguous, [{"prediction_id": "P1", "facet": "C5"}, {"prediction_id": "P2", "facet": "E1"}])


class BuildMapTest(unittest.TestCase):
    def test_rows_by_hand(self):
        facet_map = {"C01": [{"facet": "N1", "polarity": "+"}], "C02": [{"facet": "N1", "polarity": "-"}],
                     "C03": [{"facet": "E1", "polarity": "+"}], "C09": [{"facet": "A1", "polarity": "+"}]}
        observer = {"N1": Fraction(6), "E1": Fraction(4), "A1": Fraction(2), "C5": None, "O1": Fraction(4)}
        ipip_facets = {"N1": Fraction(3), "E1": Fraction(4), "A1": Fraction(3), "C5": Fraction(2), "O1": Fraction(3)}
        tags = {c: [{"prediction_id": "P1", "facets": [{"facet": "E1", "polarity": "+"}]}] for c in ("x", "y")}
        got = divergence.build_map(facet_map, {"C01", "C02", "C03"}, observer, ipip_facets, tags, True)
        self.assertEqual([(r["facet"], r["class"], r["blind"], r["self"], r["test"]) for r in got["rows"]], [
            ("N1", "divergent", "conflict", None, None),        # constructs point both ways
            ("E1", "all three", "high", "high", "high"),
            ("A1", "blind only", "low", None, None),            # C09 is not supported; the observer is low
            ("C5", "test only", None, None, "low"),
        ])
        self.assertEqual(got["rows"][0]["constructs"], [{"construct_id": "C01", "polarity": "+"},
                                                        {"construct_id": "C02", "polarity": "-"}])
        self.assertEqual(got["counts"]["divergent"], 1)
        self.assertNotIn("O1", {r["facet"] for r in got["rows"]})  # every side silent


class PipelineTest(unittest.TestCase):
    def test_the_map_recomputes_and_the_coders_get_no_ipip(self):
        fw = FakeWorkspace()
        self.addCleanup(fw.close)
        ws = build(fw)
        unmask.unmask(ws)
        results = store.read_json(ws.path("report/results.json"))
        self.assertTrue(results["divergence"]["rows"] and results["divergence"]["ambiguous"])
        self.assertEqual(problems(ws), [])
        for coder in ("claude", "codex"):
            rec = store.read_json(ws.path(_record(ws, "unmask", "crosswalk", coder, "D")))
            self.assertEqual(sorted(rec["input_artifacts"]), ["constructs:all", "facets:all", "schema:crosswalk",
                                                              "self_prediction:sealed", "template:crosswalk"])
        prompts.check_allowlist("crosswalk", ["facets:all"])
        with self.assertRaises(IsolationError):
            prompts.check_allowlist("crosswalk", ["era:e1"])

    def test_the_crosswalk_validator_takes_every_prediction_once_without_repeated_facets(self):
        fw = FakeWorkspace()
        self.addCleanup(fw.close)
        ws = build(fw)
        real = unmask.invoke.call
        seen = []

        def capture(ws_, cfg, req):
            seen.append(req.validate)
            return real(ws_, cfg, req)

        from unittest import mock
        with mock.patch.object(unmask.invoke, "call", side_effect=capture):
            unmask.unmask(ws)
        validate = seen[0]
        out = store.read_json(ws.path("run/crosswalk/codes-claude.json"))
        good = {"codes": out["codes"], "predictions": out["predictions"]}
        self.assertEqual(validate(good), [])
        first = out["predictions"][0]
        none = {**good, "predictions": [{**first, "facets": []}, *out["predictions"][1:]]}
        self.assertEqual(validate(none), [])  # a prediction no facet fits
        for facets in ([{"facet": "N1", "polarity": "+"}, {"facet": "N1", "polarity": "+"}],
                       [{"facet": "N1", "polarity": "+"}, {"facet": "N1", "polarity": "-"}]):
            dup = {**good, "predictions": [{**first, "facets": facets}, *out["predictions"][1:]]}
            self.assertEqual(validate(dup), [f"{first['prediction_id']} lists a facet twice"])
        self.assertEqual(len(validate({**good, "predictions": out["predictions"][1:]})), 1)


if __name__ == "__main__":
    unittest.main()
