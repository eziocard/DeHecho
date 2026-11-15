"""Exploración regional independiente; no cambia los resultados de la API.

Ejecutar: python3 scripts/explorar_valor.py
Solo biblioteca estándar. OLS con efectos de mes mediante Frisch–Waugh–Lovell;
varianza Newey–West Bartlett y corrección n/(n-k), como el notebook existente.
"""

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist, mean

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datos_mensuales_2014_2023/limpios"
OUT = ROOT / "docs/investigacion"
LAGS = (4, 8, 12, 18)
CORE = (
    "temperature_2m_c", "precipitation_mm", "relative_humidity_2m_pct",
    "soil_moisture_0_10cm_kgm2",
)
UNITS = {
    "temperature_2m_c": "°C",
    "precipitation_mm": "mm/mes",
    "relative_humidity_2m_pct": "puntos porcentuales",
    "soil_moisture_0_10cm_kgm2": "kg/m²",
    "dewpoint_2m_c": "°C",
    "specific_humidity_2m_kgkg": "kg/kg",
    "soil_temperature_0_10cm_c": "°C",
    "wind_speed_10m_ms": "m/s",
    "aod_550": "adimensional",
    "temperature_monthly_peak_area_mean_c": "°C",
    "temperature_monthly_max_c": "°C",
    "vpd_from_monthly_T_RH_kpa": "kPa; proxy de medias mensuales",
    "vpd_from_monthly_T_Td_kpa": "kPa; proxy de medias mensuales",
    "rh_from_monthly_T_Td_pct": "puntos porcentuales; diagnóstico",
}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def saturation_pressure(temp):
    return 0.6108 * math.exp(17.27 * temp / (temp + 237.3))


def fit(rows, variable, lag=12):
    """Pendiente por década; HAC usa distancias calendario incluso con huecos."""
    groups = defaultdict(list)
    for row in rows:
        groups[row["month"][5:]].append(row)
    xm = {m: mean(r["time"] / 120 for r in a) for m, a in groups.items()}
    ym = {m: mean(r[variable] for r in a) for m, a in groups.items()}
    x = [r["time"] / 120 - xm[r["month"][5:]] for r in rows]
    y = [r[variable] - ym[r["month"][5:]] for r in rows]
    ss = sum(v * v for v in x)
    beta = sum(a * b for a, b in zip(x, y)) / ss
    scores = {
        r["time"]: a * (b - beta * a) / ss
        for r, a, b in zip(rows, x, y)
    }
    variance = sum(v * v for v in scores.values())
    variance += 2 * sum(
        (1 - h / (lag + 1)) * sum(v * scores.get(t - h, 0) for t, v in scores.items())
        for h in range(1, lag + 1)
    )
    se = math.sqrt(variance * len(rows) / (len(rows) - len(groups) - 1))
    z95 = NormalDist().inv_cdf(0.975)
    return {
        "slope_per_decade": beta, "standard_error_per_decade": se,
        "CI95_low_per_decade": beta - z95 * se,
        "CI95_high_per_decade": beta + z95 * se,
        "p_raw": math.erfc(abs(beta / se) / math.sqrt(2)),
    }


def holm(pvalues):
    adjusted, previous = {}, 0.0
    for i, (key, value) in enumerate(sorted(pvalues.items(), key=lambda item: item[1])):
        previous = max(previous, min(1.0, value * (len(pvalues) - i)))
        adjusted[key] = previous
    return adjusted


def main():
    sources = [DATA / "region_mensual_limpio.csv", DATA / "tendencias_ambientales_2014_2023.csv"]
    rows = read_csv(sources[0])
    assert len(rows) == 120 and len({r["month"] for r in rows}) == 120
    for row in rows:
        for key in set(UNITS) - {"vpd_from_monthly_T_RH_kpa", "vpd_from_monthly_T_Td_kpa", "rh_from_monthly_T_Td_pct"}:
            row[key] = float(row[key])
            assert math.isfinite(row[key])
        assert float(row["suelo_mensual_valid_area_pct"]) >= 80
        row["time"] = int(row["month"][:4]) * 12 + int(row["month"][5:]) - 1
        et = saturation_pressure(row["temperature_2m_c"])
        ed = saturation_pressure(row["dewpoint_2m_c"])
        row["vpd_from_monthly_T_RH_kpa"] = et * (1 - row["relative_humidity_2m_pct"] / 100)
        row["vpd_from_monthly_T_Td_kpa"] = et - ed
        row["rh_from_monthly_T_Td_pct"] = 100 * ed / et
    assert [r["time"] for r in rows] == list(range(2014 * 12, 2024 * 12))

    estimates = {lag: {key: fit(rows, key, lag) for key in UNITS} for lag in LAGS}
    for lag, family in estimates.items():
        adjusted = holm({key: result["p_raw"] for key, result in family.items()})
        for key, result in family.items():
            result["p_holm_14"] = adjusted[key]

    # Comparación independiente con los cuatro ajustes publicados, sin reescribirlos.
    published = {r["variable"]: r for r in read_csv(sources[1]) if r["geography_level"] == "region"}
    for key in CORE:
        for field in ("slope_per_decade", "standard_error_per_decade", "CI95_low_per_decade", "CI95_high_per_decade", "p_raw"):
            assert math.isclose(estimates[12][key][field], float(published[key][field]), rel_tol=1e-6, abs_tol=1e-12), (key, field)
    original_holm = holm({key: estimates[12][key]["p_raw"] for key in CORE})
    assert all(math.isclose(original_holm[key], float(published[key]["p_holm"]), rel_tol=1e-6, abs_tol=1e-12) for key in CORE)

    results = []
    for key, unit in UNITS.items():
        omitted = {str(year): fit([r for r in rows if not r["month"].startswith(str(year))], key)["slope_per_decade"] for year in range(2014, 2024)}
        halves = {"2014-2018": fit(rows[:60], key)["slope_per_decade"], "2019-2023": fit(rows[60:], key)["slope_per_decade"]}
        results.append({
            "variable": key, "unit": unit, "n": 120,
            **estimates[12][key],
            "p_holm_14_by_HAC_lag": {str(lag): estimates[lag][key]["p_holm_14"] for lag in LAGS},
            "supported_all_HAC_lags": all(estimates[lag][key]["p_holm_14"] < 0.05 for lag in LAGS),
            "omit_year_slopes": omitted, "half_period_slopes_descriptive_only": halves,
        })
    inventory = []
    for path in sorted((ROOT / "data/giovanni").glob("*.csv")):
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("time,"))
        series = list(csv.reader(lines[start + 1:]))
        inventory.append({"file": path.name, "n": len(series), "start": series[0][0], "end": series[-1][0], "selection": next(line for line in lines if line.startswith("URL to Reproduce")), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    payload = {
        "status": "exploratory_not_published_to_API", "period": "2014-01/2023-12",
        "geography": "La Araucanía, región 09; no nuevas inferencias comunales",
        "model": "OLS: 12 interceptos mensuales y tiempo en décadas; HAC Bartlett, n/(n-13), normal asintótica; principal 12 meses",
        "multiplicity": "Holm sobre las 14 series regionales examinadas, por cada ventana HAC; familia distinta de la publicación original",
        "derived_definitions": {"es": "0.6108 * exp(17.27*T/(T+237.3)) kPa", "vpd_T_RH": "es(T)*(1-RH/100)", "vpd_T_Td": "es(T)-es(Td)", "rh_T_Td": "100*es(Td)/es(T)"},
        "limitations": ["Exploración posterior a observar los datos, sin confirmación independiente.", "VPD calculado DESPUÉS de promediar tiempo y espacio: proxy, no promedio verdadero ni extremo diario.", "Series derivadas y POWER/MERRA-2 comparten información; no validaciones independientes.", "HAC no corrige sesgos de fuente, confusión ni cambios de régimen.", "División 2019 ilustrativa: no prueba de quiebre ni elección de período por significación."],
        "checks": {"published_four_slopes_SE_CI_p_and_Holm_reproduced": True, "continuous_months": 120},
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "results": results, "giovanni_inventory": inventory,
    }
    OUT.mkdir(exist_ok=True, parents=True)
    (OUT / "exploracion_regional.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    fields = ["variable", "unit", "n", "slope_per_decade", "CI95_low_per_decade", "CI95_high_per_decade", "p_holm_14", "supported_all_HAC_lags"]
    with (OUT / "exploracion_regional.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print("Verificados cuatro resultados publicados; exportadas 14 exploraciones regionales.")
    for result in results:
        print(result["variable"], f'{result["slope_per_decade"]:.6g}', f'p Holm14={result["p_holm_14"]:.4g}')


if __name__ == "__main__":
    main()
