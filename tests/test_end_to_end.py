"""Offline smoke: the whole CLI, stage by stage, on the Franklin fixture with fake CLIs.

Asserts that every stage completes, the report exists and is non-vacuous, every report
figure equals its recomputation from the frozen run files, the manifest verifies, and no
sealed content reached a prompt before generation C (self-prediction only in crosswalk
prompts, IPIP answers in none).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from abx import agreement, extract, ipip, store, unmask

from . import REPO
from .helpers import FAKE_ENV, FAKES, FIXTURE

RUN = REPO / "scripts" / "run.py"


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="abx-e2e-")))
        cls.ws_path = cls.tmp / "ws"
        cls.log = cls.tmp / "fakelog"
        cls.env = {**os.environ, "PATH": f"{FAKES}{os.pathsep}{os.environ['PATH']}", "ABX_FAKE_LOG": str(cls.log),
                   "PYTHONDONTWRITEBYTECODE": "1"}
        cls.codes = {}
        cls.run_stage("init", "--text", str(FIXTURE / "autobiography.txt"), "--canary", "ABXPROFILECANARY")
        cfg_path = cls.ws_path / "config.json"
        cfg = json.loads(cfg_path.read_text())
        auth = cls.tmp / "auth.json"
        auth.write_text("{}")
        cfg["lineages"]["codex"].update(sandbox_exec=str(FAKES / "sandbox-exec"), auth_file=str(auth),
                                        capture_forward=False)
        cfg["env_passthrough"] = FAKE_ENV
        cfg_path.write_text(json.dumps(cfg, indent=1))
        cls.run_stage("prepare")
        for name in ("redactions.json", "eras.json"):
            shutil.copy(FIXTURE / name, cls.ws_path / "prepare" / name)
        cls.run_stage("prepare")
        for name in ("self-prediction.md", "ipip-120.csv"):
            shutil.copy(FIXTURE / name, cls.ws_path / "sealed" / name)
        for stage in ("seal", "freeze", "extract", "unmask"):
            cls.run_stage(stage)
        cls.ws = store.Workspace(cls.ws_path)
        cls.results = store.read_json(cls.ws.path("report/results.json"))
        cls.report = cls.ws.path("report/report.md").read_text()
        cls.prompts = [json.loads(line) for line in (cls.log / "prompts.jsonl").read_text().splitlines()]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def run_stage(cls, stage: str, *extra: str):
        p = subprocess.run([sys.executable, str(RUN), stage, str(cls.ws_path), *extra], env=cls.env,
                           capture_output=True, text=True, timeout=600, check=False)
        cls.codes[stage] = p.returncode
        if p.returncode != 0:
            raise AssertionError(f"{stage} exited {p.returncode}: {p.stderr[-2000:]}")

    def test_every_stage_completed_and_status_is_done(self):
        self.assertTrue(all(code == 0 for code in self.codes.values()), self.codes)
        p = subprocess.run([sys.executable, str(RUN), "status", str(self.ws_path)], env=self.env,
                           capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(p.stdout)["next"], "done: read report/report.md")
        self.assertEqual([e["gen"] for e in store.verify_manifest(self.ws)], ["A", "B", "C", "D", "E"])

    def test_report_first_section_is_non_clinical(self):
        headings = [line for line in self.report.splitlines() if line.startswith("## ")]
        self.assertEqual(headings[0], "## This is not a clinical assessment")

    def test_report_is_not_vacuous(self):
        p = self.results["predictions"]
        self.assertTrue(p["inductive_reportable"])
        self.assertGreater(p["supported_eligible"], 0)
        self.assertGreater(len(p["matched"]), 0)
        self.assertGreater(self.results["deductive_vs_ipip"]["compared"], 0)
        self.assertGreater(self.results["agreement"]["downgrades"], 0)

    def test_agreement_figures_recompute_from_run_files(self):
        r = extract.Run(self.ws)
        book = store.read_json(self.ws.path("run/codebook/codebook.json"))
        verdicts = {}
        for path in sorted(self.ws.root.glob("run/recode/*.json")):
            lineage, run, era = path.stem.split("-")
            verdicts[f"{lineage}|{run[1:]}|{era}"] = store.read_json(path)
        scores = {}
        for path in sorted(self.ws.root.glob("run/deductive/scores-*.json")):
            _, lineage, run = path.stem.split("-")
            scores[f"{lineage}|{run[1:]}"] = {s["facet"]: s["score"] for s in store.read_json(path)["scores"]}
        units = [f"{c['item_id']}@{e}" for c in book["constructs"] for e in r.era_ids]
        runs = {lin: {str(n): {} for n in r.runs} for lin in r.lineages}
        for key, rows in verdicts.items():
            lin, run, era = key.split("|")
            for v in rows:
                runs[lin][run][f"{v['item_id']}@{era}"] = None if v["verdict"] == "insufficient" else v["verdict"]
        ind = agreement.arm(runs, units, "nominal")
        ded = agreement.arm({lin: {str(n): scores[f"{lin}|{n}"] for n in r.runs} for lin in r.lineages},
                            extract.FACETS, "ordinal")
        reported = self.results["agreement"]
        self.assertEqual(reported["inductive"]["alpha"], ind.alpha)
        self.assertEqual(reported["deductive"]["alpha"], ded.alpha)
        self.assertEqual(reported["downgrades"], sum(1 for rows in verdicts.values() for v in rows if v["downgrade"]))
        for value in (ind.alpha, ded.alpha):
            self.assertIn(f"{value:.3f}", self.report)

    def test_comparison_figures_recompute_from_frozen_inputs(self):
        inst = ipip.load_instrument()
        self_report = ipip.score(ipip.parse_responses(self.ws.path("sealed/ipip-120.csv").read_text(), inst), inst)
        agree = store.read_json(self.ws.path("run/agreement.json"))
        observer = unmask.deductive_domains(agree["deductive_collapsed"], inst)
        self.assertEqual(self.results["deductive_vs_ipip"]["domains"],
                         json.loads(json.dumps(unmask.domain_comparison(observer, self_report)["domains"])))
        codes = {c: store.read_json(self.ws.path(f"run/crosswalk/codes-{c}.json")) for c in ("claude", "codex")}
        supported = {cid for cid, eras in agree["construct_status"].items() if "supported" in eras.values()}
        rates = unmask.prediction_rates(codes, ["P1", "P2", "P3", "P4"], supported)
        self.assertEqual(self.results["predictions"]["predictions_matched_rate"], rates["predictions_matched_rate"])
        self.assertIn(f"{rates['predictions_matched_rate']:.0%}", self.report)

    def test_sealed_content_reaches_crosswalk_prompts_only_and_ipip_none(self):
        predictions = [line.split(":", 1)[1].strip() for line in
                       (FIXTURE / "self-prediction.md").read_text().splitlines() if line.startswith("P")]
        answers = [line for line in (FIXTURE / "ipip-120.csv").read_text().splitlines()[1:] if line[-1].isdigit()]
        roles = [p["prompt"].splitlines()[0] for p in self.prompts]
        first_crosswalk = roles.index("# abx-role: crosswalk")
        self.assertTrue(all(r != "# abx-role: crosswalk" for r in roles[:first_crosswalk]))
        self.assertGreater(first_crosswalk, max(i for i, r in enumerate(roles) if r == "# abx-role: recode"))
        for i, p in enumerate(self.prompts):
            carries = any(s in p["prompt"] for s in predictions)
            self.assertEqual(carries, roles[i] == "# abx-role: crosswalk", roles[i])
            self.assertFalse(any(a in p["prompt"] for a in answers))
            self.assertNotIn("Collins", p["prompt"])
            self.assertNotIn("Keimer", p["prompt"])


if __name__ == "__main__":
    unittest.main()
