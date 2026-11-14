from datetime import date
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from app.datos.models import Kind, Model


class ResultQuery(Model):
    dataset: str = Field(min_length=1)
    variable: str | None = Field(default=None, min_length=1)
    territory_id: str | None = Field(default=None, min_length=1)


class SeriesQuery(ResultQuery):
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def ordered_period(self) -> "SeriesQuery":
        if self.start and self.end and self.end < self.start:
            raise ValueError("end no puede ser anterior a start.")
        return self


class PointResponse(Model):
    start: date
    end: date
    value: float | None
    missing_reason: str | None = None


class SeriesResponse(Model):
    variable: str
    territory_id: str
    geography_level: str
    unit: str
    frequency: Literal["month", "season", "year"]
    points: list[PointResponse]


class TrendResponse(Model):
    variable: str
    territory_id: str
    geography_level: str
    period_start: date
    period_end: date
    unit: str
    slope_per_decade: float | None
    ci95_marginal_low: float | None
    ci95_marginal_high: float | None
    p_holm: float | None
    status: Literal["evidence_increasing", "evidence_decreasing", "uncertain_trend", "insufficient_coverage"]
    n_used: int = Field(ge=0)
    exclusion_reason: str | None = None


class AssociationBase(Model):
    variable: str
    territory_id: str | None = None
    period_start: date
    period_end: date
    n_used: int = Field(ge=0)
    ci95_marginal_low: float | None = None
    ci95_marginal_high: float | None = None
    p_holm: float | None = None


class CorrelationResponse(AssociationBase):
    type: Literal["correlation"]
    statistic: Literal["spearman", "pearson"]
    coefficient: float | None = Field(ge=-1, le=1)
    lag_months: int | None = None


class GroupContrastResponse(AssociationBase):
    type: Literal["group_contrast"]
    group: str
    reference_group: str
    difference: float | None
    unit: str


class RateRatioResponse(AssociationBase):
    type: Literal["rate_ratio"]
    rate_ratio: float | None = Field(gt=0)
    increment: float = Field(gt=0, description="Incremento de la variable al que corresponde la razón de tasas.")
    unit: str


AssociationResponse = Annotated[
    CorrelationResponse | GroupContrastResponse | RateRatioResponse,
    Field(discriminator="type"),
]


class FindingResponse(Model):
    id: str
    title: str
    summary: str
    variable: str | None = None
    territory_id: str | None = None
    period_start: date
    period_end: date


class DatasetSummary(Model):
    id: str
    label: str
    kind: Kind
    available: bool
    variables: list[str]
    territories: list[str]
    units: list[str]


class HealthResponse(Model):
    status: Literal["ok", "degraded"]


class ErrorDetail(Model):
    code: str
    message: str
    details: list[dict[str, JsonValue]] | None = None


class ErrorResponse(Model):
    error: ErrorDetail
