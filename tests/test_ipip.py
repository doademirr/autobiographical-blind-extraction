import collections
import unittest

from abx import ipip
from abx.errors import UsageError


class InstrumentTest(unittest.TestCase):
    def test_shape(self):
        inst = ipip.load_instrument()
        self.assertEqual(len(inst["items"]), 120)
        per_facet = collections.Counter(i["facet"] for i in inst["items"])
        self.assertEqual(len(per_facet), 30)
        self.assertEqual(set(per_facet.values()), {4})
        self.assertEqual(set(inst["domains"]), {"N", "E", "O", "A", "C"})


class ScoringTest(unittest.TestCase):
    def setUp(self):
        self.inst = ipip.load_instrument()
        self.items = {f: [i for i in self.inst["items"] if i["facet"] == f] for f in self.inst["facets"]}

    def _answers(self, facet: str, raw: list) -> dict:
        return {i["id"]: r for i, r in zip(self.items[facet], raw, strict=True)}

    def test_hand_scored_facet_with_reversed_items(self):
        facet = next(f for f, its in self.items.items() if any(i["key"] == -1 for i in its))
        raw = [5, 4, 2, 1]
        expected = sum(r if i["key"] == 1 else 6 - r for i, r in zip(self.items[facet], raw, strict=True)) / 4
        responses = dict.fromkeys((i["id"] for i in self.inst["items"]), 3)
        responses.update(self._answers(facet, raw))
        self.assertAlmostEqual(ipip.score(responses, self.inst)["facets"][facet], expected)

    def test_missing_items_and_facets(self):
        responses = dict.fromkeys((i["id"] for i in self.inst["items"]), 4)
        n_facets = [f for f in self.inst["facets"] if f.startswith("N")]
        responses.update(self._answers(n_facets[0], [4, 4, None, None]))
        responses.update(self._answers(n_facets[1], [4, 4, 4, None]))
        scored = ipip.score(responses, self.inst)
        self.assertIsNone(scored["facets"][n_facets[0]])
        self.assertIsNotNone(scored["facets"][n_facets[1]])
        self.assertIsNotNone(scored["domains"]["N"])
        for f in n_facets[1:3]:
            responses.update(self._answers(f, [4, None, None, None]))
        self.assertIsNone(ipip.score(responses, self.inst)["domains"]["N"])

    def test_domain_mean_of_exactly_eleven_thirds_is_high_on_every_python(self):
        n_facets = [f for f in self.inst["facets"] if f.startswith("N")]
        responses = dict.fromkeys((i["id"] for i in self.inst["items"]), None)

        def answer(facet, scored):
            for item, s in zip(self.items[facet], scored, strict=False):
                responses[item["id"]] = s if item["key"] == 1 else 6 - s

        answer(n_facets[0], [1, 2, 2])
        for f in n_facets[1:4]:
            answer(f, [4, 4, 5])
        domain = ipip.score(responses, self.inst)["domains"]["N"]
        self.assertEqual(domain, ipip.IPIP_HIGH)
        self.assertEqual(ipip.ipip_band(domain), "high")

    def test_bands_are_equal_thirds(self):
        self.assertEqual(ipip.ipip_band(ipip.mean([2, 2, 3])), "low")
        self.assertEqual(ipip.ipip_band(3.0), "mid")
        self.assertEqual(ipip.ipip_band(ipip.mean([4, 4, 3])), "high")
        self.assertEqual(ipip.observer_band(3), "low")
        self.assertEqual(ipip.observer_band(4), "mid")
        self.assertEqual(ipip.observer_band(5), "high")


class ParseTest(unittest.TestCase):
    def test_csv_round_trip_and_errors(self):
        inst = ipip.load_instrument()
        answers = [f"{i['id']},{'' if n == 0 else 3}" for n, i in enumerate(inst["items"])]
        rows = ["item_id,response", *answers]
        parsed = ipip.parse_responses("\n".join(rows), inst)
        self.assertIsNone(parsed[inst["items"][0]["id"]])
        self.assertEqual(parsed[inst["items"][1]["id"]], 3)
        with self.assertRaises(UsageError):
            ipip.parse_responses("\n".join(rows[:-1]), inst)
        with self.assertRaises(UsageError):
            ipip.parse_responses("\n".join([*rows[:-1], rows[-1].replace(",3", ",7")]), inst)


if __name__ == "__main__":
    unittest.main()
