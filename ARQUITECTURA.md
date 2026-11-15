# Statistical Explorer Architecture

## Approach

**Existing files → validation and in-memory loading → FastAPI queries → JSON responses.**

The service exposes existing time series and precomputed analyses. No database, microservices, or per-request notebook execution are needed. The separate [frontend repository](https://github.com/maiki-22/low-poly-studio) contains the presentation interface using **Blockbench** assets; API integration will be defined separately.

At startup, the project's CSV and JSON inputs are captured once and checked against their reports. Environmental, CONAF, and exploratory loaders are independent. No publication artifacts or additional configuration are required. Source changes invalidate affected results; analyses are rerun outside the API, and the service must be restarted to load updated files. See the [README](README.md) for usage.

## Inputs

In `datos_mensuales_2014_2023/limpios/`:

| Files | Purpose |
| --- | --- |
| `region_mensual_limpio.csv`, `comunas_mensual_limpio.csv` | Environmental time series. |
| `incendios_contexto_mensual.csv` | Joint regional context, anomalies, and antecedent conditions. |
| `tendencias_ambientales_2014_2023.csv`, `reporte_tendencias.json` | Trends, evidence, and methods. |
| `modelo_conaf_binomial_negativa.csv`, `hallazgos_exploratorios.json` | Associations, explanatory model, episodes, and sensitivity. |
| `reporte_validacion.json` | Quality rules and warnings. |

These are supplemented by `metadatos.json` in the parent directory and the sources in `data/conaf/`. `definitivo.csv` is reconciled with the monthly context over the published period: it is an existing regional join, not an additional source of observations.

`docs/investigacion/exploracion_regional.csv` and `.json` are read in place, without modification. They provide 14 exploratory regional trends and five summaries, validated against each other and the two recorded clean source files. No series are extended and no monthly proxies are calculated.

## Modules

| Module | Responsibility |
| --- | --- |
| `datos` | Read files, validate dates and codes, apply quality rules, and preserve provenance. Never modify sources. |
| `consultas` | Filter series and prepare summaries consistent with their temporal scale. |
| `resultados` | Read published results and expose only the necessary scientific fields, without recalculation. |
| `api` | Validate parameters with Pydantic and expose minimal results through FastAPI; keep audit records and methods internal. |

Loading uses CSV/JSON files and Pydantic validation. SciPy and statsmodels belong to the estimation workflow, outside the inspector's request handling.

## Endpoints

- `GET /health`: service status and overall availability only.
- `GET /api/catalogo`: datasets, availability, variables, units, and territories.
- `GET /api/series`: values and context by variable, territory, and period.
- `GET /api/tendencias`: original estimates (`tendencias_ambientales`) and exploratory regional estimates (`tendencias_regionales_exploratorias`) for 2014–2023.
- `GET /api/asociaciones`: four adjusted rate ratios (`asociaciones_conaf`); correlations and group comparisons are deferred.
- `GET /api/hallazgos`: five CONAF summaries (`hallazgos_conaf`) and five exploratory environmental summaries (`hallazgos_ambientales`).

Data queries return **lists of results without technical metadata**. Series group data points; trends provide slopes and evidence; associations include rate ratios, marginal confidence intervals, Holm-adjusted p-values, sample size, and direction of environmental change. Missing values retain their reason. Sources, methods, hashes, and diagnostics remain internal, with no separate metadata endpoint.

## Scientific safeguards

- **Do not recalculate when filtering:** preserve the 2014–2023 period and published Holm families: four original regional tests and 127 municipal tests, with 14 exploratory regional tests kept separate. Intervals are marginal; evidence is determined by the adjusted p-value. Preserve each analysis's heteroskedasticity- and autocorrelation-consistent (HAC) settings as documented in its report.
- **Do not mix scales or reference periods:** municipal wildfire counts are seasonal; regional counts are monthly. In the exported context, contemporaneous anomalies use 114 months, while antecedent conditions use a 120-month environmental reference.
- **Do not confuse missing values with zeros:** return `null` with a reason; distinguish quality exclusions, unknown coverage, and insufficient evidence. Keep `high_activity = null` outside the comparison population; high historical activity does not imply future risk.
- **Do not publish forecasts:** the existing model is explanatory. Recalculation for other intervals and prediction are outside the initial scope.

The five data endpoints are implemented and tested with synthetic and real data. Existing results are preserved without re-estimation; this architecture requires no new measurements.
