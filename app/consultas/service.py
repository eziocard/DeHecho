from datetime import date

from app.datos.models import ArtifactSpec, Document, Kind, SeriesDocument, Status
from app.datos.publication import Publication


class QueryError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def get_document(publication: Publication, dataset: str, kind: Kind) -> tuple[ArtifactSpec, Document]:
    if publication.manifest is None:
        raise QueryError(503, "publication_unavailable", "No hay datos válidos disponibles.")
    spec = next((item for item in publication.manifest.artifacts if item.id == dataset), None)
    if spec is None:
        raise QueryError(404, "dataset_not_found", "El conjunto solicitado no existe.")
    if spec.kind != kind:
        raise QueryError(422, "incompatible_dataset", "El conjunto no corresponde al tipo de consulta.")
    state = publication.states[dataset]
    if state.status != Status.READY:
        raise QueryError(503, f"dataset_{state.status.value}", "El conjunto no está vigente o disponible; consulte el catálogo.")
    return spec, publication.documents[dataset]


def catalog(publication: Publication) -> list[dict]:
    datasets = []
    if publication.manifest:
        for spec in publication.manifest.artifacts:
            state = publication.states[spec.id]
            document = publication.documents.get(spec.id)
            rows = document.records if document else []
            datasets.append({
                "id": spec.id,
                "label": spec.label,
                "kind": spec.kind,
                "available": state.status == Status.READY,
                "variables": sorted({row.variable for row in rows if row.variable is not None}),
                "territories": sorted({row.territory_id for row in rows if row.territory_id is not None}),
                "units": sorted({row.unit for row in rows}) if isinstance(document, SeriesDocument) else sorted({
                    row.metadata["rate_unit"] for row in rows
                    if isinstance(row.metadata.get("rate_unit"), str)
                }),
            })
    return datasets


def validate_selectors(document: Document, variable: str | None, territory_id: str | None) -> None:
    for field, requested in (("variable", variable), ("territory_id", territory_id)):
        if requested is not None and not any(getattr(row, field) == requested for row in document.records):
            raise QueryError(422, "unknown_selector", f"El valor de {field} no existe en este conjunto.")


def query_series(
    publication: Publication,
    dataset: str,
    variable: str | None = None,
    territory_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[dict]:
    _, document = get_document(publication, dataset, Kind.SERIES)
    validate_selectors(document, variable, territory_id)
    rows = [row for row in document.records
            if (variable is None or row.variable == variable)
            and (territory_id is None or row.territory_id == territory_id)
            and (start is None or row.period_end >= start)
            and (end is None or row.period_start <= end)]
    groups = {}
    for row in rows:
        key = (row.variable, row.territory_id, row.geography_level, row.unit, row.time_scale)
        if key not in groups:
            groups[key] = {
                "variable": row.variable,
                "territory_id": row.territory_id,
                "geography_level": row.geography_level,
                "unit": row.unit,
                "frequency": row.time_scale,
                "points": [],
            }
        point = {"start": row.period_start, "end": row.period_end, "value": row.value}
        if row.missing_reason is not None:
            point["missing_reason"] = row.missing_reason
        groups[key]["points"].append(point)
    for group in groups.values():
        group["points"].sort(key=lambda point: (point["start"], point["end"]))
    return [groups[key] for key in sorted(groups)]
