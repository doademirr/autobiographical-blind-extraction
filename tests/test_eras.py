import itertools
import json
import unittest
from unittest import mock

from abx import config, eras, init, prepare, sizing, store
from abx import text as abx_text
from abx.errors import UsageError

from .helpers import FIXTURE, FakeWorkspace

FULL = FIXTURE.parent / "franklin-full" / "autobiography.txt"


def segmented(paragraphs: list[str]) -> tuple[str, list[abx_text.Segment]]:
    body = "\n\n".join(paragraphs)
    return body, abx_text.segment(body)


class CandidatesTest(unittest.TestCase):
    def kinds(self, paragraphs: list[str]) -> list[str]:
        body, segs = segmented(paragraphs)
        return [b.kind for b in eras.candidates(body, segs)]

    def test_heading_shapes(self):
        for heading in ("# Early years", "### Boston", "CHAPTER IV", "Chapter 12", "Part Two", "BOOK III",
                        "section one", "THE VOYAGE HOME", "LONDON"):
            with self.subTest(heading=heading):
                self.assertEqual(self.kinds([heading]), ["heading"])

    def test_not_headings(self):
        for line in ("1. Temperance.", "We sailed at dawn.", "B. F.\"", "I ARRIVED.", "A" * 81,
                     "# Early years\nWe moved that spring."):
            with self.subTest(line=line):
                self.assertNotEqual(self.kinds([line]), ["heading"])

    def test_years_mark_dated_passages(self):
        self.assertEqual(self.kinds(["In 1723 I left Boston.", "It cost 1400 pounds.", "Page 2150 of 3000.",
                                     "Back in 2003, and in the 1500s."]),
                         ["dated", "paragraph", "paragraph", "dated"])
        body, segs = segmented(["From 1723 to 1726, then 1730."])
        self.assertEqual(eras.candidates(body, segs)[0].years, (1723, 1726, 1730))


class PartitionTest(unittest.TestCase):
    def test_sixty_equal_paragraphs_give_six_balanced_eras(self):
        words, kinds = [1000] * 60, ["paragraph"] * 60
        self.assertEqual(eras.partition(words, kinds, 40_000, 6), [0, 10, 20, 30, 40, 50])

    def test_heading_within_the_floor_beats_a_better_balanced_date(self):
        # Two eras of a 20k text: target 10k, floor 5k. The heading gives 6k/14k; the date gives 10k/10k.
        words = [1000] * 20
        kinds = ["paragraph"] * 20
        kinds[6], kinds[10] = "heading", "dated"
        self.assertEqual(eras.partition(words, kinds, 40_000, 2), [0, 6])

    def test_heading_below_the_floor_loses_to_a_date(self):
        # The heading gives 2k/18k, under the 5k floor; the date at 10k wins.
        words = [1000] * 20
        kinds = ["paragraph"] * 20
        kinds[2], kinds[10] = "heading", "dated"
        self.assertEqual(eras.partition(words, kinds, 40_000, 2), [0, 10])

    def test_dates_beat_bare_paragraph_breaks(self):
        words = [1000] * 20
        kinds = ["paragraph"] * 20
        kinds[8] = "dated"
        self.assertEqual(eras.partition(words, kinds, 40_000, 2), [0, 8])

    def test_the_cap_forces_a_paragraph_cut_when_nothing_else_fits(self):
        words = [1000] * 20
        kinds = ["paragraph"] * 20
        kinds[2] = "dated"
        starts = eras.partition(words, kinds, 12_000, 2)
        self.assertEqual(starts, [0, 10])
        self.assertTrue(all(sum(words[a:b]) <= 12_000 for a, b in zip(starts, [*starts[1:], 20], strict=True)))

    def test_a_lone_paragraph_over_the_cap_is_admissible(self):
        self.assertEqual(eras.partition([5000, 50_000, 5000], ["paragraph"] * 3, 20_000, 3), [0, 1, 2])
        self.assertIsNone(eras.partition([5000, 50_000, 5000], ["paragraph"] * 3, 20_000, 2))

    def test_ties_break_to_the_earliest_cut(self):
        self.assertEqual(eras.partition([1000, 1000, 1000], ["paragraph"] * 3, 10_000, 2), [0, 1])

    def test_deterministic(self):
        words = [700, 1300, 900, 2000, 400, 1600, 1100, 800] * 5
        kinds = ["paragraph", "dated", "paragraph", "heading"] * 10
        self.assertEqual(eras.partition(words, kinds, 9000, 5), eras.partition(words, kinds, 9000, 5))


class ProposeTest(unittest.TestCase):
    def test_two_paragraphs_cap_the_count(self):
        body, segs = segmented([" ".join(["w"] * 30_000)] * 2)
        out = eras.propose(body, segs, lambda n: 40_000).eras
        self.assertEqual([e["segment_ids"] for e in out], [["p0001"], ["p0002"]])

    def test_a_short_text_is_one_era_unless_the_cap_forces_more(self):
        body, segs = segmented([" ".join(["w"] * 3000)] * 5)
        self.assertEqual(len(eras.propose(body, segs, lambda n: 40_000).eras), 1)
        forced = eras.propose(body, segs, lambda n: 7000).eras
        self.assertEqual(len(forced), 3)
        self.assertEqual([e["basis"] for e in forced[1:]],
                         ["paragraph break: no heading or dated boundary fits the size limit"] * 2)

    def test_the_count_grows_until_the_cap_for_that_count_holds(self):
        body, segs = segmented([" ".join(["w"] * 1000)] * 60)
        seen = []

        def cap_for(n):
            seen.append(n)
            return 12_000 - 500 * n
        out = eras.propose(body, segs, cap_for).eras
        caps = 12_000 - 500 * len(out)
        self.assertGreater(len(out), 6)
        self.assertIn(len(out), seen)
        self.assertTrue(all(len(e["segment_ids"]) * 1000 <= caps for e in out))

    def test_zero_cap_proposes_the_whole_text_as_one_era_without_room(self):
        body, segs = segmented(["Some text.", "More text."])
        proposal = eras.propose(body, segs, lambda n: 0)
        self.assertFalse(proposal.room)
        self.assertEqual([e["segment_ids"] for e in proposal.eras], [["p0001", "p0002"]])

    def test_fields(self):
        paragraphs = ["In 1701 we were born.", *[" ".join(["w"] * 2500)] * 4, "CHAPTER II",
                      "In 1690, 1710, 1712, 1715, 1716, 1717, 1718, 1719, 1720, 1721 and 1790.",
                      *[" ".join(["w"] * 2500)] * 4]
        body, segs = segmented(paragraphs)
        out = eras.propose(body, segs, lambda n: 15_000).eras
        self.assertEqual([e["id"] for e in out], ["e1", "e2"])
        self.assertEqual([e["label"] for e in out], ["", ""])
        self.assertEqual([e["basis"] for e in out], ["start of text", "heading: CHAPTER II"])
        self.assertEqual([e["date_range"] for e in out], ["1701", "1710–1721"])
        abx_text.validate_eras(out, segs)


class PrepareProposalTest(unittest.TestCase):
    def setUp(self):
        self.fw = FakeWorkspace()

    def tearDown(self):
        self.fw.close()

    def workspace(self, name: str, budget: int = 200_000):
        cfg = {**self.fw.cfg, "lineages": {k: {**v, "input_budget_tokens": budget}
                                           for k, v in self.fw.cfg["lineages"].items()}}
        return init.init(self.fw.ws.root.parent / name, [FULL], [], False, config=cfg)

    def proposal(self, ws) -> dict:
        self.assertEqual(prepare.prepare(ws)["status"], "review")
        self.assertEqual(self.fw.prompts_logged(), [])
        return store.read_json(ws.path("prepare/eras.json"))

    def check(self, ws, doc: dict) -> None:
        original = ws.path("text/original.txt").read_text()
        segs = abx_text.segment(original)
        abx_text.validate_eras(doc["eras"], segs)
        sizing.check_eras(ws, config.load(ws), doc["eras"], abx_text.sentences(original, segs), original)

    def test_full_franklin_is_cut_at_dated_passages_and_fits(self):
        ws = self.workspace("full")
        doc = self.proposal(ws)
        self.assertFalse(doc["approved"])
        self.assertEqual(len(doc["eras"]), 6)
        self.assertTrue(all(e["basis"].startswith("dated passage") for e in doc["eras"][1:]), doc["eras"])
        self.assertIn("proposal from headings", doc["note"])
        self.assertNotIn("does not pass", doc["note"])
        self.check(ws, doc)
        self.assertIn("dated", ws.path("prepare/segments-preview.txt").read_text())

    def test_a_small_budget_grows_the_count_and_still_fits(self):
        ws = self.workspace("small", 50_000)
        doc = self.proposal(ws)
        self.assertGreater(len(doc["eras"]), 6)
        self.check(ws, doc)

    def test_zero_room_writes_one_unapproved_era_with_the_reason(self):
        ws = self.workspace("none", 20_000)
        doc = self.proposal(ws)
        self.assertEqual(len(doc["eras"]), 1)
        self.assertIn("leave no room", doc["note"])

    def test_retries_shrink_the_cap_then_quote_the_failure(self):
        ws = self.workspace("exhausted")
        caps = []
        real = eras.propose

        def spy(text, segs, cap_for):
            caps.append(cap_for(6))
            return real(text, segs, cap_for)
        with mock.patch.object(sizing, "check_eras", side_effect=UsageError("era e3 has too many words")) as check, \
                mock.patch.object(eras, "propose", side_effect=spy):
            doc = self.proposal(ws)
        self.assertEqual(check.call_count, prepare.PROPOSAL_RETRIES + 1)
        self.assertEqual(len(caps), prepare.PROPOSAL_RETRIES + 1)
        for before, after in itertools.pairwise(caps):
            self.assertAlmostEqual(after / before, 0.9, delta=0.01)
        self.assertIn("does not pass the size check: era e3 has too many words", doc["note"])
        self.assertFalse(doc["approved"])

    def test_an_existing_eras_file_is_never_overwritten(self):
        ws = self.workspace("kept")
        mine = {"approved": False, "eras": [{"id": "x", "label": "", "date_range": "", "segment_ids": []}]}
        store.write_json(ws.path("prepare/eras.json"), mine)
        prepare.prepare(ws)
        self.assertEqual(store.read_json(ws.path("prepare/eras.json")), mine)

    def test_basis_and_date_range_are_never_sent_and_the_label_is(self):
        ws = init.init(self.fw.ws.root.parent / "sent", [FIXTURE / "autobiography.txt"], [], False,
                       config=self.fw.cfg)
        prepare.prepare(ws)
        doc = store.read_json(FIXTURE / "eras.json")
        for era in doc["eras"]:
            era |= {"date_range": "SENTINELRANGE", "basis": "SENTINELBASIS", "label": f"Label {era['id']}"}
        store.write_json(ws.path("prepare/eras.json"), doc)
        store.write_json(ws.path("prepare/redactions.json"), store.read_json(FIXTURE / "redactions.json"))
        prepare.prepare(ws)
        sent = "\n".join(json.loads(p)["prompt"] for p in self.fw.prompts_logged())
        self.assertNotIn("SENTINELRANGE", sent)
        self.assertNotIn("SENTINELBASIS", sent)
        self.assertIn("Label e1", sent)


if __name__ == "__main__":
    unittest.main()
