"""Proyección explícita de los resultados: nunca expone los reportes internos."""

import calendar
import logging
from datetime import date

from app.api.schemas import (
    CorrelationResponse,
    FindingResponse,
    GroupContrastResponse,
    RateRatioResponse,
    TrendResponse,
)
from app.consultas.service import QueryError, get_document, validate_selectors
from app.datos.models import Kind, Metadata, ResultItem
from app.datos.publication import Publication

logger = logging.getLogger(__name__)


def _date(value: str | date, *, end: bool = False) -> date:
    if isinstance(value, date):
        return value
    if len(value) == 7:
        result = date.fromisoformat(f"{value}-01")
        return result.replace(day=calendar.monthrange(result.year, result.month)[1]) if end else result
    return date.fromisoformat(value)


def _period(row: ResultItem, metadata: Metadata) -> dict:
    return {
        "period_start": _date(row.metadata.get("period_start", metadata.period_start)),
        "period_end": _date(row.metadata.get("period_end", metadata.period_end), end=True),
    }


def _trend(row: ResultItem, metadata: Metadata) -> TrendResponse:
    values = row.values
    result = {
        "variable": row.variable,
        "territory_id": row.territory_id,
        "geography_level": row.metadata["geography_level"],
        **_period(row, metadata),
        "unit": row.metadata["rate_unit"],
        "slope_per_decade": values["slope_per_decade"],
        "ci95_marginal_low": values["CI95_low_per_decade"],
        "ci95_marginal_high": values["CI95_high_per_decade"],
        "p_holm": values["p_holm"],
        "status": values["status"],
        "n_used": values["n_used"],
    }
    if values.get("exclusion_reason"):
        result["exclusion_reason"] = values["exclusion_reason"]
    return TrendResponse.model_validate(result)


def _association(row: ResultItem, metadata: Metadata):
    values = row.values
    result = {"variable": row.variable, **_period(row, metadata), "n_used": values["n_used"]}
    if row.territory_id is not None:
        result["territory_id"] = row.territory_id
    for key in ("ci95_marginal_low", "ci95_marginal_high", "p_holm"):
        if key in values:
            result[key] = values[key]
    models = {
        "correlation": (CorrelationResponse, ("type", "statistic", "coefficient")),
        "group_contrast": (GroupContrastResponse, ("type", "group", "reference_group", "difference", "unit")),
        "rate_ratio": (RateRatioResponse, ("type", "rate_ratio", "increment", "direction", "unit")),
    }
    model, fields = models[values["type"]]
    result.update({key: values[key] for key in fields})
    if values["type"] == "correlation" and "lag_months" in values:
        result["lag_months"] = values["lag_months"]
    return model.model_validate(result)


def _finding(row: ResultItem, metadata: Metadata) -> FindingResponse:
    result = {"id": row.id, "title": row.values["title"], "summary": row.values["summary"], **_period(row, metadata)}
    for key in ("variable", "territory_id"):
        value = getattr(row, key)
        if value is not None:
            result[key] = value
    return FindingResponse.model_validate(result)


def query_results(
    publication: Publication,
    dataset: str,
    kind: Kind,
    variable: str | None = None,
    territory_id: str | None = None,
) -> list:
    _, document = get_document(publication, dataset, kind)
    validate_selectors(document, variable, territory_id)
    rows = [row for row in document.records
            if (variable is None or row.variable == variable)
            and (territory_id is None or row.territory_id == territory_id)]
    project = {Kind.TRENDS: _trend, Kind.ASSOCIATIONS: _association, Kind.FINDINGS: _finding}[kind]
    try:
        return [project(row, document.metadata) for row in rows]
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("El conjunto %s no se puede presentar: %s", dataset, exc)
        raise QueryError(503, "unsupported_result", "El conjunto no tiene un formato de resultado compatible.") from exc
