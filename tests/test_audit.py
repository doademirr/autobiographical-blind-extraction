import json
import os
import re
import unittest
from unittest import mock

from abx import audit, evidence, extract, foils, invoke, prompts, store
from abx.errors import CallFailed, IntegrityError, IsolationError

from .helpers import FakeWorkspace, build


def _index() -> evidence.Index:
    eras = ({"id": "e1", "segment_ids": ["p1", "p2"]}, {"id": "e2", "segment_ids": ["p3"]})
    sentences = {"s00001": {"segment_id": "p1"}, "s00002": {"segment_id": "p2"}, "s00003": {"segment_id": "p3"}}
    return evidence.Index(eras=eras, sentences=sentences, seg_index={"p1": 1, "p2": 2, "p3": 3},
                          kept={"e1": frozenset({"s00001", "s00002"}), "e2": frozenset({"s00003"})})


class AuditValidationTest(unittest.TestCase):
    def problems(self, decided, flags):
        out = {"foils": [{"foil_id": f, "decision": "keep", "reason": "r"} for f in decided],
               "flags": [{"construct_id": c, "counter_sentence_ids": ids, "reason": "r"} for c, ids in flags]}
        return audit.validate(out, _index(), "e1", ["F1", "F2"], {"C01", "C02"})

    def test_a_complete_audit_passes(self):
        self.assertEqual(self.problems(["F2", "F1"], [("C01", ["s00001"])]), [])

    def test_every_foil_of_the_era_is_decided_exactly_once(self):
        for decided in (["F1"], ["F1", "F2", "F2"], ["F1", "F2", "F3"]):
            with self.subTest(decided=decided):
                self.assertEqual(len(self.problems(decided, [])), 1)

    def test_flags_name_known_constructs_once_and_cite_the_era(self):
        self.assertEqual(self.problems(["F1", "F2"], [("C09", ["s00001"])]), ["C09 is not in the codebook"])
        self.assertEqual(self.problems(["F1", "F2"], [("C01", ["s00001"]), ("C01", ["s00002"])]),
                         ["a construct is flagged more than once"])
        self.assertEqual(self.problems(["F1", "F2"], [("C01", ["s00003"])]),
                         ["cites 1 sentence id(s) outside the zoned era: s00003 (era:e2)"])

    def test_a_per_era_call_names_its_era_and_uses_its_own_schema(self):
        with self.assertRaises(IsolationError):
            prompts.check_allowlist("auditor", ["foils:e1", "codebook:B", "era:e2"], era_order=["e1", "e2"])
        with self.assertRaises(IsolationError):
            prompts.check_allowlist("auditor", ["schema:recode", "era:e1"], era="e1", era_order=["e1", "e2"])
        prompts.check_allowlist("auditor", ["schema:audit", "era:e1"], era="e1", era_order=["e1", "e2"])

    def test_an_auditor_may_not_receive_another_eras_foils(self):
        with self.assertRaises(IsolationError):
            prompts.check_allowlist("auditor", ["foils:e2", "codebook:B", "era:e1"], era="e1", era_order=["e1", "e2"])
        prompts.check_allowlist("auditor", ["foils:e1", "codebook:B", "era:e1"], era="e1", era_order=["e1", "e2"])


class AuditInExtractTest(unittest.TestCase):
    def setUp(self):
        self.fw = FakeWorkspace()
        self.ws = build(self.fw, until="freeze")

    def tearDown(self):
        self.fw.close()

    def auditor_prompts(self) -> list[str]:
        return [p for p in (json.loads(line)["prompt"] for line in self.fw.prompts_logged())
                if p.startswith("# abx-role: auditor")]

    def test_dropped_foils_leave_the_card_and_flagged_constructs_stay(self):
        extract.extract(self.ws)
        result = store.read_json(self.ws.path(audit.FOILS))
        card = self.ws.path("run/codebook/card.md").read_text()
        authored = [f for era in ("e1", "e2") for f in foils.load(self.ws, era)]
        dropped = {(d["era"], d["id"]) for d in result["dropped"]}
        self.assertEqual(len(dropped), 1)
        for f in authored:
            era = next(iter(f["expected"]))
            self.assertEqual(f["item_id"] in card, (era, f["id"]) not in dropped)
        book = store.read_json(self.ws.path("run/codebook/codebook.json"))
        self.assertTrue(all(c["item_id"] in card for c in book["constructs"]))
        self.assertEqual(sorted(re.findall(r"^- (K[0-9a-f]{6}):", card, re.M)), re.findall(r"^- (K[0-9a-f]{6}):", card,
                                                                                             re.M))
        flags = [f for era in ("e1", "e2") for f in store.read_json(self.ws.path(f"run/audit/{era}.json"))["flags"]]
        self.assertTrue(flags)
        frozen_b = next(e for e in store.verify_manifest(self.ws) if e["gen"] == "B")["artifacts"]
        self.assertLessEqual({audit.FOILS, "run/codebook/codebook.md", "run/audit/e1.json", "run/audit/e2.json",
                              "run/calls/extract/auditor/codex-r0-e1.json"}, set(frozen_b))

    def test_recode_must_cover_the_kept_foils(self):
        extract.extract(self.ws)
        kept = store.read_json(self.ws.path(audit.FOILS))["kept"]
        rec = store.read_json(self.ws.path("run/recode/claude-r1-e1.json"))
        self.assertLessEqual({f["item_id"] for f in kept}, {v["item_id"] for v in rec["verdicts"]})

    def test_an_interrupted_audit_resumes_to_the_same_foils_and_card(self):
        clean_fw = FakeWorkspace()
        try:
            clean = build(clean_fw)
            want = {rel: clean.path(rel).read_bytes() for rel in (audit.FOILS, "run/codebook/card.md")}
        finally:
            clean_fw.close()
        real, audits = invoke.call, []

        def second_audit_fails(*args, **kwargs):
            if args[2].role == "auditor":
                audits.append(args[2].era)
                if len(audits) == 2:
                    raise CallFailed("interrupted")
            return real(*args, **kwargs)

        with mock.patch.object(invoke, "call", side_effect=second_audit_fails), self.assertRaises(CallFailed):
            extract.extract(self.ws)
        first = self.ws.path("run/calls/extract/auditor/codex-r0-e1.json")
        before = first.read_bytes()
        extract.extract(self.ws)
        self.assertEqual(first.read_bytes(), before)
        self.assertEqual({rel: self.ws.path(rel).read_bytes() for rel in want}, want)

    def test_an_edited_foil_view_stops_extract_before_any_auditor_call(self):
        view = self.ws.path("prereg/foils/e1.md")
        view.write_text(view.read_text() + "- F9 (clear, expected absent in this era): planted.\n")
        with self.assertRaises(IntegrityError):
            extract.extract(self.ws)
        self.assertEqual(self.auditor_prompts(), [])

    def test_the_auditor_sees_uncited_counter_evidence_and_flags_on_it(self):
        """Acceptance: an era with an uncited episode contradicting a construct. The planted sentence sits in a
        middle paragraph that neither discovery nor the foil author cites; the fake auditor flags only on seeing it."""
        substrate = self.ws.path("prepare/substrate/e1.md").read_text()
        middle = list(re.finditer(r"^\[(s\d{5})\] (.{40})", substrate, re.M))
        sid, phrase = middle[len(middle) // 2].groups()
        with mock.patch.dict(os.environ, {"ABX_FAKE_PLANTED": phrase}):
            extract.extract(self.ws)
        cited = {s for p in self.ws.root.glob("run/discovery/*-r*-*.json")
                 for s in evidence.cited(store.read_json(p), ("sentence_ids",))}
        cited |= {s for era in ("e1", "e2") for s in evidence.cited(foils.load(self.ws, era),
                                                                     ("sentence_ids", "counter_sentence_ids"))}
        self.assertNotIn(sid, cited)
        e1 = [p for p in self.auditor_prompts() if f"[{sid}] {phrase}" in p]
        self.assertEqual(len(e1), 1)
        flags = store.read_json(self.ws.path("run/audit/e1.json"))["flags"]
        self.assertEqual([f["counter_sentence_ids"] for f in flags], [[sid]])
        self.assertEqual(store.read_json(self.ws.path("run/audit/e2.json"))["flags"], [])


if __name__ == "__main__":
    unittest.main()
