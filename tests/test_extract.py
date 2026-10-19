import json
import os
import unittest
from unittest import mock

from abx import extract, lifecycle, store
from abx.errors import CallFailed, IntegrityError, IsolationError

from .helpers import FakeWorkspace, build


class RecurrenceBarTest(unittest.TestCase):
    def bar(self, v):
        return extract.apply_bar(v, {"s1": 1, "s2": 2, "s3": 3, "s9": 9}.__getitem__)

    def test_one_long_episode_across_adjacent_segments_is_insufficient(self):
        v = {"verdict": "present", "occurrences": [{"sentence_ids": ["s1"]}, {"sentence_ids": ["s2"]}],
             "counter_sentence_ids": []}
        self.assertEqual(self.bar(v)[0], "insufficient")

    def test_two_separate_episodes_qualify(self):
        v = {"verdict": "present", "occurrences": [{"sentence_ids": ["s1"]}, {"sentence_ids": ["s9"]}],
             "counter_sentence_ids": []}
        self.assertEqual(self.bar(v), ("present", None))
        v["occurrences"][0]["sentence_ids"] = ["s1", "s9"]
        self.assertEqual(self.bar(v)[0], "insufficient")

    def test_absent_needs_a_counter_sentence(self):
        self.assertEqual(self.bar({"verdict": "absent", "occurrences": [], "counter_sentence_ids": []})[0],
                         "insufficient")
        self.assertEqual(self.bar({"verdict": "absent", "occurrences": [], "counter_sentence_ids": ["s3"]})[0],
                         "absent")


class CodebookValidatorTest(unittest.TestCase):
    def book(self, constructs, appendix=()):
        return {"constructs": [{"id": f"C{i:02d}", "name": n, "definition": "d" * 10, "sufficiency_rule": "r" * 10,
                                "trace": t} for i, (n, t) in enumerate(constructs, 1)], "appendix": list(appendix)}

    def test_clean_book_passes(self):
        self.assertEqual(extract.validate_codebook(self.book([("Thrift", ["c001"]), ("Wit", ["c002"])]),
                                                   {"c001", "c002"}), [])

    def test_compound_names_and_unplaced_candidates_fail(self):
        for name in ("Thrift / wit", "Thrift & wit", "Thrift; wit", "Thrift, then wit", "Thrift vs wit"):
            with self.subTest(name=name):
                problems = extract.validate_codebook(self.book([(name, ["c001"])]), {"c001", "c002"})
                self.assertTrue(any("not atomic" in p for p in problems))
                self.assertTrue(any("c002" in p for p in problems))

    def test_one_trait_with_two_objects_is_atomic(self):
        for name in ("Seeks and accepts advice from strangers", "Satirical, lampooning bent",
                     "Longing for escape or the sea"):
            with self.subTest(name=name):
                self.assertEqual(extract.validate_codebook(self.book([(name, ["c001"])]), {"c001"}), [])

    def test_split_needs_two_traces_and_excluded_none(self):
        ok = self.book([("Thrift", ["c001"]), ("Wit", ["c001"])],
                       [{"candidate_ref": "c001", "disposition": "split", "reason": "two claims"},
                        {"candidate_ref": "c002", "disposition": "excluded", "reason": "uncited"}])
        self.assertEqual(extract.validate_codebook(ok, {"c001", "c002"}), [])
        bad = self.book([("Thrift", ["c001"]), ("Wit", ["c001"])])
        self.assertTrue(extract.validate_codebook(bad, {"c001"}))

    def test_an_empty_codebook_is_a_valid_outcome(self):
        empty = {"constructs": [], "appendix": [{"candidate_ref": "c001", "disposition": "excluded", "reason": "x"}]}
        self.assertEqual(extract.validate_codebook(empty, {"c001"}), [])
        self.assertEqual(extract.validate_codebook({"constructs": [], "appendix": []}, set()), [])
        from abx import agreement
        self.assertEqual(agreement.arm({}, [], "nominal").reason, "no_units")

    def test_a_construct_must_trace_a_candidate(self):
        book = self.book([("Thrift", ["c001"]), ("Invented", [])])
        self.assertTrue(any("traces no candidate" in p for p in extract.validate_codebook(book, {"c001"})))

    def test_split_within_one_construct_is_not_a_split(self):
        one = self.book([("Thrift", ["c001", "c001"])],
                        [{"candidate_ref": "c001", "disposition": "split", "reason": "two claims"}])
        problems = extract.validate_codebook(one, {"c001"})
        self.assertTrue(any("repeats" in p for p in problems))
        self.assertTrue(any("not placed" in p for p in problems))


class ExtractPipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fw = FakeWorkspace()
        cls.ws = build(cls.fw)
        cls.result = store.read_json(cls.ws.path("run/agreement.json"))

    @classmethod
    def tearDownClass(cls):
        cls.fw.close()

    def logged(self):
        return [json.loads(line) for line in self.fw.prompts_logged()]

    def test_generations_and_statuses(self):
        self.assertEqual([e["gen"] for e in store.verify_manifest(self.ws)], ["A", "B", "C"])
        statuses = {s for per_era in self.result["construct_status"].values() for s in per_era.values()}
        self.assertTrue({"supported", "contested", "one-lineage"} <= statuses, statuses)
        self.assertIsNotNone(self.result["inductive"]["alpha"])
        self.assertIsNotNone(self.result["deductive"]["alpha"])
        self.assertGreater(self.result["downgrades"], 0)
        if self.result["deductive"]["integrity_audit_due"]:
            self.assertEqual(set(self.result["integrity_audit"]), {"requalify", "events", "allowlist", "manifest"})
        book = store.read_json(self.ws.path("run/codebook/codebook.json"))
        lineages = {tuple(c["lineages"]) for c in book["constructs"]}
        self.assertEqual(lineages, {("claude",), ("codex",), ("claude", "codex")})

    def test_discovery_is_future_blind(self):
        e2_ids = set(store.read_json(self.ws.path("prepare/zoning/e2.json")))
        for rec_path in self.ws.root.glob("run/calls/extract/discovery/*-e1.json"):
            rec = store.read_json(rec_path)
            self.assertEqual(set(rec["input_artifacts"]), {"template:discovery", "schema:discovery", "era:e1"})
        for entry in self.logged():
            if "abx-role: discovery" in entry["prompt"] and "Era: Boston" in entry["prompt"]:
                self.assertFalse(any(f"[{sid}]" in entry["prompt"] for sid in e2_ids))
        for rec_path in self.ws.root.glob("run/calls/extract/discovery/*-e2.json"):
            rec = store.read_json(rec_path)
            hyp = [a for a in rec["input_artifacts"] if a.startswith("hypotheses:")]
            self.assertEqual(hyp, [f"hypotheses:{rec['lineage']}:{rec['run']}:e1"])

    def test_deductive_calls_carry_no_inductive_artifact(self):
        for rec_path in self.ws.root.glob("run/calls/extract/deductive_*/*.json"):
            kinds = {a.split(":")[0] for a in store.read_json(rec_path)["input_artifacts"]}
            self.assertLessEqual(kinds, {"template", "schema", "era", "ledgers", "facets"})

    def test_no_sealed_content_in_any_prompt(self):
        sealed = [line.split(":", 1)[1].strip() for line in
                  self.ws.path("sealed/self-prediction.md").read_text().splitlines() if line.startswith("P")]
        for entry in self.logged():
            for s in sealed:
                self.assertNotIn(s, entry["prompt"])
            self.assertNotIn("i001,", entry["prompt"])

    def test_call_counts(self):
        roles = [e["prompt"].splitlines()[0] for e in self.logged()]
        self.assertEqual(roles.count("# abx-role: discovery"), 12)
        self.assertEqual(roles.count("# abx-role: recode"), 12)
        self.assertEqual(roles.count("# abx-role: deductive_ledger"), 12)
        self.assertEqual(roles.count("# abx-role: deductive_scorer"), 6)
        self.assertEqual(roles.count("# abx-role: codebook_author"), 1)


class AuditEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.fw = FakeWorkspace()
        self.ws = build(self.fw)

    def tearDown(self):
        self.fw.close()

    def test_integrity_audit_reads_call_record_events(self):
        c = extract._context(self.ws)
        clean = extract.integrity_audit(c)
        self.assertTrue(all(check["ok"] for check in clean.values()), clean)
        path = next(iter(sorted(self.ws.root.glob("run/calls/extract/recode/*.json"))))
        rec = store.read_json(path)
        rec["events"].append({"type": "item.completed", "detail": "command_execution", "tools": [], "mcp_servers": [],
                              "registry_present": True})
        store.write_json(path, rec)
        tampered = extract.integrity_audit(c)
        self.assertFalse(tampered["events"]["ok"])
        self.assertFalse(tampered["manifest"]["ok"])
        self.assertTrue(tampered["allowlist"]["ok"])


class IntegrityTest(unittest.TestCase):
    def setUp(self):
        self.fw = FakeWorkspace()
        self.ws = build(self.fw, until="freeze")

    def tearDown(self):
        self.fw.close()

    def test_frozen_prompt_edit_exits_4_before_any_call(self):
        before = len(self.fw.prompts_logged())
        path = self.ws.path("prereg/prompts/recode.md")
        path.write_text(path.read_text() + "\nBe generous.\n")
        with self.assertRaises(IntegrityError) as cm:
            extract.extract(self.ws)
        self.assertEqual(cm.exception.exit_code, 4)
        self.assertIn("recode.md", str(cm.exception))
        self.assertEqual(len(self.fw.prompts_logged()), before)

    def test_sealed_change_exits_4(self):
        path = self.ws.path("sealed/self-prediction.md")
        path.write_text(path.read_text() + "P9: an afterthought.\n")
        with self.assertRaises(IntegrityError):
            extract.extract(self.ws)
        with self.assertRaises(IntegrityError):
            lifecycle.verify_sealed(self.ws)

    def test_scorer_citing_evidence_outside_its_ledgers_fails_the_call(self):
        with mock.patch.dict(os.environ, {"ABX_FAKE_STRAY_CITATION": "1"}), self.assertRaises(CallFailed) as cm:
            extract.extract(self.ws)
        self.assertIn("deductive_scorer", str(cm.exception))

    def test_scorer_may_not_borrow_another_facets_evidence(self):
        with mock.patch.dict(os.environ, {"ABX_FAKE_CROSS_FACET": "1"}), self.assertRaises(CallFailed):
            extract.extract(self.ws)

    def test_sealed_prediction_cannot_reach_any_call_before_generation_c(self):
        from abx import invoke

        req = invoke.CallRequest(stage="unmask", role="crosswalk", lineage="claude", run=None, era=None,
                                 generation="D", slots={"constructs": "constructs:all",
                                                        "predictions": "self_prediction:sealed"})
        with self.assertRaises(IsolationError):
            invoke.call(self.ws, self.fw.config, req)


class ResumeTest(unittest.TestCase):
    def test_interrupted_extract_resumes_without_repeats_and_matches_clean_run(self):
        clean_fw = FakeWorkspace()
        try:
            clean = store.read_json(build(clean_fw).path("run/agreement.json"))
        finally:
            clean_fw.close()
        fw = FakeWorkspace()
        try:
            ws = build(fw, until="freeze")

            def model_calls():
                return [e for e in map(json.loads, fw.prompts_logged()) if "abx-role: probe" not in e["prompt"]]

            calls_before = len(model_calls())
            state = fw.log / "state-claude.json"
            done = json.loads(state.read_text())["calls"]
            with mock.patch.dict(os.environ, {"ABX_FAKE_FAIL_AFTER": str(done + 4)}), self.assertRaises(CallFailed):
                extract.extract(ws)
            failed_attempts = len(model_calls()) - calls_before
            records = set(map(str, ws.root.glob("run/calls/extract/**/*.json")))
            extract.extract(ws)
            resumed = store.read_json(ws.path("run/agreement.json"))
            total = len(model_calls()) - calls_before
            self.assertEqual(failed_attempts, len(records) + 1)
            self.assertEqual(total, failed_attempts + 43 - len(records))
            for key in ("inductive", "deductive", "construct_status"):
                self.assertEqual(resumed[key], clean[key])
        finally:
            fw.close()


if __name__ == "__main__":
    unittest.main()
