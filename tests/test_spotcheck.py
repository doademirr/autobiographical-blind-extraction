import json
import os
import unittest
from unittest import mock

from abx import foils, freeze, prepare, seal, spotcheck, status, store
from abx import text as abx_text
from abx.errors import GateFired, UsageError

from .helpers import FIXTURE, FakeWorkspace, approve_spot_check, build


def corpus(labels_by_era: dict[str, list[str]]):
    """Eras of one-sentence paragraphs with the given zoner labels."""
    paragraphs, eras, labels = [], [], {}
    for era, era_labels in labels_by_era.items():
        start = len(paragraphs)
        paragraphs += [f"Sentence {era} {k}." for k in range(len(era_labels))]
        eras.append({"id": era, "segment_ids": [f"p{n + 1:04d}" for n in range(start, len(paragraphs))]})
    body = "\n\n".join(paragraphs)
    sents = abx_text.sentences(body, abx_text.segment(body))
    flat = [lab for era_labels in labels_by_era.values() for lab in era_labels]
    labels = {s.id: flat[k] for k, s in enumerate(sents)}
    return eras, sents, labels, body


class SampleTest(unittest.TestCase):
    def test_sizes_allocation_order_and_text(self):
        eras, sents, labels, body = corpus({"e1": ["keep"] * 30 + ["remove"] * 10,
                                            "e2": ["keep"] * 10 + ["mixed"] * 30})
        drawn = spotcheck.sample(eras, sents, labels, body)
        self.assertEqual(len(drawn["kept"]), 20)
        self.assertEqual(len(drawn["removed"]), 20)
        self.assertEqual([sum(x["era"] == e for x in drawn["kept"]) for e in ("e1", "e2")], [15, 5])
        # One per era, then 18 split 4.5 : 13.5; the tied remainder goes to the earlier era.
        self.assertEqual([sum(x["era"] == e for x in drawn["removed"]) for e in ("e1", "e2")], [6, 14])
        order = {s.id: s.start for s in sents}
        for group in ("kept", "removed"):
            starts = [order[x["sentence_id"]] for x in drawn[group]]
            self.assertEqual(starts, sorted(starts))
        by_id = {s.id: s for s in sents}
        for x in drawn["removed"]:
            s = by_id[x["sentence_id"]]
            self.assertIn(labels[s.id], ("remove", "mixed"))
            self.assertEqual(x["text"], body[s.start:s.end])
            self.assertIs(x["wrong"], False)
        self.assertEqual(spotcheck.sample(eras, sents, labels, body), drawn)

    def test_a_small_stratum_is_shown_whole(self):
        eras, sents, labels, body = corpus({"e1": ["keep"] * 25 + ["remove"] * 3})
        drawn = spotcheck.sample(eras, sents, labels, body)
        self.assertEqual((len(drawn["kept"]), len(drawn["removed"])), (20, 3))


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.fw = FakeWorkspace()

    def tearDown(self):
        self.fw.close()

    def sealed(self):
        ws = build(self.fw, until="prepare")
        for name in ("self-prediction.md", "ipip-120.csv"):
            ws.path(f"sealed/{name}").write_text((FIXTURE / name).read_text())
        seal.seal(ws)
        return ws

    def edit(self, ws, change):
        path = ws.path(spotcheck.PATH)
        doc = store.read_json(path)
        change(doc)
        store.write_json(path, doc)

    def test_prepare_writes_it_unapproved_once_and_outside_the_receipt(self):
        ws = build(self.fw, until="prepare")
        doc = store.read_json(ws.path(spotcheck.PATH))
        self.assertFalse(doc["approved"])
        self.assertIn("mixes an event", doc["note"])
        self.assertNotIn(spotcheck.PATH, store.read_json(ws.path(prepare.RECEIPT)))
        self.edit(ws, lambda d: d.update(approved=True))
        prepare.prepare(ws)
        self.assertTrue(store.read_json(ws.path(spotcheck.PATH))["approved"])

    def test_written_also_when_calibration_fails(self):
        with mock.patch.dict(os.environ, {"ABX_FAKE_JUDGE": "claude:keep,codex:keep"}), self.assertRaises(GateFired):
            build(self.fw, until="prepare")
        self.assertTrue(store.Workspace(self.fw.ws.root.parent / "w").path(spotcheck.PATH).exists())

    def test_freeze_waits_for_approval_and_freezes_it(self):
        ws = self.sealed()
        self.assertEqual(status.status(ws)["next"], "approve_spot_check")
        calls = len(self.fw.prompts_logged())
        self.assertEqual(freeze.freeze(ws), {"status": "review", "next": "approve_spot_check"})
        self.assertEqual(store.frozen_generations(ws), set())
        self.assertEqual(len(self.fw.prompts_logged()), calls)
        self.edit(ws, lambda d: d["kept"][0].update(text="edited by the user"))
        approve_spot_check(ws)
        freeze.freeze(ws)
        self.assertIn(spotcheck.PATH, next(e for e in store.verify_manifest(ws) if e["gen"] == "A")["artifacts"])
        self.assertEqual(status.status(ws)["next"], "extract")

    def test_edited_ids_order_or_marks_are_refused(self):
        changes = {"id": lambda d: d["kept"][0].update(sentence_id="s99999"),
                   "order": lambda d: d["removed"].reverse(),
                   "mark": lambda d: d["kept"][1].update(wrong="yes"),
                   "dropped": lambda d: d["kept"].pop()}
        for name, change in changes.items():
            with self.subTest(change=name):
                ws = self.sealed()
                approve_spot_check(ws)
                self.edit(ws, change)
                with self.assertRaises(UsageError):
                    freeze.freeze(ws)
                self.assertEqual(store.frozen_generations(ws), set())
                self.fw.close()
                self.fw = FakeWorkspace()

    def test_approval_revoked_during_authoring_freezes_nothing_and_the_rerun_reuses_the_calls(self):
        ws = self.sealed()
        approve_spot_check(ws)
        real = foils.author

        def author_then_revoke(*args):
            real(*args)
            self.edit(ws, lambda d: d.update(approved=False))
        with mock.patch.object(foils, "author", side_effect=author_then_revoke), self.assertRaises(UsageError):
            freeze.freeze(ws)
        self.assertEqual(store.frozen_generations(ws), set())
        calls = len(self.fw.prompts_logged())
        approve_spot_check(ws)
        freeze.freeze(ws)
        self.assertEqual(store.frozen_generations(ws), {"A"})
        foil_calls = [p for p in map(json.loads, self.fw.prompts_logged()[calls:])
                      if p["prompt"].startswith("# abx-role: foil_author")]
        self.assertEqual(foil_calls, [])


if __name__ == "__main__":
    unittest.main()
