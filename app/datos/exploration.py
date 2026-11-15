"""Adapta la investigación existente sin mover archivos ni recalcular inferencias."""

import math

from app.datos.adapters import hash_match, read_json
from app.datos.environment import CLEAN, csv_records, digest, month_bounds
from app.datos.models import Metadata, ResultDocument, ResultItem

REPORT = "docs/investigacion/exploracion_regional.json"
TABLE = "docs/investigacion/exploracion_regional.csv"
REGION = f"{CLEAN}/region_mensual_limpio.csv"
PUBLISHED_TRENDS = f"{CLEAN}/tendencias_ambientales_2014_2023.csv"
INPUT_PATHS = (REPORT, TABLE, REGION, PUBLISHED_TRENDS)
LAGS = (4, 8, 12, 18)
GEOGRAPHY = "La Araucanía, región 09; no nuevas inferencias comunales"
MODEL = "OLS: 12 interceptos mensuales y tiempo en décadas; HAC Bartlett, n/(n-13), normal asintótica; principal 12 meses"
MULTIPLICITY = "Holm sobre las 14 series regionales examinadas, por cada ventana HAC; familia distinta de la publicación original"
DERIVED_DEFINITIONS = {
    "es": "0.6108 * exp(17.27*T/(T+237.3)) kPa",
    "vpd_T_RH": "es(T)*(1-RH/100)",
    "vpd_T_Td": "es(T)-es(Td)",
    "rh_T_Td": "100*es(Td)/es(T)",
}
# Unidad del archivo y unidad de la pendiente pública. No se convierten las mediciones.
UNITS = {
    "temperature_2m_c": ("°C", "°C/década"),
    "precipitation_mm": ("mm/mes", "mm/mes por década"),
    "relative_humidity_2m_pct": ("puntos porcentuales", "puntos porcentuales/década"),
    "soil_moisture_0_10cm_kgm2": ("kg/m²", "kg/m²/década"),
    "dewpoint_2m_c": ("°C", "°C/década"),
    "specific_humidity_2m_kgkg": ("kg/kg", "kg/kg por década"),
    "soil_temperature_0_10cm_c": ("°C", "°C/década"),
    "wind_speed_10m_ms": ("m/s", "m/s por década"),
    "aod_550": ("adimensional", "adimensional por década"),
    "temperature_monthly_peak_area_mean_c": ("°C", "°C/década"),
    "temperature_monthly_max_c": ("°C", "°C/década"),
    "vpd_from_monthly_T_RH_kpa": ("kPa; proxy de medias mensuales", "kPa/década"),
    "vpd_from_monthly_T_Td_kpa": ("kPa; proxy de medias mensuales", "kPa/década"),
    "rh_from_monthly_T_Td_pct": ("puntos porcentuales; diagnóstico", "puntos porcentuales/década"),
}
CORE = ("temperature_2m_c", "precipitation_mm", "relative_humidity_2m_pct", "soil_moisture_0_10cm_kgm2")


class StaleExplorationData(ValueError):
    """La investigación no corresponde a las fuentes actuales."""


def numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Las estimaciones deben ser números finitos explícitos.")
    return value


class ExplorationAdapter:
    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.report = read_json(files[REPORT])
        self.audit = []
        self._verify_sources()
        self.start, _ = month_bounds("2014-01")
        _, self.end = month_bounds("2023-12")
        self._validate_scope()
        self.results = {}
        for row in self.report["results"]:
            variable = row["variable"]
            if variable not in UNITS or variable in self.results:
                raise ValueError("Hay variables desconocidas o duplicadas en la exploración.")
            self._validate_result(row)
            self.results[variable] = row
        if set(self.results) != set(UNITS):
            raise ValueError("Se requieren las 14 series de la familia exploratoria completa.")
        self._validate_table()
        self._validate_published_results()

    def _verify_sources(self):
        if set(self.report["source_sha256"]) != {REGION, PUBLISHED_TRENDS}:
            raise ValueError("La investigación no declara las dos fuentes esperadas.")
        for path, expected in self.report["source_sha256"].items():
            match = hash_match(self.files[path], expected)
            if match == "mismatch":
                raise StaleExplorationData(f"La investigación no corresponde a {path}; revisar o regenerar sus resultados.")
            self.audit.append({"file": path, "recorded_sha256": expected,
                               "actual_sha256": digest(self.files[path]), "match": match})

    def _validate_scope(self):
        # Se conserva el marcador histórico de los archivos; no se modifica la investigación.
        if self.report["status"] not in {"exploratory_not_published_to_API", "exploratory"}:
            raise ValueError("El análisis debe seguir identificado como exploratorio.")
        if self.report["period"] != "2014-01/2023-12":
            raise ValueError("El período exploratorio esperado es 2014–2023.")
        if self.report["geography"] != GEOGRAPHY:
            raise ValueError("La exploración debe ser regional, sin nuevas inferencias comunales.")
        if self.report["model"] != MODEL or self.report["multiplicity"] != MULTIPLICITY:
            raise ValueError("El análisis no corresponde al método y familia exploratorios admitidos.")
        if self.report["derived_definitions"] != DERIVED_DEFINITIONS:
            raise ValueError("Las definiciones de los proxies no corresponden a la exploración admitida.")
        rows = csv_records(self.files[REGION])
        months = {f"{year}-{month:02d}" for year in range(2014, 2024) for month in range(1, 13)}
        if (len(rows) != 120 or {row["month"] for row in rows} != months
                or any(row["region_id"] != "09" for row in rows)):
            raise ValueError("La fuente debe contener 120 meses de la región 09, sin duplicados.")

    def _validate_result(self, row):
        variable = row["variable"]
        if row["unit"] != UNITS[variable][0] or type(row["n"]) is not int or row["n"] != 120:
            raise ValueError("Las unidades o la muestra no corresponden a la exploración.")
        slope = numeric(row["slope_per_decade"])
        low, high = numeric(row["CI95_low_per_decade"]), numeric(row["CI95_high_per_decade"])
        p, adjusted = numeric(row["p_raw"]), numeric(row["p_holm_14"])
        if not (low <= slope <= high and numeric(row["standard_error_per_decade"]) > 0 and 0 <= p <= adjusted <= 1):
            raise ValueError("Intervalos, incertidumbre o valores p no válidos.")
        bands = row["p_holm_14_by_HAC_lag"]
        if set(bands) != {str(lag) for lag in LAGS} or any(not 0 <= numeric(value) <= 1 for value in bands.values()):
            raise ValueError("La sensibilidad debe contener las cuatro ventanas HAC originales.")
        if bands["12"] != adjusted:
            raise ValueError("La sensibilidad HAC12 no coincide con la inferencia principal.")
        stable = row["supported_all_HAC_lags"]
        if type(stable) is not bool or stable != all(value < .05 for value in bands.values()):
            raise ValueError("El indicador de sensibilidad no coincide con los valores publicados.")

    def _validate_table(self):
        rows = csv_records(self.files[TABLE])
        if len(rows) != 14 or len({row["variable"] for row in rows}) != 14:
            raise ValueError("El CSV debe contener las 14 series sin duplicados.")
        for row in rows:
            source = self.results[row["variable"]]
            if row["unit"] != source["unit"] or float(row["n"]) != source["n"]:
                raise ValueError("Las unidades o muestras CSV/JSON no coinciden.")
            for field in ("slope_per_decade", "CI95_low_per_decade", "CI95_high_per_decade", "p_holm_14"):
                if float(row[field]) != source[field]:
                    raise ValueError("Las estimaciones CSV/JSON no coinciden.")
            if row["supported_all_HAC_lags"] not in ("True", "False"):
                raise ValueError("El CSV no tiene indicadores de sensibilidad válidos.")
            if (row["supported_all_HAC_lags"] == "True") != source["supported_all_HAC_lags"]:
                raise ValueError("La sensibilidad CSV/JSON no coincide.")

    def _validate_published_results(self):
        rows = [row for row in csv_records(self.files[PUBLISHED_TRENDS]) if row["geography_level"] == "region"]
        if len(rows) != 4 or {row["variable"] for row in rows} != set(CORE):
            raise ValueError("Faltan los cuatro resultados regionales publicados de referencia.")
        for row in rows:
            result = self.results[row["variable"]]
            if row["territory_id"] != "09" or row["period_start"] != "2014-01" or row["period_end"] != "2023-12":
                raise ValueError("Las tendencias de referencia tienen otro territorio o período.")
            for field in ("slope_per_decade", "standard_error_per_decade", "CI95_low_per_decade", "CI95_high_per_decade", "p_raw"):
                if not math.isclose(result[field], float(row[field]), rel_tol=1e-9, abs_tol=1e-12):
                    raise ValueError("La exploración no reproduce los ajustes regionales publicados.")
            # p_holm no se compara: las familias de cuatro y catorce pruebas son distintas.

    def _metadata(self):
        return Metadata(
            period_start=self.start, period_end=self.end, time_scale="month", n_observations=120,
            method={"exploratory": True, "model": self.report["model"], "multiplicity": self.report["multiplicity"],
                    "family_n_tests": 14, "HAC_lags": 12, "sensitivity_HAC_lags": list(LAGS)},
            warnings=self.report["limitations"],
        )

    def trends(self):
        records = []
        for variable, row in self.results.items():
            slope = row["slope_per_decade"]
            state = "uncertain_trend"
            if row["p_holm_14"] < .05:
                state = "evidence_increasing" if slope > 0 else "evidence_decreasing"
            records.append(ResultItem(
                id=f"exploratory:09:{variable}", variable=variable, territory_id="09",
                values={"slope_per_decade": slope, "CI95_low_per_decade": row["CI95_low_per_decade"],
                        "CI95_high_per_decade": row["CI95_high_per_decade"], "p_holm": row["p_holm_14"],
                        "status": state, "n_used": row["n"], "family_n_tests": 14},
                metadata={"geography_level": "region", "rate_unit": UNITS[variable][1]},
            ))
        return ResultDocument(metadata=self._metadata(), records=records)

    def findings(self):
        definitions = {
            "temperature_monthly_peak_area_mean_c": (
                "picos térmicos mensuales",
                "Es el promedio espacial de picos mensuales de píxeles, no días de ola de calor. "
                "No se probó formalmente la diferencia entre su pendiente y la de temperatura media.",
            ),
            "dewpoint_2m_c": (
                "punto de rocío",
                "Es una señal compatible con cambios del contenido de vapor. Comparte información de origen "
                "con otras variables y no demuestra por sí sola la causa del cambio de humedad relativa.",
            ),
            "specific_humidity_2m_kgkg": (
                "humedad específica",
                "Comparte información de origen con otras variables de humedad; no es una confirmación independiente.",
            ),
            "vpd_from_monthly_T_RH_kpa": (
                "proxy VPD con temperatura y humedad relativa",
                "Se calcula con medias mensuales y espaciales: no es el VPD medio verdadero ni un extremo diario. "
                "No se evaluó su asociación ajustada con CONAF.",
            ),
            "vpd_from_monthly_T_Td_kpa": (
                "proxy VPD con temperatura y punto de rocío",
                "Se calcula con medias mensuales y espaciales: no es el VPD medio verdadero ni un extremo diario. "
                "No aporta una validación independiente del otro proxy ni una asociación ajustada con CONAF.",
            ),
        }
        records = []
        for variable, (label, explanation) in definitions.items():
            row = self.results[variable]
            slope, unit = row["slope_per_decade"], UNITS[variable][1]
            if variable == "specific_humidity_2m_kgkg":
                slope, unit = slope * 1000, "g/kg por década"
            evidence = "con evidencia" if row["p_holm_14"] < .05 else "sin evidencia suficiente"
            summary = f"Pendiente regional estimada: {slope:+.3g} {unit}, {evidence} tras Holm sobre 14 series. "
            if variable == "temperature_monthly_peak_area_mean_c" and self.results["temperature_2m_c"]["p_holm_14"] >= .05:
                summary += "La temperatura media no alcanza evidencia en este análisis. "
            summary += explanation + " Resultado exploratorio de 2014–2023, no causalidad ni pronóstico."
            records.append(ResultItem(
                id=f"environmental:{variable}", variable=variable, territory_id="09",
                values={"title": f"Exploratorio: {label}", "summary": summary},
            ))
        return ResultDocument(metadata=self._metadata(), records=records)
