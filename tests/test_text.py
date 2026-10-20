import itertools
import json
import unittest

from abx import schema, store, text
from abx.errors import UsageError

from . import REPO

FIXTURE = REPO / "fixtures" / "franklin"


def _load():
    original = (FIXTURE / "autobiography.txt").read_text(encoding="utf-8")
    names = store.read_json(FIXTURE / "redactions.json")["names"]
    redacted, spans = text.redact(original, names)
    segs = text.segment(redacted)
    return original, names, redacted, spans, segs, text.sentences(redacted, segs)


class RedactionTest(unittest.TestCase):
    def test_whole_word_and_longest_first(self):
        out, spans = text.redact("Ann Lee met Lee, not Leeds.", {"Lee": "L.", "Ann Lee": "Ann L."})
        self.assertEqual(out, "Ann L. met L., not Leeds.")
        self.assertEqual(len(spans), 2)

    def test_offset_map_round_trips_on_fixture(self):
        original, names, redacted, spans, _, _ = _load()
        self.assertTrue(spans)
        for s in spans:
            self.assertIn(original[s["orig_start"]:s["orig_end"]], names)
            self.assertEqual(redacted[s["red_start"]:s["red_end"]],
                             names[original[s["orig_start"]:s["orig_end"]]])
        inside = {i for s in spans for i in range(s["red_start"], s["red_end"])}
        for pos in range(0, len(redacted), 97):
            if pos not in inside:
                self.assertEqual(redacted[pos], original[text.to_original(pos, spans)])
        for name in names:
            self.assertNotRegex(redacted, rf"(?<!\w){name}(?!\w)")


class SegmentationTest(unittest.TestCase):
    def test_sentences_partition_each_segment(self):
        _, _, redacted, _, segs, sents = _load()
        self.assertEqual(len(segs), 76)
        for seg in segs:
            mine = [s for s in sents if s.segment_id == seg.id]
            self.assertTrue(mine)
            self.assertEqual(mine[0].start, seg.start)
            self.assertEqual(mine[-1].end, seg.end)
            for a, b in itertools.pairwise(mine):
                self.assertTrue(redacted[a.end:b.start].isspace())

    def test_abbreviations_do_not_split(self):
        t = "He met Mr. Bradford at St. Paul's. Then he left."
        segs = text.segment(t)
        got = [t[s.start:s.end] for s in text.sentences(t, segs)]
        self.assertEqual(got, ["He met Mr. Bradford at St. Paul's.", "Then he left."])

    def test_closing_quote_stays_with_sentence(self):
        t = 'He said, "Go." She went.'
        got = [t[s.start:s.end] for s in text.sentences(t, text.segment(t))]
        self.assertEqual(got, ['He said, "Go."', "She went."])


class EraTest(unittest.TestCase):
    def test_fixture_eras_cover_all_segments(self):
        _, _, _, _, segs, _ = _load()
        text.validate_eras(store.read_json(FIXTURE / "eras.json")["eras"], segs)

    def test_gap_or_reorder_is_refused(self):
        segs = text.segment("a\n\nb\n\nc")
        base = {"label": "x", "date_range": "y"}
        with self.assertRaises(UsageError):
            text.validate_eras([{**base, "id": "e1", "segment_ids": ["p0001", "p0003"]}], segs)
        with self.assertRaises(UsageError):
            text.validate_eras([{**base, "id": "e1", "segment_ids": ["p0002", "p0001", "p0003"]}], segs)


class ZonedRenderingTest(unittest.TestCase):
    def test_kept_lines_are_byte_exact_and_removed_runs_collapse(self):
        _, _, redacted, _, segs, sents = _load()
        era_ids = [s.id for s in segs[:3]]
        era_sents = [s for s in sents if s.segment_id in era_ids]
        kept = {s.id for i, s in enumerate(era_sents) if i % 3 != 1}
        rendered = text.render_zoned(redacted, era_ids, era_sents, kept)
        by_id = {s.id: s for s in era_sents}
        for line in rendered.splitlines():
            if line.startswith("[s"):
                sid, body = line[1:7], line[9:]
                self.assertEqual(body, redacted[by_id[sid].start:by_id[sid].end])
        self.assertNotIn(f"{text.REMOVED_MARK}\n{text.REMOVED_MARK}", rendered)
        self.assertEqual(sum(1 for line in rendered.splitlines() if line.startswith("[s")), len(kept))


class ZoningChunkTest(unittest.TestCase):
    def sents(self, sizes):
        """Segments p1, p2, … with the given sentence counts."""
        return [text.Sentence(f"s{seg}{i:03d}", f"p{seg}", 0, 0) for seg, n in enumerate(sizes, start=1)
                for i in range(n)]

    def test_chunks_break_between_segments_and_keep_order(self):
        sents = self.sents([4, 3, 5, 2])
        chunks = text.zoning_chunks(sents, limit=7)
        self.assertEqual([[s.segment_id for s in c] for c in chunks],
                         [["p1"] * 4 + ["p2"] * 3, ["p3"] * 5 + ["p4"] * 2])
        self.assertEqual([s for c in chunks for s in c], sents)

    def test_a_segment_over_the_limit_splits_at_sentence_boundaries(self):
        sents = self.sents([2, 9, 1])
        chunks = text.zoning_chunks(sents, limit=4)
        self.assertTrue(all(len(c) <= 4 for c in chunks))
        self.assertEqual([len(c) for c in chunks], [2, 4, 4, 2])  # p3 joins the tail of split p2
        self.assertEqual([s for c in chunks for s in c], sents)


class ZonerSchemaTest(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((REPO / "schemas" / "zoner.json").read_text())

    def test_ids_and_labels_only(self):
        ok = {"labels": [{"sentence_id": "s00001", "label": "keep"}]}
        self.assertEqual(schema.errors(ok, self.schema), [])

    def test_any_text_field_is_rejected(self):
        bad = {"labels": [{"sentence_id": "s00001", "label": "keep", "text": "rewritten"}]}
        self.assertTrue(schema.errors(bad, self.schema))
        self.assertTrue(schema.errors({"labels": [], "summary": "x"}, self.schema))


if __name__ == "__main__":
    unittest.main()
