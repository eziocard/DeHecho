"""Lectura directa de datos ambientales; las mutaciones usan copias temporales."""

import json
import logging
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.application import create_app
from app.config import Settings
from app.datos.environment import (
    CLEAN,
    DATA,
    INPUT_PATHS,
    TRENDS_CSV,
    TRENDS_REPORT,
    EnvironmentAdapter,
    csv_records,
    digest,
)

PROJECT = Path(__file__).resolve().parents[1]


class EnvironmentIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logger = logging.getLogger("app.datos.load_environment")
        level = logger.level
        logger.setLevel(logging.CRITICAL)
        cls.addClassCleanup(logger.setLevel, level)
        cls.temp = tempfile.TemporaryDirectory(prefix="dehecho-environment-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.files = {path: (PROJECT / path).read_bytes() for path in INPUT_PATHS}
        for path, content in cls.files.items():
            destination = cls.root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        cls.client = TestClient(create_app(Settings(project_root=cls.root)))
        cls.client.__enter__()
        cls.addClassCleanup(cls.client.__exit__, None, None, None)

    def test_health_and_catalog_with_real_data(self):
        health = self.client.get("/health").json()
        self.assertEqual(health, {"status": "ok"})
        catalog = self.client.get("/api/catalogo").json()
        datasets = {item["id"]: item for item in catalog}
        self.assertEqual(set(datasets), {"ambiente_region", "ambiente_comunas", "tendencias_ambientales"})
        self.assertEqual(datasets["ambiente_region"]["territories"], ["09"])
        self.assertEqual(len(datasets["ambiente_comunas"]["territories"]), 32)
        self.assertEqual(len(datasets["ambiente_comunas"]["variables"]), 4)
        self.assertIn("puntos porcentuales/década", datasets["tendencias_ambientales"]["units"])
        for item in datasets.values():
            self.assertTrue(item["available"])
            self.assertNotIn("metadata", item)
        publication = self.client.app.state.publication
        for spec in publication.manifest.artifacts:
            self.assertFalse(any("conaf" in key.lower() for key in spec.depends_on))

    def test_every_regional_observation_matches_its_csv(self):
        source = {row["month"]: row for row in csv_records(self.files[f"{CLEAN}/region_mensual_limpio.csv"])}
        result = self.client.get("/api/series", params={"dataset": "ambiente_region"}).json()
        self.assertEqual(len(result), 4)
        self.assertEqual(sum(len(group["points"]) for group in result), 480)
        for group in result:
            self.assertEqual(group["territory_id"], "09")
            for point in group["points"]:
                row = source[point["start"][:7]]
                self.assertEqual(point["value"], float(row[group["variable"]]))
        manifest = self.client.app.state.publication.manifest
        self.assertEqual(manifest.analysis_config["load_mode"], "direct")
        self.assertFalse(manifest.analysis_config["reestimated"])

    def test_communal_observations_and_quality_match_csv(self):
        source = {(row["commune_id"], row["month"]): row
                  for row in csv_records(self.files[f"{CLEAN}/comunas_mensual_limpio.csv"])}
        result = self.client.get("/api/series", params={"dataset": "ambiente_comunas"}).json()
        self.assertEqual(len(result), 128)
        self.assertEqual(sum(len(group["points"]) for group in result), 15360)
        masked = 0
        for group in result:
            for point in group["points"]:
                row = source[group["territory_id"], point["start"][:7]]
                if group["variable"] == "soil_moisture_0_10cm_kgm2" and row["soil_coverage_ok"] == "False":
                    self.assertIsNone(point["value"])
                    self.assertEqual(point["missing_reason"], "insufficient_coverage")
                    masked += 1
                else:
                    self.assertEqual(point["value"], float(row[group["variable"]]))
        self.assertEqual(masked, 120)

    def test_saavedra_retains_other_variables_and_unknown_coverage(self):
        result = self.client.get("/api/series", params={
            "dataset": "ambiente_comunas", "territory_id": "09116",
            "start": "2015-01-15", "end": "2015-01-16",
        }).json()
        self.assertEqual(len(result), 4)
        points = {group["variable"]: group["points"][0] for group in result}
        self.assertIsNone(points["soil_moisture_0_10cm_kgm2"]["value"])
        self.assertIsNotNone(points["temperature_2m_c"]["value"])
        self.assertNotIn("metadata", points["relative_humidity_2m_pct"])
        self.assertEqual(points["temperature_2m_c"]["start"], "2015-01-01")
        self.assertEqual(points["temperature_2m_c"]["end"], "2015-01-31")
        internal = self.client.app.state.publication.documents["ambiente_comunas"]
        humidity = next(row for row in internal.records if row.variable == "relative_humidity_2m_pct")
        self.assertIsNone(humidity.metadata["coverage_pct"])
        self.assertEqual(internal.metadata.n_observations, 120)

    def test_all_trend_statistics_match_existing_export(self):
        source = {(row["geography_level"], row["territory_id"], row["variable"]): row
                  for row in csv_records(self.files[TRENDS_CSV])}
        result = self.client.get("/api/tendencias", params={"dataset": "tendencias_ambientales"}).json()
        self.assertEqual(len(result), 132)
        fields = {"slope_per_decade": "slope_per_decade", "ci95_marginal_low": "CI95_low_per_decade",
                  "ci95_marginal_high": "CI95_high_per_decade", "p_holm": "p_holm"}
        for record in result:
            row = source[record["geography_level"], record["territory_id"], record["variable"]]
            self.assertEqual(record["unit"], row["rate_unit"])
            for public, original in fields.items():
                self.assertEqual(record[public], float(row[original]) if row[original] else None)
            self.assertEqual(record["status"], row["status"])
            self.assertEqual(record["n_used"], int(row["n_used"]))
        internal = self.client.app.state.publication.documents["tendencias_ambientales"]
        for record in internal.records:
            row = source[record.metadata["geography_level"], record.territory_id, record.variable]
            for key in ("p_raw", "p_holm_HAC4", "p_holm_HAC8", "p_holm_HAC12", "p_holm_HAC18"):
                self.assertEqual(record.values[key], float(row[key]) if row[key] else None)

    def test_filtered_trend_keeps_holm_hac_period_and_sample(self):
        report = json.loads(self.files[TRENDS_REPORT])
        result = self.client.get("/api/tendencias", params={
            "dataset": "tendencias_ambientales", "variable": "relative_humidity_2m_pct", "territory_id": "09",
        }).json()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["period_start"], "2014-01-01")
        self.assertEqual(result[0]["period_end"], "2023-12-31")
        self.assertEqual(result[0]["status"], "evidence_decreasing")
        internal = self.client.app.state.publication.documents["tendencias_ambientales"]
        self.assertEqual(internal.metadata.method["multiplicity"], report["multiplicity"])
        self.assertEqual(internal.metadata.method["primary_inference"], report["primary_inference"])
        original = next(row for row in internal.records if row.variable == "relative_humidity_2m_pct" and row.territory_id == "09")
        self.assertEqual(original.values["family_n_tests"], 4)
        self.assertEqual(result[0]["p_holm"], original.values["p_holm"])
        excluded = self.client.get("/api/tendencias", params={
            "dataset": "tendencias_ambientales", "variable": "soil_moisture_0_10cm_kgm2", "territory_id": "09116",
        }).json()[0]
        self.assertEqual(excluded["status"], "insufficient_coverage")
        self.assertIsNone(excluded["slope_per_decade"])
        self.assertIsNone(excluded["ci95_marginal_low"])
        self.assertIsNone(excluded["p_holm"])
        self.assertEqual(excluded["n_used"], 0)
        self.assertIn("exclusion_reason", excluded)

    def test_regional_precipitation_state_is_not_inferred_from_marginal_interval(self):
        result = self.client.get("/api/tendencias", params={
            "dataset": "tendencias_ambientales", "variable": "precipitation_mm", "territory_id": "09",
        }).json()[0]
        self.assertLess(result["ci95_marginal_high"], 0)
        self.assertGreater(result["p_holm"], 0.05)
        self.assertEqual(result["status"], "uncertain_trend")

    def test_trend_response_contains_only_the_minimum_result(self):
        result = self.client.get("/api/tendencias", params={
            "dataset": "tendencias_ambientales", "territory_id": "09",
            "variable": "relative_humidity_2m_pct",
        }).json()[0]
        self.assertEqual(set(result), {
            "variable", "territory_id", "geography_level", "period_start", "period_end", "unit",
            "slope_per_decade", "ci95_marginal_low", "ci95_marginal_high", "p_holm", "status", "n_used",
        })
        self.assertEqual(result["n_used"], 120)

    def test_empty_interval_and_unsupported_reestimation(self):
        result = self.client.get("/api/series", params={
            "dataset": "ambiente_region", "start": "2024-01-01",
        })
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), [])
        result = self.client.get("/api/tendencias", params={
            "dataset": "tendencias_ambientales", "start": "2020-01-01",
        })
        self.assertEqual(result.status_code, 422)

    def test_original_files_are_unchanged_and_no_publication_is_created(self):
        for path, content in self.files.items():
            self.assertEqual((PROJECT / path).read_bytes(), content)
            self.assertEqual((self.root / path).read_bytes(), content)
        self.assertEqual({str(path.relative_to(self.root)) for path in self.root.rglob("*") if path.is_file()}, set(INPUT_PATHS))
        for spec in self.client.app.state.publication.manifest.sources:
            self.assertEqual(digest((self.root / spec.path).read_bytes()), spec.sha256)

    def test_historical_newlines_are_audited_without_weakening_manifest(self):
        files = dict(self.files)
        report = json.loads(files[TRENDS_REPORT])
        content = files[TRENDS_CSV].replace(b"\r\n", b"\n")
        files[TRENDS_CSV] = content
        report["output"]["sha256"] = digest(content.replace(b"\n", b"\r\n"))
        files[TRENDS_REPORT] = json.dumps(report).encode("utf-8")
        adapter = EnvironmentAdapter(files)
        audit = next(item for item in adapter.audit if item["file"] == TRENDS_CSV)
        self.assertEqual(audit["match"], "line_endings_only")
        self.assertEqual(audit["actual_sha256"], digest(content))
        self.assertNotEqual(audit["actual_sha256"], audit["recorded_sha256"])

    def test_changed_measurement_cannot_be_republished_as_old_analysis(self):
        files = dict(self.files)
        name = f"{CLEAN}/region_mensual_limpio.csv"
        files[name] = files[name].replace(b"16.026", b"16.027", 1)
        with self.assertRaisesRegex(ValueError, "no corresponde"):
            EnvironmentAdapter(files)

    def test_mismatched_units_are_rejected(self):
        files = dict(self.files)
        report = json.loads(files[TRENDS_REPORT])
        report["units"]["temperature_2m_c"]["observations"] = "K"
        files[TRENDS_REPORT] = json.dumps(report).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "unidades"):
            EnvironmentAdapter(files)

    def test_conflicting_quality_thresholds_are_rejected(self):
        files = dict(self.files)
        report = json.loads(files[TRENDS_REPORT])
        report["data_quality"]["soil_minimum_spatial_coverage_pct"] = 90
        files[TRENDS_REPORT] = json.dumps(report).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "umbral"):
            EnvironmentAdapter(files)

    def copy_inputs(self, folder):
        root = Path(folder)
        for name, content in self.files.items():
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        return root

    def test_changed_source_blocks_dependent_real_results_at_restart(self):
        with tempfile.TemporaryDirectory(prefix="dehecho-changed-input-") as folder:
            root = self.copy_inputs(folder)
            settings = Settings(project_root=root)
            with TestClient(create_app(settings)) as client:
                before = client.get("/api/series", params={"dataset": "ambiente_region"}).json()
                path = root / f"{CLEAN}/region_mensual_limpio.csv"
                path.write_bytes(path.read_bytes().replace(b"16.026", b"16.027", 1))
                self.assertEqual(client.get("/api/series", params={"dataset": "ambiente_region"}).json(), before)
            with TestClient(create_app(settings)) as client:
                available = {item["id"]: item["available"] for item in client.get("/api/catalogo").json()}
                self.assertEqual(available, {"ambiente_region": False, "tendencias_ambientales": False, "ambiente_comunas": True})
                self.assertEqual(client.app.state.publication.states[f"input:{CLEAN}/region_mensual_limpio.csv"].status.value, "stale")
                response = client.get("/api/tendencias", params={"dataset": "tendencias_ambientales"})
                self.assertEqual(response.status_code, 503)

    def test_invalid_soil_indicator_is_not_silently_applied(self):
        adapter = EnvironmentAdapter(dict(self.files))
        name = f"{CLEAN}/region_mensual_limpio.csv"
        adapter.files[name] = adapter.files[name].replace(b",True", b",False", 1)
        with self.assertRaisesRegex(ValueError, "indicador de calidad"):
            adapter.series("region")

    def test_invalid_calendar_is_rejected(self):
        adapter = EnvironmentAdapter(dict(self.files))
        name = f"{CLEAN}/region_mensual_limpio.csv"
        adapter.files[name] = adapter.files[name].replace(b"2014-02", b"2014-01", 1)
        with self.assertRaisesRegex(ValueError, "duplicados"):
            adapter.series("region")

    def test_changed_statistics_are_not_served_as_valid(self):
        with tempfile.TemporaryDirectory(prefix="dehecho-bad-input-") as folder:
            root = self.copy_inputs(folder)
            path = root / TRENDS_CSV
            path.write_bytes(path.read_bytes().replace(b"0.651969", b"0.751969", 1))
            with TestClient(create_app(Settings(project_root=root))) as client:
                self.assertEqual(client.get("/health").json(), {"status": "degraded"})
                response = client.get("/api/tendencias", params={"dataset": "tendencias_ambientales"})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], "dataset_stale")
                self.assertEqual(client.get("/api/series", params={"dataset": "ambiente_region"}).status_code, 200)
            self.assertFalse((root / "publicaciones").exists())

    def test_missing_input_only_blocks_its_dependents(self):
        with tempfile.TemporaryDirectory(prefix="dehecho-missing-input-") as folder:
            root = self.copy_inputs(folder)
            (root / f"{DATA}/region_mensual.csv").unlink()
            with TestClient(create_app(Settings(project_root=root))) as client:
                available = {item["id"]: item["available"] for item in client.get("/api/catalogo").json()}
                self.assertEqual(available, {"ambiente_region": False, "ambiente_comunas": True, "tendencias_ambientales": False})
                response = client.get("/api/series", params={"dataset": "ambiente_region"})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], "dataset_unavailable")

    def test_missing_project_does_not_crash_the_service(self):
        with (
            tempfile.TemporaryDirectory(prefix="dehecho-empty-project-") as folder,
            self.assertLogs("app.datos.load_environment", level="WARNING"),
            TestClient(create_app(Settings(project_root=Path(folder)))) as client,
        ):
            self.assertEqual(client.get("/health").json(), {"status": "degraded"})
            response = client.get("/api/series", params={"dataset": "ambiente_region"})
            self.assertEqual(response.status_code, 503)

    def test_malformed_report_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory(prefix="dehecho-bad-report-") as folder:
            root = self.copy_inputs(folder)
            (root / TRENDS_REPORT).write_text("not json")
            with (
                self.assertLogs("app.datos.load_environment", level="WARNING"),
                TestClient(create_app(Settings(project_root=root))) as client,
            ):
                self.assertEqual(client.get("/health").json(), {"status": "degraded"})
                response = client.get("/api/tendencias", params={"dataset": "tendencias_ambientales"})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], "dataset_invalid")


if __name__ == "__main__":
    unittest.main()
