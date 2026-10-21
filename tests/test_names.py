import json
import re
import unittest
from unittest import mock

from abx import config, init, invoke, names, prepare, prompts, qualify, store
from abx import text as abx_text
from abx.errors import IsolationError, UsageError
from abx.withheld import Withheld

from .helpers import FIXTURE, FakeWorkspace


def scanned(body: str) -> dict[str, names.Candidate]:
    return {c.name: c for c in names.scan(body, abx_text.sentences(body, abx_text.segment(body)))}


def unlabelled() -> dict:
    eras = store.read_json(FIXTURE / "eras.json")
    for era in eras["eras"]:
        era["label"] = ""
    return eras


class ScanTest(unittest.TestCase):
    def test_expected_candidates(self):
        body = ("We met John Smith at the fair. Later I saw Mr. Brown there. Mrs Brown came too. However it rained. "
                "Then John's coat and John’s hat got wet. I wrote to O'Connor and to Smith-Jones. "
                "We read CHAPTER notes in The Hague in March and on Sunday, praying to God. "
                "I met Anne Mary Jane Doe. Alice left early. She said: That was all.")
        found = scanned(body)
        self.assertEqual(sorted(found), sorted(["John Smith", "Brown", "John", "O'Connor", "Smith-Jones", "Hague",
                                                "Anne Mary Jane"]))
        self.assertIn("John Smith", found)
        self.assertTrue(found["Brown"].titled)
        self.assertIn("John", found)
        self.assertNotIn("John's", found)
        self.assertIn("O'Connor", found)
        self.assertIn("Smith-Jones", found)
        self.assertIn("Hague", found)
        self.assertIn("Anne Mary Jane", found)
        for absent in ("However", "CHAPTER", "I", "March", "Sunday", "God", "The Hague", "Alice", "That", "Later",
                       "Then", "Mr", "Mrs"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, found)

    def test_every_title_with_and_without_a_full_stop(self):
        for title in sorted(names.TITLES):
            for stop in ("", "."):
                with self.subTest(title=title + stop):
                    found = scanned(f"I met {title}{stop} Alice by the gate.")
                    self.assertEqual(list(found), ["Alice"])
                    self.assertTrue(found["Alice"].titled)

    def test_accented_names_are_whole_words(self):
        found = scanned("I met Dr. José. Later I saw José and Émile, then Émile again.")
        self.assertEqual(set(found), {"Émile", "José"})
        self.assertEqual((found["José"].count, found["José"].titled), (2, True))

    def test_counts_include_sentence_starts_and_are_whole_word(self):
        body = "Alice came. I saw Alice. Alice's dog barked at Alicea."
        self.assertEqual(scanned(body)["Alice"].count, 3)

    def test_first_paragraph_is_recorded(self):
        body = "Nothing here.\n\nWe met Tom Hart.\n\nTom Hart again."
        self.assertEqual(scanned(body)["Tom Hart"].first_segment, "p0002")


class PrefillTest(unittest.TestCase):
    def test_threshold_titles_and_shared_placeholders(self):
        candidates = [names.Candidate("John Smith", 3, False, "p1"), names.Candidate("Brown", 1, True, "p1"),
                      names.Candidate("Smith", 2, False, "p2"), names.Candidate("Once", 1, False, "p2"),
                      names.Candidate("John Wood", 2, False, "p3"), names.Candidate("John", 4, False, "p3"),
                      names.Candidate("Wood", 2, False, "p4")]
        self.assertEqual(names.prefill(candidates), {
            "John Smith": "Name 1", "Brown": "Name 2", "Smith": "Name 1", "John Wood": "Name 3", "John": "Name 4",
            "Wood": "Name 3"})

    def test_placeholders_never_contain_a_listed_name(self):
        candidates = [names.Candidate("Name", 2, False, "p1"), names.Candidate("Ada", 2, False, "p1")]
        self.assertEqual(names.prefill(candidates), {"Name": "Person 1", "Ada": "Person 2"})

    def test_every_stem_taken_falls_back_to_one_no_scanned_word_can_be(self):
        candidates = [names.Candidate(n, 2, False, "p1") for n in ("Name", "Person", "Someone", "Party")]
        self.assertEqual(names.prefill(candidates)["Name"], "Name0 1")

    def test_preview_lists_every_candidate(self):
        candidates = [names.Candidate("Ann Lee", 2, False, "p0001"), names.Candidate("Once", 1, False, "p0002")]
        text = names.preview(candidates, names.prefill(candidates))
        self.assertIn("Ann Lee\t2\tName 1\tp0001", text)
        self.assertIn("Once\tp0002", text)


class NameAuditTest(unittest.TestCase):
    def setUp(self):
        self.withheld = Withheld(redacted_names=["Ann", "Boston"])
        self.zoner = (prompts.SHIPPED_TEMPLATES / "zoner.md").read_text(encoding="utf-8")
        self.slots = dict.fromkeys(re.findall(r"\{\{([a-z_]+)\}\}", self.zoner), "Era text.")

    def test_whole_word_in_what_fills_the_template(self):
        def prompt(value):
            return prompts.Prompt("zoner", self.zoner, {**self.slots, "chunk": value}, {})
        with self.assertRaises(IsolationError):
            prompts.audit(prompt("we met Ann's sister"), self.withheld)
        prompts.audit(prompt("Anna came by"), self.withheld)

    def test_a_prompt_keeps_its_own_copy_of_the_values(self):
        values = {**self.slots, "chunk": "we met Ann"}
        prompt = prompts.Prompt("zoner", self.zoner, values, {})
        self.assertIn("Ann", prompt.text)
        values["chunk"] = "nobody"
        with self.assertRaises(IsolationError):
            prompts.audit(prompt, self.withheld)

    def test_shipped_template_wording_is_exempt_and_an_edited_template_is_not(self):
        self.assertIsNotNone(re.search(r"(?<!\w)Boston(?!\w)", self.zoner))
        prompts.audit(prompts.Prompt("zoner", self.zoner, self.slots, {}), self.withheld)
        with self.assertRaises(IsolationError):
            prompts.audit(prompts.Prompt("zoner", self.zoner + "\nOnce more: Boston.", self.slots, {}), self.withheld)


class PrepareScanTest(unittest.TestCase):
    def setUp(self):
        self.fw = FakeWorkspace()
        self.ws = init.init(self.fw.ws.root.parent / "w", [FIXTURE / "autobiography.txt"], [], False,
                            config=self.fw.cfg)

    def tearDown(self):
        self.fw.close()

    def test_first_run_prefills_unapproved_and_sends_nothing(self):
        self.assertEqual(prepare.prepare(self.ws)["status"], "review")
        doc = store.read_json(self.ws.path("prepare/redactions.json"))
        self.assertFalse(doc["approved"])
        self.assertIn("Collins", doc["names"])
        self.assertIn("local scan", doc["note"])
        self.assertIn("Collins", self.ws.path("prepare/names-preview.txt").read_text())
        self.assertEqual(self.fw.prompts_logged(), [])

    def test_an_existing_list_is_never_overwritten(self):
        mine = {"approved": False, "names": {"Zed": "Z."}}
        store.write_json(self.ws.path("prepare/redactions.json"), mine)
        prepare.prepare(self.ws)
        self.assertEqual(store.read_json(self.ws.path("prepare/redactions.json")), mine)

    def test_an_interruption_before_the_list_leaves_a_retry_that_writes_both(self):
        real = store.write_json

        def failing(path, doc):
            if path.name == "redactions.json":
                raise OSError("disk full")
            real(path, doc)
        with mock.patch.object(store, "write_json", side_effect=failing), self.assertRaises(OSError):
            prepare.prepare(self.ws)
        self.assertTrue(self.ws.path("prepare/names-preview.txt").exists())
        self.assertFalse(self.ws.path("prepare/redactions.json").exists())
        prepare.prepare(self.ws)
        self.assertTrue(self.ws.path("prepare/redactions.json").exists())
        self.assertTrue(self.ws.path("prepare/names-preview.txt").exists())

    def test_approving_the_prefill_redacts_it_and_zoning_passes_the_audit(self):
        prepare.prepare(self.ws)
        doc = store.read_json(self.ws.path("prepare/redactions.json"))
        self.assertTrue({"Read", "Boston"} <= set(doc["names"]))  # both are in shipped prompt wording
        store.write_json(self.ws.path("prepare/redactions.json"), {**doc, "approved": True})
        eras = store.read_json(FIXTURE / "eras.json")
        store.write_json(self.ws.path("prepare/eras.json"), eras)
        with self.assertRaises(UsageError) as cm:  # the fixture's first label names Boston
            prepare.prepare(self.ws)
        self.assertIn("label", str(cm.exception))
        self.assertEqual(self.fw.prompts_logged(), [])
        for era in eras["eras"]:
            era["label"] = ""
        store.write_json(self.ws.path("prepare/eras.json"), eras)
        self.assertEqual(prepare.prepare(self.ws)["status"], "done")
        redacted = self.ws.path("prepare/redacted.txt").read_text()
        for name in doc["names"]:
            self.assertIsNone(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", redacted), name)
        sent = [json.loads(p)["prompt"] for p in self.fw.prompts_logged()]
        self.assertTrue(any(p.startswith("# abx-role: zoner") for p in sent))

    def test_a_replacement_holding_a_listed_name_is_refused_before_any_call(self):
        prepare.prepare(self.ws)
        store.write_json(self.ws.path("prepare/redactions.json"),
                         {"approved": True, "names": {"Collins": "John C.", "John": "J."}})
        store.write_json(self.ws.path("prepare/eras.json"), store.read_json(FIXTURE / "eras.json"))
        with self.assertRaises(UsageError) as cm:
            prepare.prepare(self.ws)
        self.assertIn("entry 1", str(cm.exception))
        self.assertNotIn("Collins", str(cm.exception))
        self.assertEqual(self.fw.prompts_logged(), [])

    def test_a_name_added_to_a_staged_template_fails_the_audit(self):
        prepare.prepare(self.ws)
        doc = store.read_json(self.ws.path("prepare/redactions.json"))
        store.write_json(self.ws.path("prepare/redactions.json"), {**doc, "approved": True})
        store.write_json(self.ws.path("prepare/eras.json"), unlabelled())
        zoner = self.ws.path("prereg/prompts/zoner.md")
        zoner.write_text(zoner.read_text() + "\nRemember Boston.\n")
        with self.assertRaises(IsolationError):
            prepare.prepare(self.ws)

    def test_an_era_id_standing_in_for_an_empty_label_is_checked_too(self):
        prepare.prepare(self.ws)
        doc = store.read_json(self.ws.path("prepare/redactions.json"))
        store.write_json(self.ws.path("prepare/redactions.json"), {**doc, "approved": True})
        eras = unlabelled()
        eras["eras"][0]["id"] = "Boston"
        store.write_json(self.ws.path("prepare/eras.json"), eras)
        with self.assertRaises(UsageError):
            prepare.prepare(self.ws)
        self.assertEqual(self.fw.prompts_logged(), [])

    def test_the_probes_are_audited_before_anything_is_sent(self):
        prepare.prepare(self.ws)
        store.write_json(self.ws.path("prepare/redactions.json"), {"approved": True, "names": {"Collins": "C."}})
        schema_path = self.ws.path("prereg/schemas/probe.json")
        store.write_json(schema_path, {**store.read_json(schema_path), "description": "about Collins"})
        cfg = config.load(self.ws)
        with self.assertRaises(IsolationError):
            invoke.probe(self.ws, cfg, "claude", ())
        with self.assertRaises(IsolationError):
            qualify.qualify(self.ws, cfg)
        self.assertEqual(self.fw.prompts_logged(), [])

    def test_a_name_added_to_a_staged_schema_fails_the_audit(self):
        prepare.prepare(self.ws)
        doc = store.read_json(self.ws.path("prepare/redactions.json"))
        store.write_json(self.ws.path("prepare/redactions.json"), {**doc, "approved": True})
        store.write_json(self.ws.path("prepare/eras.json"), unlabelled())
        schema_path = self.ws.path("prereg/schemas/zoner.json")
        schema = store.read_json(schema_path)
        store.write_json(schema_path, {**schema, "description": "labels for Collins"})
        with self.assertRaises(IsolationError):
            prepare.prepare(self.ws)


if __name__ == "__main__":
    unittest.main()
