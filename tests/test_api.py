"""Pruebas con publicaciones sintéticas; no fijan los datos finales de CONAF."""

import copy
import hashlib
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.application import create_app
from app.config import Settings
from app.datos.publication import load_publication


class ApiTests(unittest.TestCase):
    def setUp(self):
        logger = logging.getLogger("app.datos.publication")
        level = logger.level
        logger.setLevel(logging.CRITICAL)
        self.addCleanup(logger.setLevel, level)
        self.temp = tempfile.TemporaryDirectory(prefix="dehecho-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "manifest.json"
        self.manifest = {
            "schema_version": 1,
            "publication_id": "synthetic-1",
            "generated_at": "2026-01-01T00:00:00Z",
            "procedure_version": "synthetic-procedure-1",
            "analysis_config": {"synthetic": True},
            "sources": [],
            "artifacts": [],
        }
        for name in ("environment", "conaf"):
            path = self.root / f"{name}.csv"
            path.write_text("synthetic\n1\n")
            self.manifest["sources"].append({"id": name, "path": path.name, "sha256": self.digest(path)})
        self.metadata = {
            "period_start": "2020-01-01",
            "period_end": "2021-12-31",
            "time_scale": "month",
            "n_observations": 24,
            "warnings": ["Datos sintéticos; no representan hallazgos de DeHecho."],
            "reference": {"months": 24},
            "method": {"correction": "Holm", "family_n_tests": 4, "HAC_lags": 12,
                       "interval": "marginal"},
        }
        self.points = [
            {"variable": "temperature", "territory_id": "09", "geography_level": "region",
             "time_scale": "month", "period_start": "2020-01-01", "period_end": "2020-01-31",
             "unit": "°C", "value": 12.0, "metadata": {"coverage": None}},
            {"variable": "temperature", "territory_id": "09", "geography_level": "region",
             "time_scale": "month", "period_start": "2020-02-01", "period_end": "2020-02-29",
             "unit": "°C", "value": None, "missing_reason": "insufficient_coverage"},
        ]
        self.results = [
            {"id": "synthetic-slope", "variable": "temperature", "territory_id": "09",
             "values": {"slope_per_decade": 0.5, "CI95_low_per_decade": -0.1,
                        "CI95_high_per_decade": 1.1, "p_holm": 0.3, "status": "uncertain_trend", "n_used": 24},
             "metadata": {"rate_unit": "°C/década", "geography_level": "region"}},
            {"id": "synthetic-exclusion", "variable": "soil", "territory_id": "09001",
             "values": {"slope_per_decade": None, "CI95_low_per_decade": None,
                        "CI95_high_per_decade": None, "p_holm": None, "status": "insufficient_coverage",
                        "n_used": 0, "exclusion_reason": "insufficient_coverage"},
             "metadata": {"rate_unit": "kg/m² por década", "geography_level": "commune"}},
        ]
        self.associations = [
            {"id": "synthetic-correlation", "variable": "temperature", "territory_id": "09",
             "values": {"type": "correlation", "statistic": "spearman", "coefficient": 0.5,
                        "lag_months": 1, "n_used": 24, "p_holm": 0.3}},
            {"id": "synthetic-contrast", "variable": "temperature", "territory_id": "09",
             "values": {"type": "group_contrast", "group": "high_activity", "reference_group": "rest",
                        "difference": 0.0, "unit": "°C", "n_used": 24}},
            {"id": "synthetic-ratio", "variable": "rain", "territory_id": "09",
             "values": {"type": "rate_ratio", "rate_ratio": 1.5, "increment": 40.0,
                        "direction": "decrease", "unit": "mm/mes", "n_used": 24,
                        "ci95_marginal_low": 1.1, "ci95_marginal_high": 2.0}},
        ]
        self.findings = [
            {"id": "synthetic-finding", "variable": "temperature", "territory_id": "09",
             "values": {"title": "Hallazgo sintético", "summary": "No representa un hallazgo real."}},
        ]
        self.add_artifact("weather", "series", ["environment"], self.points)
        self.add_artifact("trends", "tendencias", ["environment"], self.results)
        self.add_artifact("joint", "series", ["environment", "conaf"], self.points)
        self.add_artifact("associations", "asociaciones", ["joint"], self.associations)
        self.add_artifact("findings", "hallazgos", ["associations"], self.findings)

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def add_artifact(self, name, kind, dependencies, records):
        path = self.root / f"{name}.json"
        path.write_text(json.dumps({"metadata": self.metadata, "records": records}), encoding="utf-8")
        specs = {item["id"]: item for item in self.manifest["sources"] + self.manifest["artifacts"]}
        self.manifest["artifacts"].append({
            "id": name, "path": path.name, "sha256": self.digest(path),
            "label": f"Synthetic {name}", "kind": kind,
            "depends_on": {key: specs[key]["sha256"] for key in dependencies},
        })

    def spec(self, name):
        return next(item for item in self.manifest["sources"] + self.manifest["artifacts"] if item["id"] == name)

    def rewrite_artifact(self, name, edit):
        spec = self.spec(name)
        path = self.root / spec["path"]
        document = json.loads(path.read_text())
        edit(document)
        path.write_text(json.dumps(document))
        spec["sha256"] = self.digest(path)

    def client(self, configured=True):
        self.path.write_text(json.dumps(self.manifest))
        return TestClient(create_app(data_loader=lambda: load_publication(self.path if configured else None)))

    @staticmethod
    def statuses(client):
        publication = client.app.state.publication
        return {item.id: publication.states[item.id].status.value for item in publication.manifest.artifacts}

    def test_start_without_final_data(self):
        with self.client(configured=False) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/health").json()["status"], "degraded")
            self.assertEqual(client.get("/api/catalogo").json(), [])
            response = client.get("/api/series", params={"dataset": "weather"})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "publication_unavailable")

    def test_missing_manifest(self):
        with TestClient(create_app(data_loader=lambda: load_publication(self.root / "absent.json"))) as client:
            self.assertEqual(client.get("/health").json()["status"], "degraded")

    def test_complete_publication_and_documentation(self):
        with self.client() as client:
            health = client.get("/health").json()
            self.assertEqual(health, {"status": "ok"})
            self.assertEqual(client.get("/docs").status_code, 200)
            schema = client.get("/openapi.json").json()
            self.assertIn("SeriesResponse", schema["components"]["schemas"])
            self.assertEqual(client.get("/api/catalogo").json()[0]["units"], ["°C"])

    def test_nulls_quality_and_zero_are_not_confused(self):
        self.points[0]["value"] = 0
        self.rewrite_artifact("weather", lambda doc: doc.update(records=self.points))
        with self.client() as client:
            response = client.get("/api/series", params={"dataset": "weather"})
            self.assertEqual(response.status_code, 200)
            records = response.json()[0]["points"]
            self.assertEqual(records[0]["value"], 0)
            self.assertNotIn("missing_reason", records[0])
            self.assertIsNone(records[1]["value"])
            self.assertEqual(records[1]["missing_reason"], "insufficient_coverage")

    def test_series_filters_overlap_without_exposing_internal_metadata(self):
        with self.client() as client:
            result = client.get("/api/series", params={
                "dataset": "weather", "variable": "temperature", "territory_id": "09",
                "start": "2020-01-15", "end": "2020-01-16",
            }).json()
            self.assertEqual(len(result), 1)
            self.assertEqual(len(result[0]["points"]), 1)
            self.assertEqual(result[0]["points"][0]["start"], "2020-01-01")
            self.assertEqual(result[0]["unit"], "°C")
            self.assertNotIn("metadata", result[0])
            self.assertEqual(client.app.state.publication.documents["weather"].metadata.n_observations, 24)

    def test_empty_valid_query_is_not_unavailable(self):
        with self.client() as client:
            response = client.get("/api/series", params={"dataset": "weather", "start": "2030-01-01"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), [])

    def test_results_keep_correction_and_references_when_filtered(self):
        with self.client() as client:
            response = client.get("/api/tendencias", params={"dataset": "trends", "territory_id": "09"})
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["p_holm"], 0.3)
            self.assertEqual(result[0]["n_used"], 24)
            self.assertEqual(result[0]["period_start"], "2020-01-01")
            self.assertEqual(result[0]["ci95_marginal_low"], -0.1)
            internal = client.app.state.publication.documents["trends"].metadata
            self.assertEqual(internal.method, self.metadata["method"])
            self.assertEqual(internal.reference, {"months": 24})

    def test_all_result_routes(self):
        with self.client() as client:
            for endpoint, dataset in [("tendencias", "trends"), ("asociaciones", "associations"), ("hallazgos", "findings")]:
                with self.subTest(endpoint=endpoint):
                    response = client.get(f"/api/{endpoint}", params={"dataset": dataset})
                    self.assertEqual(response.status_code, 200)
                    self.assertIsInstance(response.json(), list)
                    self.assertNotIn("values", response.json()[0])

    def test_association_types_have_explicit_result_fields(self):
        with self.client() as client:
            response = client.get("/api/asociaciones", params={"dataset": "associations"})
            self.assertEqual(response.status_code, 200)
            correlation, contrast, ratio = response.json()
            self.assertEqual(correlation["statistic"], "spearman")
            self.assertEqual(correlation["coefficient"], 0.5)
            self.assertEqual(correlation["lag_months"], 1)
            self.assertEqual(contrast["difference"], 0)
            self.assertEqual(contrast["reference_group"], "rest")
            self.assertEqual(ratio["rate_ratio"], 1.5)
            self.assertEqual(ratio["increment"], 40)
            self.assertEqual(ratio["direction"], "decrease")
            self.assertEqual(ratio["unit"], "mm/mes")
            self.assertNotIn("p_holm", ratio)
            self.assertNotIn("difference", correlation)

    def test_findings_only_return_published_content(self):
        with self.client() as client:
            response = client.get("/api/hallazgos", params={"dataset": "findings"})
            self.assertEqual(response.json(), [{
                "id": "synthetic-finding", "title": "Hallazgo sintético",
                "summary": "No representa un hallazgo real.", "variable": "temperature",
                "territory_id": "09", "period_start": "2020-01-01", "period_end": "2021-12-31",
            }])

    def test_no_internal_metadata_is_exposed_at_any_depth(self):
        forbidden = {
            "metadata", "provenance", "values", "records", "returned_count", "publication_id",
            "sha256", "dependencies", "depends_on", "analysis_config", "warnings", "diagnostics",
            "HAC_lags", "family_n_tests", "n_observations", "source_sha256",
        }

        def check(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for item in value.values():
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)

        for name in ("trends", "associations", "findings"):
            self.rewrite_artifact(name, lambda doc: doc["records"][0]["values"].update(
                diagnostics={"secret": "INTERNAL_ONLY"}, sha256="INTERNAL_ONLY"))
        # Recalcular aquí solo las dependencias del fixture sintético, no estadísticas.
        self.spec("findings")["depends_on"]["associations"] = self.spec("associations")["sha256"]
        with self.client() as client:
            requests = [
                ("/", {}), ("/health", {}), ("/api/catalogo", {}),
                ("/api/series", {"dataset": "weather"}),
                ("/api/tendencias", {"dataset": "trends"}),
                ("/api/asociaciones", {"dataset": "associations"}),
                ("/api/hallazgos", {"dataset": "findings"}),
            ]
            for path, params in requests:
                with self.subTest(path=path):
                    response = client.get(path, params=params)
                    self.assertEqual(response.status_code, 200)
                    check(response.json())
                    self.assertNotIn("INTERNAL_ONLY", response.text)
            schemas = client.get("/openapi.json").json()["components"]["schemas"]
            for name in ("Metadata", "Provenance", "SeriesDocument", "ResultDocument"):
                self.assertNotIn(name, schemas)

    def test_empty_result_filters_return_empty_lists(self):
        with self.client() as client:
            # Ambas dimensiones existen, pero esta combinación no tiene resultados.
            response = client.get("/api/tendencias", params={
                "dataset": "trends", "variable": "temperature", "territory_id": "09001",
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), [])

    def test_unadapted_result_is_rejected_instead_of_exposing_raw_values(self):
        self.rewrite_artifact("associations", lambda doc: doc["records"][0]["values"].update(type="not-supported"))
        with self.client() as client:
            with self.assertLogs("app.resultados.service", level="WARNING"):
                response = client.get("/api/asociaciones", params={"dataset": "associations"})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "unsupported_result")
            self.assertNotIn("values", response.json())

    def test_invalid_numeric_result_is_not_silently_served(self):
        self.rewrite_artifact("associations", lambda doc: doc["records"][0]["values"].update(coefficient=2))
        with self.client() as client:
            with self.assertLogs("app.resultados.service", level="WARNING"):
                response = client.get("/api/asociaciones", params={"dataset": "associations"})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "unsupported_result")

    def test_rate_ratio_without_a_direction_is_not_assumed_to_be_an_increase(self):
        self.rewrite_artifact("associations", lambda doc: doc["records"][2]["values"].pop("direction"))
        with self.client() as client, self.assertLogs("app.resultados.service", level="WARNING"):
            response = client.get("/api/asociaciones", params={"dataset": "associations"})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "unsupported_result")

    def test_grouping_separates_units_and_orders_points(self):
        self.points[1].update(unit="°F", value=32)
        self.points[1].pop("missing_reason")
        self.rewrite_artifact("weather", lambda doc: doc.update(records=list(reversed(self.points))))
        with self.client() as client:
            groups = client.get("/api/series", params={"dataset": "weather"}).json()
            self.assertEqual(len(groups), 2)
            self.assertEqual({group["unit"] for group in groups}, {"°C", "°F"})
        self.points[1]["unit"] = "°C"
        self.rewrite_artifact("weather", lambda doc: doc.update(records=list(reversed(self.points))))
        with self.client() as client:
            groups = client.get("/api/series", params={"dataset": "weather"}).json()
            self.assertEqual(len(groups), 1)
            self.assertEqual([point["start"] for point in groups[0]["points"]], ["2020-01-01", "2020-02-01"])

    def test_catalog_marks_unavailable_data_without_exposing_diagnostics(self):
        (self.root / "conaf.csv").unlink()
        with self.client() as client:
            catalog = {item["id"]: item for item in client.get("/api/catalogo").json()}
            self.assertFalse(catalog["joint"]["available"])
            self.assertTrue(catalog["weather"]["available"])
            self.assertNotIn("reasons", catalog["joint"])
            self.assertEqual(client.get("/health").json(), {"status": "degraded"})

    def test_invalid_query_parameters(self):
        cases = [
            ("series", {}),
            ("series", {"dataset": "weather", "start": "bad-date"}),
            ("series", {"dataset": "weather", "start": "2021-01-01", "end": "2020-01-01"}),
            ("series", {"dataset": "weather", "variable": ""}),
            ("series", {"dataset": "weather", "variable": "not-a-variable"}),
            ("series", {"dataset": "weather", "territory_id": "not-a-territory"}),
            ("series", {"dataset": "weather", "file": "/etc/passwd"}),
            ("tendencias", {"dataset": "trends", "start": "2020-01-01"}),
            ("tendencias", {"dataset": "weather"}),
        ]
        with self.client() as client:
            for endpoint, params in cases:
                with self.subTest(endpoint=endpoint, params=params):
                    response = client.get(f"/api/{endpoint}", params=params)
                    self.assertEqual(response.status_code, 422)
                    self.assertIn("error", response.json())
            self.assertEqual(client.get("/api/series", params={"dataset": "absent"}).status_code, 404)

    def test_conaf_change_invalidates_only_dependents(self):
        (self.root / "conaf.csv").write_text("synthetic\n2\n")
        with self.client() as client:
            self.assertEqual(self.statuses(client), {
                "weather": "ready", "trends": "ready", "joint": "stale",
                "associations": "stale", "findings": "stale",
            })
            self.assertEqual(client.get("/health").json()["status"], "degraded")
            for endpoint, dataset in [("series", "joint"), ("asociaciones", "associations"), ("hallazgos", "findings")]:
                response = client.get(f"/api/{endpoint}", params={"dataset": dataset})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], "dataset_stale")

    def test_updated_source_hash_does_not_revalidate_old_analysis(self):
        path = self.root / "conaf.csv"
        path.write_text("synthetic\n3\n")
        self.spec("conaf")["sha256"] = self.digest(path)
        with self.client() as client:
            self.assertEqual(self.statuses(client)["joint"], "stale")
            self.assertEqual(self.statuses(client)["findings"], "stale")

    def test_missing_source_propagates_unavailability(self):
        (self.root / "conaf.csv").unlink()
        with self.client() as client:
            states = self.statuses(client)
            self.assertEqual(states["associations"], "unavailable")
            self.assertEqual(states["weather"], "ready")

    def test_artifact_hash_mismatch_is_invalid(self):
        (self.root / "trends.json").write_text("{}")
        with self.client() as client:
            self.assertEqual(self.statuses(client)["trends"], "invalid")
            response = client.get("/api/tendencias", params={"dataset": "trends"})
            self.assertEqual(response.json()["error"]["code"], "dataset_invalid")

    def test_missing_artifact_is_not_an_empty_result(self):
        (self.root / "trends.json").unlink()
        with self.client() as client:
            self.assertEqual(self.statuses(client)["trends"], "unavailable")
            self.assertEqual(client.get("/api/tendencias", params={"dataset": "trends"}).status_code, 503)

    def test_invalid_data_contracts(self):
        cases = {
            "duplicate": lambda doc: doc["records"].append(copy.deepcopy(doc["records"][0])),
            "missing_reason": lambda doc: doc["records"][1].pop("missing_reason"),
            "nan": lambda doc: doc["metadata"]["reference"].update(value=float("nan")),
            "infinity": lambda doc: doc["metadata"]["reference"].update(value=float("inf")),
            "wrong_scale": lambda doc: doc["records"][0].update(time_scale="season"),
            "infinite_exponent": lambda doc: doc["metadata"]["reference"].update(value=1e309),
            "outside_period": lambda doc: doc["records"][0].update(period_start="2019-01-01"),
            "inverted_period": lambda doc: doc["records"][0].update(period_end="2019-01-01"),
        }
        original = (self.root / "weather.json").read_bytes()
        for name, edit in cases.items():
            with self.subTest(name=name):
                (self.root / "weather.json").write_bytes(original)
                self.rewrite_artifact("weather", edit)
                with self.client() as client:
                    self.assertEqual(self.statuses(client)["weather"], "invalid")

    def test_result_requires_method(self):
        self.rewrite_artifact("trends", lambda doc: doc["metadata"].update(method={}))
        with self.client() as client:
            self.assertEqual(self.statuses(client)["trends"], "invalid")

    def test_result_identifiers_must_be_unique(self):
        self.rewrite_artifact("trends", lambda doc: doc["records"].append(copy.deepcopy(doc["records"][0])))
        with self.client() as client:
            self.assertEqual(self.statuses(client)["trends"], "invalid")

    def test_artifact_cannot_depend_on_itself(self):
        self.spec("trends")["depends_on"]["trends"] = self.spec("trends")["sha256"]
        with self.client() as client:
            self.assertEqual(self.statuses(client)["trends"], "invalid")

    def test_json_overflow_and_duplicate_keys_are_rejected(self):
        for payload in (b'{"value":1e9999}', b'{"metadata": {}, "metadata": {}}'):
            with self.subTest(payload=payload):
                path = self.root / "weather.json"
                path.write_bytes(payload)
                self.spec("weather")["sha256"] = self.digest(path)
                with self.client() as client:
                    self.assertEqual(self.statuses(client)["weather"], "invalid")

    def test_paths_cannot_escape_publication(self):
        for path in ("../conaf.csv", "/etc/passwd"):
            with self.subTest(path=path):
                self.spec("conaf")["path"] = path
                with self.client() as client:
                    self.assertEqual(self.statuses(client)["joint"], "invalid")

    def test_symlink_cannot_escape_publication(self):
        link = self.root / "escape"
        link.symlink_to(self.root.parent, target_is_directory=True)
        self.spec("conaf")["path"] = "escape/anything.csv"
        with self.client() as client:
            self.assertEqual(self.statuses(client)["joint"], "invalid")

    def test_cycle_and_unknown_dependency(self):
        self.spec("joint")["depends_on"]["associations"] = self.spec("associations")["sha256"]
        self.spec("trends")["depends_on"]["absent"] = "0" * 64
        with self.client() as client:
            states = self.statuses(client)
            for key in ("joint", "associations", "findings", "trends"):
                self.assertEqual(states[key], "invalid")
            self.assertEqual(states["weather"], "ready")

    def test_duplicate_manifest_identifiers(self):
        self.manifest["sources"].append(copy.deepcopy(self.manifest["sources"][0]))
        with self.client() as client:
            self.assertEqual(client.get("/health").json(), {"status": "degraded"})
            self.assertIsNone(client.app.state.publication.manifest)

    def test_malformed_manifest_does_not_crash_service(self):
        for content in (b"not json", b'{"publication_id": "a", "publication_id": "b"}', b"[]"):
            with self.subTest(content=content):
                self.path.write_bytes(content)
                with TestClient(create_app(data_loader=lambda: load_publication(self.path))) as client:
                    self.assertEqual(client.get("/health").json()["status"], "degraded")

    def test_loaded_snapshot_is_stable_until_restart(self):
        with self.client() as client:
            before = client.get("/api/series", params={"dataset": "weather"}).json()
            (self.root / "weather.json").write_text("{}")
            (self.root / "conaf.csv").write_text("changed")
            self.assertEqual(client.get("/api/series", params={"dataset": "weather"}).json(), before)
            self.assertEqual(client.get("/health").json()["status"], "ok")
        with self.client() as client:
            self.assertEqual(self.statuses(client)["joint"], "stale")
            self.assertEqual(self.statuses(client)["weather"], "invalid")

    def test_new_valid_publication_is_activated_on_restart(self):
        with self.client() as client:
            self.assertEqual(client.app.state.publication.manifest.publication_id, "synthetic-1")
        (self.root / "conaf.csv").write_text("synthetic\n4\n")
        self.spec("conaf")["sha256"] = self.digest(self.root / "conaf.csv")
        self.spec("joint")["depends_on"]["conaf"] = self.spec("conaf")["sha256"]
        self.manifest["publication_id"] = "synthetic-2"
        with self.client() as client:
            self.assertEqual(client.get("/health").json()["status"], "ok")
            self.assertEqual(client.app.state.publication.manifest.publication_id, "synthetic-2")

    def test_default_configuration_does_not_require_a_manifest(self):
        with patch.dict("os.environ", {"DEHECHO_MANIFEST": "no-longer-used.json"}):
            settings = Settings()
            self.assertEqual(settings.project_root, Path(__file__).resolve().parents[1])
            with TestClient(create_app()) as client:
                self.assertEqual(client.get("/health").json(), {"status": "ok"})
                self.assertEqual(len(client.get("/api/catalogo").json()), 7)

    def test_season_is_not_disaggregated_to_months(self):
        def seasonal(doc):
            doc["metadata"]["time_scale"] = "season"
            doc["records"] = [dict(self.points[0], time_scale="season", unit="incendios",
                                   period_start="2020-07-01", period_end="2021-06-30", value=100)]
        self.rewrite_artifact("weather", seasonal)
        with self.client() as client:
            result = client.get("/api/series", params={
                "dataset": "weather", "start": "2020-12-01", "end": "2020-12-31",
            }).json()
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["frequency"], "season")
            self.assertEqual(result[0]["points"][0]["value"], 100)
            self.assertEqual(result[0]["points"][0]["end"], "2021-06-30")

    def test_group_null_is_preserved_internally_but_not_exposed_in_trends(self):
        self.rewrite_artifact("trends", lambda doc: doc["records"][0]["values"].update(high_activity=None))
        with self.client() as client:
            result = client.get("/api/tendencias", params={"dataset": "trends"}).json()
            self.assertNotIn("high_activity", result[0])
            self.assertIsNone(client.app.state.publication.documents["trends"].records[0].values["high_activity"])


if __name__ == "__main__":
    unittest.main()
