"""Resultados CONAF ya estimados: validación y adaptación, sin ajuste estadístico."""

import math
from collections import Counter, defaultdict
from datetime import date

from app.datos.adapters import hash_match, read_json
from app.datos.environment import CLEAN, DATA, csv_records, digest, month_bounds
from app.datos.models import Metadata, ResultDocument, ResultItem

REPORT = f"{CLEAN}/hallazgos_exploratorios.json"
MODEL = f"{CLEAN}/modelo_conaf_binomial_negativa.csv"
CONTEXT = f"{CLEAN}/incendios_contexto_mensual.csv"
DEFINITIVE = "definitivo.csv"
SOURCE_PATHS = {
    "region_mensual.csv": f"{DATA}/region_mensual.csv",
    "comunas_mensual.csv": f"{DATA}/comunas_mensual.csv",
    "infraestructura_vial_referencia_2019.csv": f"{DATA}/infraestructura_vial_referencia_2019.csv",
    "metadatos.json": f"{DATA}/metadatos.json",
    "conaf.csv": "data/conaf/conaf.csv",
    "conaf_comuna.csv": "data/conaf/conaf_comuna.csv",
}
INPUT_PATHS = (*SOURCE_PATHS.values(), REPORT, MODEL, CONTEXT, DEFINITIVE)
TERMS = {
    "heat": ("temperature_2m_c", 1),
    "rain_deficit": ("precipitation_mm", -1),
    "rh_deficit": ("relative_humidity_2m_pct", -1),
    "soil_deficit": ("soil_moisture_0_10cm_kgm2", -1),
}
MONTHS = {name: index for index, name in enumerate((
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
), 1)}


class StaleConafData(ValueError):
    """Las observaciones o salidas no corresponden al análisis publicado."""


def finite(value) -> float:
    if value is None or isinstance(value, bool) or value == "":
        raise ValueError("Falta un valor numérico explícito.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Se esperaba un número finito.")
    return result


def count(value) -> int:
    result = finite(value)
    if result < 0 or not result.is_integer():
        raise ValueError("Se esperaba un conteo entero no negativo.")
    return int(result)


def close(left, right) -> bool:
    return math.isclose(finite(left), finite(right), rel_tol=1e-12, abs_tol=1e-14)


def indexed(rows, key) -> dict:
    result = {}
    for row in rows:
        identifier = row[key]
        if identifier in result:
            raise ValueError(f"Clave duplicada: {identifier}")
        result[identifier] = row
    return result


class ConafAdapter:
    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.report = read_json(files[REPORT])
        self.followup = self.report["inferential_followup"]
        self.scope = self.report["scope"]
        self.audit = []
        self._verify_files()
        self.region_id = read_json(files[f"{DATA}/metadatos.json"])["geography"]["region_id"]
        if not isinstance(self.region_id, str):
            raise TypeError("El código regional debe conservar sus ceros iniciales.")
        self.start, _ = month_bounds(self.scope["fire_start"])
        _, self.end = month_bounds(self.scope["fire_end"])
        self.n = count(self.scope["fire_matched_months"])
        self.context = indexed(csv_records(files[CONTEXT]), "month")
        self._validate_cohort()
        self.coefficients = indexed(csv_records(files[MODEL]), "term")
        self.scales = indexed(self.followup["coefficient_scale"], "term")
        self._validate_coefficients()
        self._validate_sensitivity()

    def _verify(self, path, expected):
        match = hash_match(self.files[path], expected)
        if match == "mismatch":
            raise StaleConafData(f"{path} no corresponde al análisis CONAF; revisar o reejecutar.")
        self.audit.append({"file": path, "recorded_sha256": expected,
                           "actual_sha256": digest(self.files[path]), "match": match})

    def _verify_files(self):
        if set(self.report["source_sha256"]) != set(SOURCE_PATHS):
            raise ValueError("El reporte no declara todas las fuentes esperadas.")
        for name, path in SOURCE_PATHS.items():
            self._verify(path, self.report["source_sha256"][name])
        for output, path in ((self.followup["output"], MODEL), (self.report["event_context_output"], CONTEXT)):
            if output["file"] != path.rsplit("/", 1)[1]:
                raise ValueError("La salida declarada no corresponde al archivo esperado.")
            self._verify(path, output["sha256"])

    def _validate_cohort(self):
        if len(self.context) != self.n or count(self.report["event_context_output"]["rows"]) != self.n:
            raise ValueError("El contexto y el reporte no tienen la misma muestra.")
        months = set()
        current = self.start
        while current <= self.end:
            months.add(current.strftime("%Y-%m"))
            current = date(current.year + current.month // 12, current.month % 12 + 1, 1)
        if set(self.context) != months:
            raise ValueError("El contexto no tiene el calendario publicado completo.")

        fire = {}
        regional_totals = Counter()
        for row in csv_records(self.files[SOURCE_PATHS["conaf.csv"]]):
            first, last = map(int, row["temporada"].split("-"))
            if last != first + 1:
                raise ValueError("Temporada CONAF no válida.")
            month = MONTHS[row["mes"].strip().upper()]
            key = date(first + (month < 7), month, 1).strftime("%Y-%m")
            if key in fire:
                raise ValueError("Hay meses CONAF duplicados.")
            fire[key] = (count(row["IX"]), row["temporada"])
            regional_totals[row["temporada"]] += count(row["IX"])
        communal_totals = Counter()
        communal_keys = set()
        for row in csv_records(self.files[SOURCE_PATHS["conaf_comuna.csv"]]):
            key = (row["temporada"], row["comuna"])
            if key in communal_keys or row["region"] != "IX":
                raise ValueError("Las claves comunales CONAF no son válidas.")
            communal_keys.add(key)
            communal_totals[row["temporada"]] += count(row["numero_incendios"])
        commune_counts = Counter(season for season, _ in communal_keys)
        if any(total != count(self.scope["communes"]) for total in commune_counts.values()):
            raise ValueError("No están representadas todas las comunas de cada temporada.")
        reconciled = indexed(self.report["seasonal_totals_reconciled"], "temporada")
        expected_totals = {season: count(row["regional_count"]) for season, row in reconciled.items()}
        if any(count(row["regional_count"]) != count(row["communal_count"])
               for row in self.report["seasonal_totals_reconciled"]):
            raise ValueError("El reporte no concilia los totales regionales y comunales.")
        if dict(regional_totals) != dict(communal_totals) or dict(regional_totals) != expected_totals:
            raise StaleConafData("Los totales CONAF no corresponden al reporte.")

        zeros = 0
        for key, row in self.context.items():
            if key not in fire or (count(row["fire_count"]), row["conaf_season"]) != fire[key]:
                raise StaleConafData("Los conteos o temporadas del contexto no corresponden a CONAF.")
            zeros += count(row["fire_count"]) == 0
        self.zeros = zeros
        self.with_fire = self.n - zeros
        events, diagnostics = self.report["fire_event_contrasts"], self.followup["diagnostics"]
        if (count(events["without_recorded_fire"]) != zeros
                or count(events["with_recorded_fire"]) != self.with_fire
                or count(diagnostics["n_months"]) != self.n
                or count(diagnostics["zero_count_months"]) != zeros
                or diagnostics["converged"] is not True):
            raise ValueError("Las muestras del contexto, contrastes y modelo no coinciden.")

        definitive = {}
        for row in csv_records(self.files[DEFINITIVE]):
            day = date.fromisoformat(row["fecha"])
            if day.day != 1:
                raise ValueError("La fecha del cruce debe identificar el inicio de mes.")
            key = day.strftime("%Y-%m")
            if key in definitive:
                raise ValueError("Hay fechas duplicadas en definitivo.csv.")
            definitive[key] = row
        matched = {key for key in definitive if self.start <= month_bounds(key)[0] <= self.end}
        if matched != months:
            raise StaleConafData("definitivo.csv ya no contiene la cohorte publicada completa.")
        for key in months:
            row, context = definitive[key], self.context[key]
            if (count(row["IX"]) != count(context["fire_count"])
                    or row["temporada"] != context["conaf_season"]
                    or count(row["region_id"]) != int(self.region_id)):
                raise StaleConafData("El cruce definitivo no coincide con el contexto publicado.")
            for variable in self.report["event_context_output"]["units"]:
                if not close(row[variable], context[variable]):
                    raise StaleConafData(f"El ambiente de definitivo.csv difiere en {key}: {variable}.")

    def _validate_coefficients(self):
        published = indexed(self.followup["coefficients"], "term")
        if set(self.coefficients) != set(TERMS) or set(self.scales) != set(TERMS) or set(published) != set(TERMS):
            raise ValueError("Se esperaban los cuatro términos ambientales del modelo.")
        if count(self.followup["output"]["rows"]) != len(TERMS):
            raise ValueError("El reporte no declara cuatro coeficientes.")
        numeric = ("beta", "HAC_standard_error", "rate_ratio", "CI95_low", "CI95_high",
                   "p_asymptotic", "p_Holm_four_terms", "one_sd_original_units")
        for term, row in self.coefficients.items():
            scale, reference = self.scales[term], published[term]
            variable, direction = TERMS[term]
            if scale["variable"] != variable or isinstance(scale["direction"], bool) or scale["direction"] != direction:
                raise ValueError("La dirección o variable del efecto es incompatible.")
            if row["unit"] != reference["unit"] or row["unit"] != scale["unit"]:
                raise ValueError("Las unidades de los coeficientes no coinciden.")
            if row["label"] != reference["label"] or row["label"] != scale["label"]:
                raise ValueError("Las etiquetas de los coeficientes no coinciden.")
            if any(not close(row[key], reference[key]) for key in numeric):
                raise ValueError("Los coeficientes CSV y JSON no coinciden.")
            if not close(row["one_sd_original_units"], scale["one_sd_original_units"]):
                raise ValueError("La escala del efecto no coincide con el reporte.")
            ratio = finite(row["rate_ratio"])
            if not (0 < finite(row["CI95_low"]) <= ratio <= finite(row["CI95_high"])):
                raise ValueError("Intervalo de razón de tasas no válido.")
            if not close(math.log(ratio), row["beta"]):
                raise ValueError("La razón de tasas no corresponde al coeficiente.")
            if (finite(row["one_sd_original_units"]) <= 0 or finite(row["HAC_standard_error"]) <= 0
                    or not 0 <= finite(row["p_asymptotic"]) <= finite(row["p_Holm_four_terms"]) <= 1):
                raise ValueError("Escala, incertidumbre o p ajustado no válidos.")

    def _validate_sensitivity(self):
        variants = defaultdict(dict)
        for row in self.followup["sensitivity"]:
            key = (row["specification"], count(row["HAC_lags"]))
            term = row["term"]
            if term not in TERMS or key in variants[term]:
                raise ValueError("Términos o variantes de sensibilidad no válidos.")
            ratio, p = finite(row["rate_ratio"]), finite(row["p_Holm_four_terms"])
            if not (0 < finite(row["CI95_low"]) <= ratio <= finite(row["CI95_high"]) and 0 <= p <= 1):
                raise ValueError("Estadísticas de sensibilidad no válidas.")
            variants[term][key] = row
        keys = set(variants["heat"])
        if not keys or any(set(variants[term]) != keys for term in TERMS):
            raise ValueError("Las variables no tienen las mismas variantes de sensibilidad.")
        diagnostics = indexed(self.followup["sensitivity_diagnostics"], "specification")
        if set(diagnostics) != {spec for spec, _ in keys} - {"main_month_linear_time"}:
            raise ValueError("Los diagnósticos no describen todas las variantes examinadas.")
        if any(row["converged"] is not True or count(row["n"]) != self.n for row in diagnostics.values()):
            raise ValueError("Hay variantes sin convergencia o con otra muestra.")
        stable = set()
        for term in TERMS:
            rows = list(variants[term].values())
            if (all(finite(row["p_Holm_four_terms"]) < .05 for row in rows)
                    and (all(finite(row["rate_ratio"]) > 1 for row in rows)
                         or all(finite(row["rate_ratio"]) < 1 for row in rows))):
                stable.add(term)
            primary = variants[term][("main_month_linear_time", count(self.followup["primary_HAC"]["maxlags"]))]
            if any(not close(primary[key], self.coefficients[term][key])
                   for key in ("rate_ratio", "CI95_low", "CI95_high", "p_Holm_four_terms")):
                raise ValueError("La sensibilidad principal no coincide con los coeficientes.")
        if stable != set(self.followup["terms_supported_all_sensitivity_specifications"]):
            raise ValueError("La conclusión de estabilidad no corresponde a las variantes publicadas.")
        self.stable_terms = stable
        self.soil_year = variants["soil_deficit"][("month_year_fixed_effects", 4)]

    def _metadata(self):
        return Metadata(
            period_start=self.start, period_end=self.end, time_scale="month", n_observations=self.n,
            method={"type": "published_negative_binomial", "model": self.followup["primary_model"],
                    "HAC": self.followup["primary_HAC"], "multiplicity": self.followup["multiplicity"]},
            warnings=self.followup["limitations"],
        )

    def associations(self):
        records = []
        for term, (variable, direction) in TERMS.items():
            row = self.coefficients[term]
            records.append(ResultItem(
                id=term, variable=variable, territory_id=self.region_id,
                values={"type": "rate_ratio", "rate_ratio": finite(row["rate_ratio"]),
                        "increment": finite(row["one_sd_original_units"]),
                        "direction": "increase" if direction == 1 else "decrease", "unit": row["unit"],
                        "ci95_marginal_low": finite(row["CI95_low"]), "ci95_marginal_high": finite(row["CI95_high"]),
                        "p_holm": finite(row["p_Holm_four_terms"]), "n_used": self.n},
            ))
        return ResultDocument(metadata=self._metadata(), records=records)

    def findings(self):
        records = []
        for term, (variable, direction) in TERMS.items():
            row = self.coefficients[term]
            label = self.scales[term]["label"]
            p = finite(row["p_Holm_four_terms"])
            if p >= .05:
                title = f"{label}: evidencia independiente insuficiente"
                summary = (f"El modelo principal no respalda una asociación independiente tras Holm (p={p:.3g}). "
                           "Eso no demuestra ausencia de relación.")
            else:
                title = f"{label}: asociación ajustada"
                change = "aumento" if direction == 1 else "déficit adicional"
                summary = (f"Un {change} de {finite(row['one_sd_original_units']):.2f} {row['unit']} en la anomalía mensual "
                           f"se asocia con una razón de tasas de {finite(row['rate_ratio']):.2f}, condicionado al modelo.")
                if term in self.stable_terms:
                    title = f"{label}: asociación estable entre las variantes examinadas"
                    summary += " Conserva signo y evidencia en todas las variantes examinadas."
                elif term == "soil_deficit" and finite(self.soil_year["p_Holm_four_terms"]) >= .05:
                    title = "Suelo: asociación sensible al control temporal"
                    summary += (" Al controlar cada año por separado pierde evidencia "
                                f"(p Holm={finite(self.soil_year['p_Holm_four_terms']):.3g}).")
                else:
                    summary += " La evidencia no es estable entre todas las variantes examinadas."
            summary += " Asociación explicativa regional, no causalidad ni pronóstico."
            records.append(ResultItem(id=f"conaf:{term}", variable=variable, territory_id=self.region_id,
                                      values={"title": title, "summary": summary}))
        records.append(ResultItem(
            id="conaf:monthly_presence", territory_id=self.region_id,
            values={"title": "Presencia de incendios en la muestra regional",
                    "summary": f"De {self.n} meses, {self.with_fire} tienen incendios registrados y {self.zeros} tienen cero. "
                               "Son conteos regionales mensuales, no ubicaciones de ignición ni superficie quemada."},
        ))
        return ResultDocument(metadata=self._metadata(), records=records)
