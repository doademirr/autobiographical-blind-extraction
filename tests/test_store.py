import tempfile
import unittest
from pathlib import Path

from abx import store
from abx.errors import IntegrityError, UsageError


class StrictJsonTest(unittest.TestCase):
    def test_rejects_duplicate_keys_and_nan(self):
        with self.assertRaises(ValueError):
            store.loads_strict('{"a": 1, "a": 2}')
        with self.assertRaises(ValueError):
            store.loads_strict('{"a": NaN}')

    def test_read_json_reports_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text("{bad")
            with self.assertRaises(UsageError) as cm:
                store.read_json(p)
            self.assertIn("x.json", str(cm.exception))

    def test_atomic_write_leaves_no_temp_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "x.json"
            store.write_json(p, {"k": [1, 2]})
            self.assertEqual(store.read_json(p), {"k": [1, 2]})
            self.assertEqual([f.name for f in p.parent.iterdir()], ["x.json"])


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = store.Workspace(Path(self._tmp.name))
        for rel, text in {"prereg/a.md": "alpha", "prereg/b.json": "{}", "run/c.json": "[]"}.items():
            self.ws.path(rel).parent.mkdir(parents=True, exist_ok=True)
            self.ws.path(rel).write_text(text)

    def tearDown(self):
        self._tmp.cleanup()

    def test_chain_verifies(self):
        a = store.append_generation(self.ws, "A", ["prereg/a.md", "prereg/b.json"])
        b = store.append_generation(self.ws, "B", ["run/c.json"])
        self.assertEqual(b["prev"], a["hash"])
        self.assertEqual([e["gen"] for e in store.verify_manifest(self.ws)], ["A", "B"])

    def test_edit_to_frozen_file_is_integrity_failure(self):
        store.append_generation(self.ws, "A", ["prereg/a.md"])
        self.ws.path("prereg/a.md").write_text("alpha edited")
        with self.assertRaises(IntegrityError) as cm:
            store.verify_manifest(self.ws)
        self.assertEqual(cm.exception.exit_code, 4)
        self.assertIn("prereg/a.md", str(cm.exception))

    def test_tampered_entry_breaks_chain(self):
        store.append_generation(self.ws, "A", ["prereg/a.md"])
        store.append_generation(self.ws, "B", ["run/c.json"])
        path = self.ws.path(store.MANIFEST)
        path.write_text(path.read_text().replace('"gen":"A"', '"gen":"Z"'))
        with self.assertRaises(IntegrityError):
            store.verify_manifest(self.ws)

    def test_generation_cannot_be_refrozen(self):
        store.append_generation(self.ws, "A", ["prereg/a.md"])
        with self.assertRaises(IntegrityError):
            store.append_generation(self.ws, "A", ["prereg/b.json"])


if __name__ == "__main__":
    unittest.main()
