"""Adaptación en memoria de series limpias y tendencias existentes, sin estimación."""

import calendar
import csv
import hashlib
import io
import math
from datetime import date
from pathlib import PurePosixPath

from app.datos.adapters import read_json
from app.datos.models import (
    Metadata,
    ResultDocument,
    ResultItem,
    SeriesDocument,
    SeriesPoint,
)

DATA = "datos_mensuales_2014_2023"
CLEAN = f"{DATA}/limpios"
VALIDATION = f"{CLEAN}/reporte_validacion.json"
TRENDS_REPORT = f"{CLEAN}/reporte_tendencias.json"
TRENDS_CSV = f"{CLEAN}/tendencias_ambientales_2014_2023.csv"
INPUT_PATHS = (
    f"{DATA}/region_mensual.csv",
    f"{DATA}/comunas_mensual.csv",
    f"{DATA}/infraestructura_vial_referencia_2019.csv",
    f"{DATA}/metadatos.json",
    f"{CLEAN}/region_mensual_limpio.csv",
    f"{CLEAN}/comunas_mensual_limpio.csv",
    f"{CLEAN}/infraestructura_vial_limpia.csv",
    VALIDATION,
    TRENDS_CSV,
    TRENDS_REPORT,
)
COVERAGE = {
    "temperature_2m_c": "meteorologia_mensual_valid_area_pct",
    "precipitation_mm": "precipitacion_mensual_valid_area_pct",
    "relative_humidity_2m_pct": None,
    "soil_moisture_0_10cm_kgm2": "suelo_mensual_valid_area_pct",
}


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def csv_records(content: bytes) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""))
    headers = reader.fieldnames
    if not headers or len(headers) != len(set(headers)):
        raise ValueError("El CSV no tiene cabeceras únicas.")
    rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("El CSV contiene filas con un número incorrecto de columnas.")
    return rows


def number(value: str) -> float | None:
    if value == "":
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Las mediciones y estadísticas deben ser finitas o estar vacías.")
    return result


def boolean(value: str) -> bool:
    if value not in ("True", "False"):
        raise ValueError("Se esperaba un indicador True/False explícito.")
    return value == "True"


def month_bounds(value: str) -> tuple[date, date]:
    start = date.fromisoformat(f"{value}-01")
    return start, start.replace(day=calendar.monthrange(start.year, start.month)[1])


class EnvironmentAdapter:
    """Verifica y adapta una misma captura de bytes.

    Con strict=False acumula errores por fuente; el cargador debe bloquear sus dependientes.
    """

    def __init__(self, files: dict[str, bytes], *, strict: bool = True):
        self.files = files
        self.strict = strict
        self.verification_errors: dict[str, str] = {}
        self.validation = read_json(files[VALIDATION])
        self.trends = read_json(files[TRENDS_REPORT])
        self.source_metadata = read_json(files[f"{DATA}/metadatos.json"])
        self.audit: list[dict] = []
        self._verify_reports()
        self.variables = self.trends["units"]
        if set(self.variables) != set(COVERAGE):
            raise ValueError("El adaptador ambiental espera las cuatro variables publicadas.")
        if not self.validation["all_checks_passed"]:
            raise ValueError("La validación ambiental original contiene controles fallidos.")
        if not self.trends["scope"]["independent_of_CONAF_join"]:
            raise ValueError("Las tendencias ambientales no deben depender de CONAF.")
        if any(units["observations"] != self.validation["units"][variable]
               for variable, units in self.variables.items()):
            raise ValueError("Las unidades de tendencias y validación ambiental no coinciden.")
        if any(self.trends["scope"][key] != self.validation["scope"][key] for key in ("start", "end", "communes")):
            raise ValueError("Los reportes no describen el mismo alcance ambiental.")
        if self.trends["data_quality"]["soil_minimum_spatial_coverage_pct"] != self.validation["soil_coverage_threshold_pct"]:
            raise ValueError("Los reportes no usan el mismo umbral de cobertura de suelo.")

    def _verify(self, path: str, expected: str, report: str) -> None:
        # Los reportes históricos pueden tener rutas Windows y hashes CRLF.
        path = str(PurePosixPath(path.replace("\\", "/")))
        if path not in INPUT_PATHS:
            raise ValueError(f"Dependencia no reconocida en {report}: {path}")
        if path not in self.files:
            message = f"No se pudo leer {path}, requerido por {report}."
            self.verification_errors[path] = message
            self.audit.append({"report": report, "file": path, "recorded_sha256": expected,
                               "actual_sha256": None, "match": "unavailable"})
            if self.strict:
                raise ValueError(message)
            return
        content = self.files[path]
        actual = digest(content)
        if actual == expected:
            match = "exact"
        else:
            lf = content.replace(b"\r\n", b"\n")
            if expected not in (digest(lf), digest(lf.replace(b"\n", b"\r\n"))):
                message = f"La huella de {path} no corresponde a {report}; revisar o reejecutar el análisis."
                self.verification_errors[path] = message
                if self.strict:
                    raise ValueError(message)
                match = "mismatch"
            else:
                match = "line_endings_only"
        self.audit.append({
            "report": report, "file": path, "recorded_sha256": expected,
            "actual_sha256": actual, "match": match,
        })

    def _verify_reports(self) -> None:
        for name, expected in self.validation["source_sha256"].items():
            self._verify(f"{DATA}/{name}", expected, VALIDATION)
        for name, output in self.validation["outputs"].items():
            self._verify(f"{CLEAN}/{name}", output["sha256"], VALIDATION)
        for path, expected in self.trends["source_sha256"].items():
            self._verify(path, expected, TRENDS_REPORT)
        output = self.trends["output"]
        if output["file"] != PurePosixPath(TRENDS_CSV).name:
            raise ValueError("La salida declarada no corresponde al CSV de tendencias.")
        self._verify(TRENDS_CSV, output["sha256"], TRENDS_REPORT)
        verified = {item["file"] for item in self.audit}
        if set(INPUT_PATHS) - {TRENDS_REPORT} != verified:
            raise ValueError("Los reportes no verifican todas las entradas ambientales.")

    def _metadata(self, *, trends: bool = False) -> Metadata:
        scope = self.trends["scope"]
        start, _ = month_bounds(scope["start"])
        _, end = month_bounds(scope["end"])
        method = {
            "type": "published_observations",
            "sample_unit": "months per territory and variable",
            "soil_coverage_threshold_pct": self.validation["soil_coverage_threshold_pct"],
            "variables": self.variables,
            "aggregation": "Valores mensuales publicados, sin reagregación ni imputación.",
        }
        if trends:
            method = {key: value for key, value in self.trends.items() if key not in {
                "scope", "source_sha256", "output", "regional_results", "limitations",
            }}
        return Metadata(
            period_start=start, period_end=end, time_scale="month",
            n_observations=scope["environmental_months"],
            warnings=self.trends["limitations"],
            reference={"start": scope["start"], "end": scope["end"],
                       "type": "environmental_observation_window", "climate_normal": False},
            method=method,
        )

    def series(self, level: str) -> SeriesDocument:
        if level not in ("region", "commune"):
            raise ValueError("Nivel territorial no compatible.")
        filename = "region_mensual_limpio.csv" if level == "region" else "comunas_mensual_limpio.csv"
        rows = csv_records(self.files[f"{CLEAN}/{filename}"])
        id_column = "region_id" if level == "region" else "commune_id"
        name_column = "region_name" if level == "region" else "commune_name"
        scope = self.trends["scope"]
        threshold = self.validation["soil_coverage_threshold_pct"]
        records = []
        calendars: dict[str, set[str]] = {}
        for row in rows:
            identifier = row[id_column]
            valid_code = identifier == self.source_metadata["geography"]["region_id"] if level == "region" else (
                len(identifier) == 5 and identifier.isdigit()
                and identifier.startswith(self.source_metadata["geography"]["region_id"])
            )
            if not valid_code:
                raise ValueError("Código territorial ambiental no válido; conservar ceros iniciales.")
            months = calendars.setdefault(identifier, set())
            if row["month"] in months:
                raise ValueError("Hay meses duplicados por territorio.")
            months.add(row["month"])
            start, end = month_bounds(row["month"])
            for variable, units in self.variables.items():
                value = number(row[variable])
                reason = "missing_measurement" if value is None else None
                column = COVERAGE[variable]
                coverage = number(row[column]) if column else None
                if coverage is not None and not 0 <= coverage <= 100:
                    raise ValueError("La cobertura espacial debe estar entre 0 y 100.")
                metadata = {"territory_name": row[name_column], "coverage_pct": coverage}
                if variable == "soil_moisture_0_10cm_kgm2":
                    usable = boolean(row["soil_coverage_ok"])
                    if coverage is None or usable != (coverage >= threshold):
                        raise ValueError("El indicador de calidad de suelo no corresponde a su cobertura.")
                    metadata["soil_coverage_ok"] = usable
                    if not usable:
                        value, reason = None, "insufficient_coverage"
                records.append(SeriesPoint(
                    variable=variable, territory_id=identifier, geography_level=level,
                    time_scale="month", period_start=start, period_end=end,
                    unit=units["observations"], value=value, missing_reason=reason,
                    metadata=metadata,
                ))
        expected_territories = 1 if level == "region" else scope["communes"]
        first, _ = month_bounds(scope["start"])
        last, _ = month_bounds(scope["end"])
        expected_months = set()
        current = first
        while current <= last:
            expected_months.add(current.strftime("%Y-%m"))
            current = date(current.year + current.month // 12, current.month % 12 + 1, 1)
        if len(expected_months) != scope["environmental_months"] or len(calendars) != expected_territories:
            raise ValueError("La cobertura temporal o territorial no coincide con el reporte.")
        if any(months != expected_months for months in calendars.values()):
            raise ValueError("Hay meses faltantes o fuera del calendario publicado.")
        return SeriesDocument(metadata=self._metadata(), records=records)

    def trend_results(self) -> ResultDocument:
        rows = csv_records(self.files[TRENDS_CSV])
        if len(rows) != self.trends["scope"]["candidate_rows"]:
            raise ValueError("El número de tendencias no coincide con su reporte.")
        info = {"geography_level", "territory_name", "variable_label", "native_unit",
                "rate_unit", "period_start", "period_end"}
        text = info | {"variable", "territory_id", "status", "exclusion_reason", "direction"}
        integers = {"n_expected", "n_measurements", "n_used", "residual_df", "HAC_lags", "family_n_tests"}
        records = []
        for row in rows:
            values = {}
            for key, value in row.items():
                if key in text:
                    values[key] = value if value != "" else None
                elif key == "evidence_all_bandwidths":
                    values[key] = boolean(value) if value else None
                else:
                    numeric = number(value)
                    if key in integers and numeric is not None:
                        if not numeric.is_integer():
                            raise ValueError(f"El campo {key} debe ser entero.")
                        numeric = int(numeric)
                    values[key] = numeric
            records.append(ResultItem(
                id=f"{row['geography_level']}:{row['territory_id']}:{row['variable']}",
                variable=row["variable"], territory_id=row["territory_id"],
                values={key: value for key, value in values.items() if key not in info | {"variable", "territory_id"}},
                metadata={key: values[key] for key in sorted(info)},
            ))
        return ResultDocument(metadata=self._metadata(trends=True), records=records)
