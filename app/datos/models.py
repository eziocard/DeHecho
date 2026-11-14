"""Contratos internos, independientes de las columnas originales de CONAF."""

import math
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


Identifier = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Kind(StrEnum):
    SERIES = "series"
    TRENDS = "tendencias"
    ASSOCIATIONS = "asociaciones"
    FINDINGS = "hallazgos"


class Status(StrEnum):
    READY = "ready"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


class SourceSpec(Model):
    id: Identifier
    path: Identifier
    sha256: Digest


class ArtifactSpec(SourceSpec):
    kind: Kind
    label: Identifier
    depends_on: dict[Identifier, Digest] = Field(min_length=1)
    adapter: Literal["json-v1"] = "json-v1"


class Manifest(Model):
    schema_version: Literal[1] = 1
    publication_id: Identifier
    generated_at: datetime
    procedure_version: Identifier
    analysis_config: dict[str, JsonValue] = Field(default_factory=dict)
    sources: list[SourceSpec] = Field(default_factory=list)
    artifacts: list[ArtifactSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self) -> "Manifest":
        ids = [item.id for item in [*self.sources, *self.artifacts]]
        if len(ids) != len(set(ids)):
            raise ValueError("Los identificadores de fuentes y resultados deben ser únicos.")
        if self.generated_at.utcoffset() is None:
            raise ValueError("generated_at debe incluir zona horaria.")
        return self


class SeriesPoint(Model):
    variable: Identifier
    territory_id: Identifier
    geography_level: Identifier
    time_scale: Literal["month", "season", "year"]
    period_start: date
    period_end: date
    unit: Identifier
    value: float | None
    missing_reason: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_observation(self) -> "SeriesPoint":
        if self.period_end < self.period_start:
            raise ValueError("El fin del período no puede preceder al inicio.")
        if self.value is None and not self.missing_reason:
            raise ValueError("Un valor ausente requiere un motivo.")
        if self.value is not None and self.missing_reason is not None:
            raise ValueError("Un valor presente no puede tener motivo de ausencia.")
        return self


class ResultItem(Model):
    id: Identifier
    variable: Identifier | None = None
    territory_id: Identifier | None = None
    values: dict[str, JsonValue]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class Metadata(Model):
    """Información publicada: se conserva incluso al filtrar observaciones."""

    period_start: date
    period_end: date
    time_scale: Identifier
    n_observations: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    reference: dict[str, JsonValue] = Field(default_factory=dict)
    method: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_period(self) -> "Metadata":
        if self.period_end < self.period_start:
            raise ValueError("El período publicado no es válido.")
        return self


class SeriesDocument(Model):
    metadata: Metadata
    records: list[SeriesPoint]

    @model_validator(mode="after")
    def valid_records(self) -> "SeriesDocument":
        keys = set()
        for row in self.records:
            key = (row.variable, row.territory_id, row.geography_level,
                   row.time_scale, row.period_start, row.period_end)
            if key in keys:
                raise ValueError("Hay observaciones duplicadas.")
            keys.add(key)
            if not (self.metadata.period_start <= row.period_start
                    <= row.period_end <= self.metadata.period_end):
                raise ValueError("Hay observaciones fuera del período publicado.")
            if row.time_scale != self.metadata.time_scale:
                raise ValueError("La escala de la observación no coincide con la publicación.")
        return self


class ResultDocument(Model):
    metadata: Metadata
    records: list[ResultItem]

    @model_validator(mode="after")
    def unique_records(self) -> "ResultDocument":
        ids = [row.id for row in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("Los identificadores de resultados deben ser únicos.")
        if not self.metadata.method:
            raise ValueError("Los resultados requieren describir su método.")
        return self


Document = SeriesDocument | ResultDocument


def ensure_finite(value: JsonValue) -> None:
    """JSON no admite NaN ni infinitos, tampoco en metadatos anidados."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("La publicación contiene valores no finitos; usar null con motivo.")
    if isinstance(value, dict):
        for item in value.values():
            ensure_finite(item)
    elif isinstance(value, list):
        for item in value:
            ensure_finite(item)
