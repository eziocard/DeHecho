"""Integración real CONAF; todas las modificaciones se hacen en copias temporales."""

import csv
import io
import json
import logging
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.application import create_app
from app.config import Settings
from app.datos.conaf import (
    CONTEXT,
    DEFINITIVE,
    MODEL,
    REPORT,
    SOURCE_PATHS,
    TERMS,
    ConafAdapter,
)
from app.datos.conaf import (
    INPUT_PATHS as CONAF_INPUTS,
)
from app.datos.environment import INPUT_PATHS as ENVIRONMENT_INPUTS
from app.datos.environment import csv_records, digest
from app.datos.exploration import INPUT_PATHS as EXPLORATION_INPUTS
from app.datos.load_data import load_data

PROJECT = Path(__file__).resolve().parents[1]


class ConafIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name in ("app.datos.load_environment", "app.datos.load_conaf", "app.datos.load_exploration"):
            logger = logging.getLogger(name)
            level = logger.level
            logger.setLevel(logging.CRITICAL)
            cls.addClassCleanup(logger.setLevel, level)
        cls.temp = tempfile.TemporaryDirectory(prefix="dehecho-conaf-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.files = {path: (PROJECT / path).read_bytes()
                     for path in dict.fromkeys((*ENVIRONMENT_INPUTS, *CONAF_INPUTS, *EXPLORATION_INPUTS))}
        cls.write_inputs(cls.root)
        cls.client = TestClient(create_app(Settings(project_root=cls.root)))
        cls.client.__enter__()
        cls.addClassCleanup(cls.client.__exit__, None, None, None)

    @classmethod
    def write_inputs(cls, root):
        for name, content in cls.files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def copy_inputs(self):
        temp = tempfile.TemporaryDirectory(prefix="dehecho-conaf-change-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.write_inputs(root)
        return root

    @staticmethod
    def edit_csv(path, edit):
        rows = csv_records(path.read_bytes())
        edit(rows)
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        path.write_bytes(output.getvalue().encode("utf-8-sig"))

    def assert_conaf_blocked(self, root, status):
        with TestClient(create_app(Settings(project_root=root))) as client:
            self.assertEqual(client.get("/health").json(), {"status": "degraded"})
            available = {item["id"]: item["available"] for item in client.get("/api/catalogo").json()}
            self.assertEqual(available, {
                "ambiente_region": True, "ambiente_comunas": True, "tendencias_ambientales": True,
                "asociaciones_conaf": False, "hallazgos_conaf": False,
                "tendencias_regionales_exploratorias": True, "hallazgos_ambientales": True,
            })
            for endpoint, dataset in (("asociaciones", "asociaciones_conaf"), ("hallazgos", "hallazgos_conaf")):
                response = client.get(f"/api/{endpoint}", params={"dataset": dataset})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], f"dataset_{status}")
            self.assertEqual(client.get("/api/tendencias", params={"dataset": "tendencias_ambientales"}).status_code, 200)

    def test_all_seven_datasets_are_available(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        catalog = {item["id"]: item for item in self.client.get("/api/catalogo").json()}
        self.assertEqual(len(catalog), 7)
        self.assertTrue(all(item["available"] for item in catalog.values()))
        self.assertEqual(catalog["asociaciones_conaf"]["territories"], ["09"])
        self.assertEqual(set(catalog["asociaciones_conaf"]["variables"]), {item[0] for item in TERMS.values()})
        self.assertIn("mm/mes", catalog["asociaciones_conaf"]["units"])
        self.assertEqual(catalog["hallazgos_conaf"]["kind"], "hallazgos")

    def test_four_coefficients_match_the_csv_without_reestimation(self):
        rows = {row["term"]: row for row in csv_records(self.files[MODEL])}
        result = self.client.get("/api/asociaciones", params={"dataset": "asociaciones_conaf"})
        self.assertEqual(result.status_code, 200)
        result = result.json()
        self.assertEqual(len(result), 4)
        for term, (variable, direction) in TERMS.items():
            row = rows[term]
            output = next(item for item in result if item["variable"] == variable)
            self.assertEqual(output["rate_ratio"], float(row["rate_ratio"]))
            self.assertEqual(output["ci95_marginal_low"], float(row["CI95_low"]))
            self.assertEqual(output["ci95_marginal_high"], float(row["CI95_high"]))
            self.assertEqual(output["p_holm"], float(row["p_Holm_four_terms"]))
            self.assertEqual(output["increment"], float(row["one_sd_original_units"]))
            self.assertEqual(output["unit"], row["unit"])
            self.assertEqual(output["direction"], "increase" if direction == 1 else "decrease")
            self.assertEqual(output["period_start"], "2014-07-01")
            self.assertEqual(output["period_end"], "2023-12-31")
            self.assertEqual(output["territory_id"], "09")
            self.assertEqual(output["n_used"], 114)
        self.assertFalse(self.client.app.state.publication.manifest.analysis_config["reestimated"])

    def test_deficit_direction_is_not_the_sign_of_the_rate_ratio(self):
        result = self.client.get("/api/asociaciones", params={"dataset": "asociaciones_conaf"}).json()
        by_variable = {row["variable"]: row for row in result}
        rain = by_variable["precipitation_mm"]
        self.assertEqual(rain["direction"], "decrease")
        self.assertGreater(rain["rate_ratio"], 1)
        self.assertAlmostEqual(rain["increment"], 49.59582851544603)
        self.assertEqual(by_variable["relative_humidity_2m_pct"]["direction"], "decrease")
        self.assertLess(by_variable["relative_humidity_2m_pct"]["rate_ratio"], 1)
        self.assertEqual(by_variable["temperature_2m_c"]["direction"], "increase")

    def test_filter_keeps_the_published_effect_and_family(self):
        all_rows = self.client.get("/api/asociaciones", params={"dataset": "asociaciones_conaf"}).json()
        filtered = self.client.get("/api/asociaciones", params={
            "dataset": "asociaciones_conaf", "variable": "precipitation_mm", "territory_id": "09",
        }).json()
        self.assertEqual(filtered, [row for row in all_rows if row["variable"] == "precipitation_mm"])
        internal = self.client.app.state.publication.documents["asociaciones_conaf"]
        self.assertIn("four primary NB", internal.metadata.method["multiplicity"])
        self.assertEqual(internal.metadata.method["HAC"]["maxlags"], 4)

    def test_five_findings_preserve_the_published_qualifications(self):
        response = self.client.get("/api/hallazgos", params={"dataset": "hallazgos_conaf"})
        self.assertEqual(response.status_code, 200)
        rows = {row["id"]: row for row in response.json()}
        self.assertEqual(len(rows), 5)
        self.assertIn("estable", rows["conaf:rain_deficit"]["title"])
        self.assertIn("49.60", rows["conaf:rain_deficit"]["summary"])
        self.assertIn("todas las variantes", rows["conaf:rain_deficit"]["summary"])
        self.assertIn("sensible", rows["conaf:soil_deficit"]["title"])
        self.assertIn("cada año", rows["conaf:soil_deficit"]["summary"])
        self.assertIn("0.828", rows["conaf:soil_deficit"]["summary"])
        for term in ("heat", "rh_deficit"):
            self.assertIn("insuficiente", rows[f"conaf:{term}"]["title"])
            self.assertIn("no demuestra ausencia", rows[f"conaf:{term}"]["summary"])
        for term in TERMS:
            self.assertIn("no causalidad ni pronóstico", rows[f"conaf:{term}"]["summary"])
        presence = rows["conaf:monthly_presence"]
        for value in ("114", "100", "14"):
            self.assertIn(value, presence["summary"])
        self.assertNotIn("variable", presence)
        self.assertEqual(presence["period_start"], "2014-07-01")

    def test_finding_filter_returns_a_real_soil_result(self):
        rows = self.client.get("/api/hallazgos", params={
            "dataset": "hallazgos_conaf", "variable": "soil_moisture_0_10cm_kgm2", "territory_id": "09",
        }).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "conaf:soil_deficit")

    def test_unknown_and_incompatible_queries_remain_distinct(self):
        cases = [
            ("asociaciones", {"dataset": "no_existe"}, 404),
            ("asociaciones", {"dataset": "tendencias_ambientales"}, 422),
            ("hallazgos", {"dataset": "asociaciones_conaf"}, 422),
            ("asociaciones", {"dataset": "asociaciones_conaf", "variable": "rain_deficit"}, 422),
            ("asociaciones", {"dataset": "asociaciones_conaf", "territory_id": "09101"}, 422),
            ("hallazgos", {"dataset": "hallazgos_conaf", "start": "2020-01-01"}, 422),
        ]
        for endpoint, params, status in cases:
            with self.subTest(params=params):
                self.assertEqual(self.client.get(f"/api/{endpoint}", params=params).status_code, status)

    def test_no_technical_metadata_is_exposed(self):
        forbidden = {"metadata", "provenance", "values", "sha256", "source_sha256", "analysis_config",
                     "diagnostics", "dependencies", "HAC", "multiplicity", "warnings", "records"}

        def check(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for item in value.values():
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)
        for endpoint, dataset in (("asociaciones", "asociaciones_conaf"), ("hallazgos", "hallazgos_conaf")):
            check(self.client.get(f"/api/{endpoint}", params={"dataset": dataset}).json())

    def test_input_files_are_read_once_for_all_loaders(self):
        reads = Counter()
        original = Path.read_bytes

        def read(path):
            reads[str(path.relative_to(self.root))] += 1
            return original(path)
        with patch.object(Path, "read_bytes", read):
            loaded = load_data(self.root)
        self.assertEqual(reads, Counter({path: 1 for path in self.files}))
        self.assertEqual(len(loaded.documents), 7)

    def test_original_files_are_not_modified_and_nothing_is_generated(self):
        for name, content in self.files.items():
            self.assertEqual((PROJECT / name).read_bytes(), content)
            self.assertEqual((self.root / name).read_bytes(), content)
        self.assertEqual({str(path.relative_to(self.root)) for path in self.root.rglob("*") if path.is_file()}, set(self.files))

    def test_regional_conaf_change_blocks_only_conaf_results(self):
        root = self.copy_inputs()
        path = root / SOURCE_PATHS["conaf.csv"]
        self.edit_csv(path, lambda rows: rows[0].update(IX="1"))
        self.assert_conaf_blocked(root, "stale")

    def test_communal_conaf_change_blocks_only_conaf_results(self):
        root = self.copy_inputs()
        self.edit_csv(root / SOURCE_PATHS["conaf_comuna.csv"], lambda rows: rows[0].update(numero_incendios="64"))
        self.assert_conaf_blocked(root, "stale")

    def test_definitive_count_change_is_detected_even_when_raw_sources_are_unchanged(self):
        root = self.copy_inputs()
        self.edit_csv(root / DEFINITIVE, lambda rows: rows[0].update(IX="1"))
        self.assert_conaf_blocked(root, "stale")

    def test_definitive_weather_change_is_detected(self):
        root = self.copy_inputs()
        self.edit_csv(root / DEFINITIVE, lambda rows: rows[0].update(temperature_2m_c="4.942"))
        self.assert_conaf_blocked(root, "stale")

    def test_changed_model_export_is_blocked(self):
        root = self.copy_inputs()
        self.edit_csv(root / MODEL, lambda rows: rows[0].update(rate_ratio="0.95"))
        self.assert_conaf_blocked(root, "stale")

    def test_updating_a_hash_cannot_hide_csv_json_disagreement(self):
        root = self.copy_inputs()
        self.edit_csv(root / MODEL, lambda rows: rows[0].update(rate_ratio="0.95"))
        report = json.loads((root / REPORT).read_bytes())
        report["inferential_followup"]["output"]["sha256"] = digest((root / MODEL).read_bytes())
        (root / REPORT).write_text(json.dumps(report))
        self.assert_conaf_blocked(root, "invalid")

    def test_flipped_deficit_direction_is_rejected(self):
        root = self.copy_inputs()
        report = json.loads((root / REPORT).read_bytes())
        scale = report["inferential_followup"]["coefficient_scale"][1]
        self.assertEqual(scale["term"], "rain_deficit")
        scale["direction"] = 1
        (root / REPORT).write_text(json.dumps(report))
        self.assert_conaf_blocked(root, "invalid")

    def test_false_stability_claim_is_rejected(self):
        root = self.copy_inputs()
        report = json.loads((root / REPORT).read_bytes())
        report["inferential_followup"]["terms_supported_all_sensitivity_specifications"].append("soil_deficit")
        (root / REPORT).write_text(json.dumps(report))
        self.assert_conaf_blocked(root, "invalid")

    def test_failed_sensitivity_fit_is_not_presented_as_stable_evidence(self):
        root = self.copy_inputs()
        report = json.loads((root / REPORT).read_bytes())
        report["inferential_followup"]["sensitivity_diagnostics"][0]["converged"] = False
        (root / REPORT).write_text(json.dumps(report))
        self.assert_conaf_blocked(root, "invalid")

    def test_inconsistent_effect_label_is_rejected(self):
        root = self.copy_inputs()
        report = json.loads((root / REPORT).read_bytes())
        report["inferential_followup"]["coefficient_scale"][1]["label"] = "Otra variable"
        (root / REPORT).write_text(json.dumps(report))
        self.assert_conaf_blocked(root, "invalid")

    def test_missing_report_does_not_break_environmental_queries(self):
        root = self.copy_inputs()
        (root / REPORT).unlink()
        self.assert_conaf_blocked(root, "unavailable")

    def test_invalid_json_does_not_break_environmental_queries(self):
        root = self.copy_inputs()
        (root / REPORT).write_text("not json")
        self.assert_conaf_blocked(root, "invalid")

    def test_both_line_endings_are_accepted_without_ignoring_content(self):
        for ending in (b"\n", b"\r\n"):
            with self.subTest(ending=ending):
                root = self.copy_inputs()
                for name in (*SOURCE_PATHS.values(), MODEL, CONTEXT):
                    content = self.files[name].replace(b"\r\n", b"\n")
                    (root / name).write_bytes(content.replace(b"\n", ending))
                with TestClient(create_app(Settings(project_root=root))) as client:
                    self.assertEqual(client.get("/health").json(), {"status": "ok"})
                    self.assertEqual(client.get("/api/asociaciones", params={"dataset": "asociaciones_conaf"}).status_code, 200)

    def test_reordering_definitive_rows_does_not_invalidate_observations(self):
        root = self.copy_inputs()
        self.edit_csv(root / DEFINITIVE, lambda rows: rows.reverse())
        with TestClient(create_app(Settings(project_root=root))) as client:
            self.assertEqual(client.get("/health").json(), {"status": "ok"})

    def test_extra_months_do_not_extend_the_estimated_period(self):
        root = self.copy_inputs()

        def append(rows):
            rows.append(dict(rows[-1], fecha="2024-01-01"))
        self.edit_csv(root / DEFINITIVE, append)
        with TestClient(create_app(Settings(project_root=root))) as client:
            rows = client.get("/api/asociaciones", params={"dataset": "asociaciones_conaf"}).json()
            self.assertEqual(len(rows), 4)
            self.assertTrue(all(row["n_used"] == 114 and row["period_end"] == "2023-12-31" for row in rows))

    def test_adapter_preserves_zero_months_and_reported_scales(self):
        adapter = ConafAdapter({name: self.files[name] for name in CONAF_INPUTS})
        self.assertEqual(adapter.zeros, 14)
        self.assertEqual(adapter.with_fire, 100)
        self.assertEqual(adapter.stable_terms, {"rain_deficit"})
        self.assertEqual(len(adapter.audit), 8)


if __name__ == "__main__":
    unittest.main()
