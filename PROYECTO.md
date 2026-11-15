# DeHecho — Statistical Explorer of La Araucanía

The project introduction is also included in the [README](README.md), alongside the interface preview, frontend repository, and setup instructions.

## Objective

Enable users to examine **how environmental conditions change, where, by how much, and with what statistical evidence**, and explore their associations with wildfires recorded by Chile's National Forestry Corporation (CONAF).

The project addresses the [NASA Space Apps 2026 Earth System Trend Detective challenge](https://www.spaceappschallenge.org/2026/challenges/earth-system-trend-detective/?tab=details). It builds on existing data; **forecasting and alerts are outside the initial scope**.

## What can be explored

- Temperature, precipitation, relative humidity, and soil-moisture series at regional or municipal scale.
- Anomalies: departures from typical conditions for each calendar month within the reference period.
- Trends for 2014–2023, including magnitude, uncertainty, and statistical evidence.
- Wildfire associations, episodes, and results from the previously fitted explanatory model.

The analyses are available in `analisis.ipynb`, with outputs in `datos_mensuales_2014_2023/limpios/`. The API serves environmental series and trends, the four adjusted associations from the CONAF model, and their summaries. Correlations and group comparisons are deferred. Analyses only need to be rerun if the underlying data or analysis changes; nothing is recalculated per query. See the [architecture](ARQUITECTURA.md).

The API also serves the 14 existing exploratory regional trends in `docs/investigacion/` and five environmental summaries. These retain their own Holm correction, without replacing the original analysis or extending observed series.

## Data and important limitations

- **Environment:** 120 months from 2014–2023 and 32 municipalities. The joint regional wildfire context covers 114 months: July 2014–December 2023.
- **Wildfires:** regional monthly counts and municipal counts by July–June fire season. No fire coordinates or municipal monthly breakdowns are available; these must not be invented, nor regional totals distributed across municipalities.
- **Regional alignment:** `definitivo.csv` aligns the same 114 matched months by calendar `fecha`; `año_x` retains the fire-season starting year. It does not replace the 120-month environmental baseline used for trends.
- **Quality:** exclude Saavedra's soil moisture because of low coverage, without removing its other variables. Unknown coverage is not equivalent to 100%. Missing values are not zeros.
- **Interpretation:** the associations and negative binomial model are explanatory; they neither prove causality nor predict risk. Counts do not represent burned area or severity. Municipalities may share source pixels and are not independent replicates.

## What the current results support

In the original four-variable analysis, **relative humidity declines with statistical evidence** across the region and its municipalities during 2014–2023. The other three variables do not meet the evidence threshold after the applied correction; this does not demonstrate an absence of change.

The regional exploration shows increasing area-mean monthly temperature peaks and declining dew point and specific humidity. Vapor pressure deficit (VPD) proxies are not true mean VPD; the signals share underlying information and establish neither new wildfire associations nor differences between slopes. They must not be extrapolated to municipalities.

**Rainfall deficit retains the most stable adjusted association with wildfires across the variants examined.** It must not be confused with the variable changing most strongly or with a validated predictor.

Published trends refer to the full 2014–2023 period: filtering a series does not change its estimate. Methods, references, and corrections from the original reports must be preserved; statistical evidence cannot be inferred from the confidence interval alone.
