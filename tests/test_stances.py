import json
import os
import unittest
from unittest import mock

from abx import agreement, extract, store
from abx.errors import CallFailed, IntegrityError

from .helpers import FakeWorkspace, build

FACETS = ["A1", "C2", "N3"]
CITED = {"A1": frozenset({"s00001"}), "C2": frozenset({"s00002"}), "N3": frozenset()}


def scores(**given) -> dict:
    """{facet: (score, citations)} for the given facets, insufficient for the rest."""
    return {"scores": [{"facet": f, "score": given.get(f, (None, []))[0],
                        "cited_sentence_ids": given.get(f, (None, []))[1]} for f in FACETS]}


def ratings(strict: dict, lenient: dict) -> extract.Ratings:
    """{(lineage, run): {facet: score}} per stance as named ratings."""
    def keyed(rows):
        return {extract.RaterKey(lin, run, None): dict(by_facet) for (lin, run), by_facet in rows.items()}
    return extract.Ratings({}, keyed(strict), keyed(lenient))


class ScoreProblemsTest(unittest.TestCase):
    def test_lenient_needs_a_citation_from_the_raters_ledgers(self):
        self.assertEqual(extract.score_problems(scores(N3=(5, ["s00001"])), FACETS, CITED, "lenient"), [])
        self.assertTrue(extract.score_problems(scores(N3=(5, [])), FACETS, CITED, "lenient"))
        self.assertTrue(extract.score_problems(scores(A1=(5, ["s09999"])), FACETS, CITED, "lenient"))

    def test_strict_keeps_each_score_on_its_own_facets_evidence(self):
        self.assertEqual(extract.score_problems(scores(A1=(5, ["s00001"])), FACETS, CITED, "strict"), [])
        self.assertTrue(extract.score_problems(scores(A1=(5, ["s00002"])), FACETS, CITED, "strict"))
        self.assertTrue(extract.score_problems(scores(N3=(5, ["s00001"])), FACETS, CITED, "strict"))

    def test_every_facet_once(self):
        out = scores()
        out["scores"].pop()
        self.assertTrue(extract.score_problems(out, FACETS, CITED, "lenient"))


class SensitivityTest(unittest.TestCase):
    def test_hand_fixture(self):
        # Collapses (rounded median of three runs, halves up):
        # strict  claude A1 5, C2 3, N3 -     codex A1 4, C2 3, N3 -
        # lenient claude A1 6, C2 3, N3 4     codex A1 4, C2 3, N3 5
        strict = {("claude", r): {"A1": a, "C2": 3, "N3": None} for r, a in ((1, 5), (2, 5), (3, 6))}
        strict |= {("codex", r): {"A1": 4, "C2": c, "N3": None} for r, c in ((1, 3), (2, 2), (3, 3))}
        lenient = {("claude", r): {"A1": a, "C2": 3, "N3": 4} for r, a in ((1, 6), (2, 6), (3, 5))}
        lenient |= {("codex", r): {"A1": 4, "C2": 3, "N3": n} for r, n in ((1, 5), (2, 5), (3, 4))}
        arm, s = extract.stance_sensitivity(ratings(strict, lenient), FACETS)
        self.assertEqual(arm.collapsed, {"claude": {"A1": 6, "C2": 3, "N3": 4}, "codex": {"A1": 4, "C2": 3, "N3": 5}})
        matrix = {"strict": {("claude", "A1"): 5, ("claude", "C2"): 3, ("claude", "N3"): None,
                             ("codex", "A1"): 4, ("codex", "C2"): 3, ("codex", "N3"): None},
                  "lenient": {("claude", "A1"): 6, ("claude", "C2"): 3, ("claude", "N3"): 4,
                              ("codex", "A1"): 4, ("codex", "C2"): 3, ("codex", "N3"): 5}}
        self.assertEqual(s["alpha"], agreement.alpha(matrix, "ordinal")[0])
        self.assertEqual((s["units"], s["paired"]), (6, 4))
        self.assertEqual(s["equal_rate"], 3 / 4)
        self.assertEqual(s["mean_shift"], 1 / 4)
        self.assertEqual(s["reason"], "")

    def test_half_up_and_fewer_than_two_runs(self):
        strict = {("claude", 1): {"A1": 4, "C2": 2, "N3": None}, ("claude", 2): {"A1": 5, "C2": None, "N3": None},
                  ("codex", 1): {"A1": 4, "C2": 2, "N3": None}, ("codex", 2): {"A1": 4, "C2": 2, "N3": None}}
        lenient = {k: {"A1": 4, "C2": 2, "N3": None} for k in strict}
        _, s = extract.stance_sensitivity(ratings(strict, lenient), FACETS)
        # claude A1 strict median 4.5 rounds up to 5; claude C2 strict has one valid run, so it is missing.
        self.assertEqual(s["paired"], 3)
        self.assertEqual(s["mean_shift"], -1 / 3)

    def test_nothing_paired_and_no_variation(self):
        none = {(lin, r): {"A1": None, "C2": None, "N3": None} for lin in ("claude", "codex") for r in (1, 2)}
        some = {(lin, r): {"A1": 4, "C2": 4, "N3": 4} for lin in ("claude", "codex") for r in (1, 2)}
        _, s = extract.stance_sensitivity(ratings(none, some), FACETS)
        self.assertEqual((s["alpha"], s["reason"], s["paired"], s["equal_rate"], s["mean_shift"]),
                         (None, "no_pairable_unit", 0, None, None))
        _, s = extract.stance_sensitivity(ratings(some, some), FACETS)
        self.assertEqual((s["alpha"], s["reason"], s["equal_rate"], s["mean_shift"]), (None, "no_variation", 1.0, 0.0))


class PipelineTest(unittest.TestCase):
    def test_lenient_agreement_alone_triggers_no_audit(self):
        fw = FakeWorkspace()
        try:
            with mock.patch.dict(os.environ, {"ABX_FAKE_LENIENT_SAME": "1", "ABX_FAKE_STRICT_MIRROR": "1"}):
                ws = build(fw)
            agree = store.read_json(ws.path("run/agreement.json"))
            self.assertGreaterEqual(agree["deductive_lenient"]["alpha"], agreement.INTEGRITY_TRIGGER)
            self.assertLess(agree["deductive"]["alpha"], agreement.INTEGRITY_TRIGGER)
            self.assertLess(agree["inductive"]["alpha"], agreement.INTEGRITY_TRIGGER)
            self.assertNotIn("integrity_audit", agree)
            self.assertNotIn("integrity_audit_due", agree["deductive_lenient"])
        finally:
            fw.close()

    def test_frozen_inputs_stances_and_records(self):
        fw = FakeWorkspace()
        try:
            ws = build(fw)
            entries = {e["gen"]: e["artifacts"] for e in store.verify_manifest(ws)}
            self.assertIn("prereg/prompts/deductive_scorer_lenient.md", entries["A"])
            lenient = sorted(ws.rel(p) for p in ws.root.glob("run/deductive/lenient-*.json"))
            records = sorted(ws.rel(p) for p in ws.root.glob("run/calls/extract/deductive_scorer_lenient/*.json"))
            self.assertEqual((len(lenient), len(records)), (6, 6))
            self.assertTrue(set(lenient) | set(records) <= set(entries["C"]))
            for path in lenient:
                rec = store.read_json(ws.path(path))
                self.assertEqual(rec["stance"], "lenient")
                inputs = store.read_json(ws.path(records[lenient.index(path)]))["input_artifacts"]
                self.assertEqual(sorted(i for i in inputs if not i.startswith(("template:", "schema:"))),
                                 sorted([f"ledgers:{rec['lineage']}:{rec['run']}", "facets:all"]))
            strict = store.read_json(next(ws.root.glob("run/deductive/scores-*.json")))
            self.assertEqual(strict["stance"], "strict")
            relabelled = {**strict, "stance": "lenient"}
            path = next(ws.root.glob("run/deductive/scores-*.json"))
            path.write_text(json.dumps(relabelled))
            with self.assertRaises(IntegrityError):
                extract.load_ratings(ws)
        finally:
            fw.close()

    def test_resume_between_the_strict_and_lenient_scorers_matches_a_clean_run(self):
        clean_fw = FakeWorkspace()
        try:
            clean = store.read_json(build(clean_fw).path("run/agreement.json"))
        finally:
            clean_fw.close()
        fw = FakeWorkspace()
        try:
            ws = build(fw, until="freeze")
            with mock.patch.dict(os.environ, {"ABX_FAKE_FAIL_ROLE": "deductive_scorer_lenient"}), \
                    self.assertRaises(CallFailed):
                extract.extract(ws)
            strict_records = sorted(ws.root.glob("run/calls/extract/deductive_scorer/*.json"))
            self.assertEqual(len(strict_records), 1)
            self.assertEqual(list(ws.root.glob("run/deductive/lenient-*.json")), [])
            before = strict_records[0].read_bytes()
            extract.extract(ws)
            self.assertEqual(strict_records[0].read_bytes(), before)
            resumed = store.read_json(ws.path("run/agreement.json"))
            for key in ("deductive", "deductive_lenient", "stances"):
                self.assertEqual(resumed[key], clean[key], key)
        finally:
            fw.close()


if __name__ == "__main__":
    unittest.main()
