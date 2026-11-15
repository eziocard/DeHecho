"""Integración exploratoria regional; las mutaciones usan copias temporales."""

import csv
import io
import json
import logging
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.application import create_app
from app.config import Settings
from app.datos.conaf import INPUT_PATHS as CONAF_INPUTS
from app.datos.environment import INPUT_PATHS as ENVIRONMENT_INPUTS
from app.datos.environment import csv_records, digest
from app.datos.exploration import INPUT_PATHS, PUBLISHED_TRENDS, REGION, REPORT, TABLE, UNITS
from app.datos.load_conaf import load_conaf
from app.datos.load_environment import load_environment

PROJECT = Path(__file__).resolve().parents[1]
TRENDS = "tendencias_regionales_exploratorias"
FINDINGS = "hallazgos_ambientales"


class ExplorationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name in ("app.datos.load_environment", "app.datos.load_conaf", "app.datos.load_exploration"):
            logger = logging.getLogger(name)
            level = logger.level
            logger.setLevel(logging.CRITICAL)
            cls.addClassCleanup(logger.setLevel, level)
        cls.files = {name: (PROJECT / name).read_bytes()
                     for name in dict.fromkeys((*ENVIRONMENT_INPUTS, *CONAF_INPUTS, *INPUT_PATHS))}
        cls.temp = tempfile.TemporaryDirectory(prefix="dehecho-exploration-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
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
        temp = tempfile.TemporaryDirectory(prefix="dehecho-exploration-change-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.write_inputs(root)
        return root

    def edit_report(self, edit):
        root = self.copy_inputs()
        report = json.loads(self.files[REPORT])
        edit(report)
        (root / REPORT).write_text(json.dumps(report))
        return root

    def assert_exploration_blocked(self, root, status, *, shared_source=False):
        with TestClient(create_app(Settings(project_root=root))) as client:
            self.assertEqual(client.get("/health").json(), {"status": "degraded"})
            catalog = {item["id"]: item for item in client.get("/api/catalogo").json()}
            self.assertEqual(len(catalog), 7)
            for endpoint, dataset in (("tendencias", TRENDS), ("hallazgos", FINDINGS)):
                self.assertFalse(catalog[dataset]["available"])
                response = client.get(f"/api/{endpoint}", params={"dataset": dataset})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], f"dataset_{status}")
            independent = {"asociaciones_conaf", "hallazgos_conaf"}
            if not shared_source:
                independent.update({"ambiente_region", "ambiente_comunas", "tendencias_ambientales"})
            self.assertTrue(all(catalog[name]["available"] for name in independent))

    def test_catalog_identifies_exploratory_regional_results(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        catalog = {item["id"]: item for item in self.client.get("/api/catalogo").json()}
        self.assertEqual(set(catalog[TRENDS]["variables"]), set(UNITS))
        for key in (TRENDS, FINDINGS):
            self.assertTrue(catalog[key]["available"])
            self.assertEqual(catalog[key]["territories"], ["09"])
            self.assertIn("exploratori", catalog[key]["label"].lower())

    def test_all_fourteen_estimates_match_csv_and_json_exactly(self):
        source = {row["variable"]: row for row in json.loads(self.files[REPORT])["results"]}
        table = {row["variable"]: row for row in csv_records(self.files[TABLE])}
        response = self.client.get("/api/tendencias", params={"dataset": TRENDS})
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        self.assertEqual(len(rows), 14)
        for row in rows:
            original, csv_row = source[row["variable"]], table[row["variable"]]
            for public, field in (("slope_per_decade", "slope_per_decade"),
                                  ("ci95_marginal_low", "CI95_low_per_decade"),
                                  ("ci95_marginal_high", "CI95_high_per_decade"),
                                  ("p_holm", "p_holm_14")):
                self.assertEqual(row[public], original[field])
                self.assertEqual(row[public], float(csv_row[field]))
            self.assertEqual(row["n_used"], 120)
            self.assertEqual(row["territory_id"], "09")
            self.assertEqual(row["geography_level"], "region")
            self.assertEqual(row["period_start"], "2014-01-01")
            self.assertEqual(row["period_end"], "2023-12-31")
            self.assertEqual(row["unit"], UNITS[row["variable"]][1])
            expected = "uncertain_trend"
            if original["p_holm_14"] < .05:
                expected = "evidence_increasing" if original["slope_per_decade"] > 0 else "evidence_decreasing"
            self.assertEqual(row["status"], expected)

    def test_filter_preserves_the_fourteen_test_family_not_the_original_four(self):
        all_rows = self.client.get("/api/tendencias", params={"dataset": TRENDS}).json()
        for variable in ("temperature_2m_c", "relative_humidity_2m_pct"):
            params = {"dataset": TRENDS, "variable": variable, "territory_id": "09"}
            filtered = self.client.get("/api/tendencias", params=params).json()
            self.assertEqual(filtered, [row for row in all_rows if row["variable"] == variable])
            original = self.client.get("/api/tendencias", params=dict(params, dataset="tendencias_ambientales")).json()[0]
            self.assertAlmostEqual(filtered[0]["slope_per_decade"], original["slope_per_decade"])
            self.assertNotEqual(filtered[0]["p_holm"], original["p_holm"])
        internal = self.client.app.state.publication.documents[TRENDS]
        self.assertTrue(internal.metadata.method["exploratory"])
        self.assertEqual(internal.metadata.method["family_n_tests"], 14)
        self.assertEqual(internal.metadata.method["HAC_lags"], 12)

    def test_evidence_uses_adjusted_p_not_the_marginal_interval(self):
        row = self.client.get("/api/tendencias", params={"dataset": TRENDS, "variable": "precipitation_mm"}).json()[0]
        self.assertLess(row["ci95_marginal_high"], 0)
        self.assertGreater(row["p_holm"], .05)
        self.assertEqual(row["status"], "uncertain_trend")

    def test_specific_humidity_is_not_rescaled_in_numeric_results(self):
        row = self.client.get("/api/tendencias", params={"dataset": TRENDS, "variable": "specific_humidity_2m_kgkg"}).json()[0]
        self.assertEqual(row["slope_per_decade"], -0.000761437070707071)
        self.assertEqual(row["unit"], "kg/kg por década")
        finding = self.client.get("/api/hallazgos", params={"dataset": FINDINGS, "variable": row["variable"]}).json()[0]
        self.assertIn("-0.761 g/kg por década", finding["summary"])

    def test_five_deterministic_findings_keep_interpretation_limits(self):
        params = {"dataset": FINDINGS}
        rows = self.client.get("/api/hallazgos", params=params).json()
        self.assertEqual(rows, self.client.get("/api/hallazgos", params=params).json())
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertIn("Exploratorio", row["title"])
            self.assertIn("Holm sobre 14 series", row["summary"])
            self.assertIn("no causalidad ni pronóstico", row["summary"])
            self.assertEqual(row["territory_id"], "09")
            self.assertEqual(row["period_start"], "2014-01-01")
            self.assertEqual(row["period_end"], "2023-12-31")
            filtered = self.client.get("/api/hallazgos", params=dict(params, variable=row["variable"], territory_id="09"))
            self.assertEqual(filtered.json(), [row])
        by_variable = {row["variable"]: row["summary"] for row in rows}
        peaks = by_variable["temperature_monthly_peak_area_mean_c"]
        self.assertIn("no días de ola de calor", peaks)
        self.assertIn("No se probó formalmente la diferencia", peaks)
        self.assertIn("La temperatura media no alcanza evidencia", peaks)
        for variable in ("vpd_from_monthly_T_RH_kpa", "vpd_from_monthly_T_Td_kpa"):
            self.assertIn("no es el VPD medio verdadero", by_variable[variable])
            self.assertIn("asociación ajustada con CONAF", by_variable[variable])

    def test_incompatible_queries_cannot_reinterpret_scope_or_period(self):
        for endpoint, params in (
            ("tendencias", {"dataset": TRENDS, "territory_id": "09101"}),
            ("hallazgos", {"dataset": FINDINGS, "territory_id": "09101"}),
            ("tendencias", {"dataset": TRENDS, "start": "2019-01-01"}),
            ("hallazgos", {"dataset": FINDINGS, "end": "2018-12-31"}),
            ("series", {"dataset": TRENDS}),
            ("asociaciones", {"dataset": TRENDS}),
            ("tendencias", {"dataset": FINDINGS}),
        ):
            with self.subTest(endpoint=endpoint, params=params):
                self.assertEqual(self.client.get(f"/api/{endpoint}", params=params).status_code, 422)

    def test_old_documents_and_series_scope_are_unchanged(self):
        expected = {**load_environment(self.root).documents, **load_conaf(self.root).documents}
        actual = self.client.app.state.publication.documents
        for name, document in expected.items():
            self.assertEqual(actual[name], document)
        self.assertEqual(len(actual["tendencias_ambientales"].records), 132)
        series = self.client.get("/api/series", params={"dataset": "ambiente_region"}).json()
        self.assertEqual(len(series), 4)
        self.assertEqual(sum(len(row["points"]) for row in series), 480)
        self.assertEqual(len(actual["asociaciones_conaf"].records), 4)
        self.assertEqual(len(actual["hallazgos_conaf"].records), 5)

    def test_no_internal_metadata_or_generic_envelopes_are_exposed(self):
        forbidden = {"metadata", "provenance", "values", "records", "sha256", "source_sha256", "analysis_config",
                     "diagnostics", "depends_on", "warnings", "family_n_tests", "HAC_lags", "multiplicity"}

        def check(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for item in value.values():
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)
        for endpoint, dataset in (("tendencias", TRENDS), ("hallazgos", FINDINGS)):
            response = self.client.get(f"/api/{endpoint}", params={"dataset": dataset})
            self.assertEqual(response.status_code, 200)
            self.assertIsInstance(response.json(), list)
            check(response.json())

    def test_missing_research_inputs_only_block_exploration(self):
        for name in (REPORT, TABLE):
            with self.subTest(name=name):
                root = self.copy_inputs()
                (root / name).unlink()
                self.assert_exploration_blocked(root, "unavailable")

    def test_invalid_json_only_blocks_exploration(self):
        for content in (b"not json", b'{"status":1,"status":2}', b'{"n":1e9999}'):
            with self.subTest(content=content):
                root = self.copy_inputs()
                (root / REPORT).write_bytes(content)
                self.assert_exploration_blocked(root, "invalid")

    def test_csv_json_disagreement_only_blocks_exploration(self):
        root = self.copy_inputs()
        rows = csv_records(self.files[TABLE])
        rows[0]["slope_per_decade"] = "0.7"
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        (root / TABLE).write_text(output.getvalue())
        self.assert_exploration_blocked(root, "invalid")

    def test_changed_shared_sources_mark_exploration_stale(self):
        for name in (REGION, PUBLISHED_TRENDS):
            with self.subTest(name=name):
                root = self.copy_inputs()
                (root / name).write_bytes(self.files[name] + b"\n")
                self.assert_exploration_blocked(root, "stale", shared_source=True)

    def test_only_lf_crlf_equivalence_is_accepted_for_historical_hashes(self):
        for ending in (b"\n", b"\r\n"):
            with self.subTest(ending=ending):
                root = self.copy_inputs()
                for name in (REGION, PUBLISHED_TRENDS):
                    (root / name).write_bytes(self.files[name].replace(b"\r\n", b"\n").replace(b"\n", ending))
                with TestClient(create_app(Settings(project_root=root))) as client:
                    self.assertEqual(client.get("/health").json(), {"status": "ok"})
                    self.assertEqual(len(client.get("/api/tendencias", params={"dataset": TRENDS}).json()), 14)

    def test_wrong_scope_method_or_definitions_are_not_silently_relabelled(self):
        for field, value in (("period", "2019-01/2023-12"), ("geography", "comunas"),
                             ("model", "OLS sin HAC"), ("multiplicity", "Holm sobre cuatro pruebas"),
                             ("derived_definitions", {}), ("status", "confirmed")):
            with self.subTest(field=field):
                root = self.edit_report(lambda report: report.update({field: value}))
                self.assert_exploration_blocked(root, "invalid")

    def test_incomplete_duplicate_or_unknown_family_is_rejected(self):
        edits = (
            lambda report: report["results"].pop(),
            lambda report: report["results"].append(report["results"][0]),
            lambda report: report["results"][0].update(variable="unknown"),
        )
        for edit in edits:
            self.assert_exploration_blocked(self.edit_report(edit), "invalid")

    def test_bad_units_sample_intervals_and_sensitivity_are_rejected(self):
        edits = (
            {"unit": "g/kg"}, {"n": 114}, {"n": True}, {"slope_per_decade": True},
            {"CI95_high_per_decade": -100}, {"p_holm_14": -1}, {"supported_all_HAC_lags": True},
            {"p_holm_14_by_HAC_lag": {"12": .2}},
            {"p_holm_14_by_HAC_lag": {"4": .2, "8": .2, "12": .2, "18": .2}},
        )
        for values in edits:
            with self.subTest(values=values):
                root = self.edit_report(lambda report: report["results"][0].update(values))
                self.assert_exploration_blocked(root, "invalid")

    def test_updating_source_hash_does_not_hide_invalid_calendar(self):
        root = self.copy_inputs()
        content = self.files[REGION].replace(b"2014-01", b"2014-02", 1)
        (root / REGION).write_bytes(content)
        report = json.loads(self.files[REPORT])
        report["source_sha256"][REGION] = digest(content)
        (root / REPORT).write_text(json.dumps(report))
        self.assert_exploration_blocked(root, "invalid", shared_source=True)

    def test_research_files_are_unchanged_and_nothing_is_generated(self):
        for name, content in self.files.items():
            self.assertEqual((PROJECT / name).read_bytes(), content)
            self.assertEqual((self.root / name).read_bytes(), content)
        self.assertEqual({str(path.relative_to(self.root)) for path in self.root.rglob("*") if path.is_file()}, set(self.files))
        self.assertEqual(json.loads(self.files[REPORT])["status"], "exploratory_not_published_to_API")


if __name__ == "__main__":
    unittest.main()
