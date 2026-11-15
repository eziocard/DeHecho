from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.schemas import (
    AssociationResponse,
    DatasetSummary,
    ErrorResponse,
    FindingResponse,
    HealthResponse,
    ResultQuery,
    SeriesQuery,
    SeriesResponse,
    TrendResponse,
)
from app.consultas.service import catalog, query_series
from app.datos.models import Kind, Status
from app.datos.publication import Publication
from app.resultados.service import query_results

router = APIRouter(responses={
    404: {"model": ErrorResponse, "description": "El conjunto no existe."},
    422: {"model": ErrorResponse, "description": "Parámetros incompatibles o no válidos."},
    503: {"model": ErrorResponse, "description": "Publicación o conjunto no disponible, inválido o desactualizado."},
})


def get_publication(request: Request) -> Publication:
    return request.app.state.publication


CurrentPublication = Annotated[Publication, Depends(get_publication)]


@router.get("/", include_in_schema=False)
def root():
    return {"name": "DeHecho", "docs": "/docs", "health": "/health"}


@router.get("/health", tags=["estado"], response_model=HealthResponse)
def health(publication: CurrentPublication):
    artifacts = publication.manifest.artifacts if publication.manifest else []
    ready = artifacts and all(publication.states[item.id].status == Status.READY for item in artifacts)
    return {"status": "ok" if ready else "degraded"}


@router.get("/api/catalogo", tags=["consulta"], response_model=list[DatasetSummary])
def get_catalog(publication: CurrentPublication):
    return catalog(publication)


@router.get("/api/series", tags=["consulta"], response_model=list[SeriesResponse], response_model_exclude_unset=True)
def get_series(params: Annotated[SeriesQuery, Query()], publication: CurrentPublication):
    """Filtra por solapamiento de períodos; no desagrega observaciones."""
    return query_series(publication, **params.model_dump())


@router.get("/api/tendencias", tags=["resultados"], response_model=list[TrendResponse], response_model_exclude_unset=True)
def get_trends(params: Annotated[ResultQuery, Query()], publication: CurrentPublication):
    """Usar dataset=tendencias_ambientales o tendencias_regionales_exploratorias.

    Ejemplo exploratorio: variable=temperature_monthly_peak_area_mean_c, territory_id=09.
    La exploración es solo regional: 14 estimaciones, 120 meses de 2014–2023.
    Filtrar conserva el período y la familia Holm de cada análisis, sin mezclarlos.
    Las estimaciones VPD son proxies de medias mensuales, no series ni extremos diarios.
    """
    return query_results(publication, kind=Kind.TRENDS, **params.model_dump())


@router.get(
    "/api/asociaciones", tags=["resultados"],
    response_model=list[AssociationResponse],
    response_model_exclude_unset=True,
)
def get_associations(params: Annotated[ResultQuery, Query()], publication: CurrentPublication):
    """Usar dataset=asociaciones_conaf y territory_id=09 (opcional).

    Cuatro asociaciones ajustadas del modelo explicativo, no pronósticos.
    direction indica aumento o disminución de la anomalía mensual por increment unidades.
    """
    return query_results(publication, kind=Kind.ASSOCIATIONS, **params.model_dump())


@router.get("/api/hallazgos", tags=["resultados"], response_model=list[FindingResponse], response_model_exclude_unset=True)
def get_findings(params: Annotated[ResultQuery, Query()], publication: CurrentPublication):
    """Usar dataset=hallazgos_conaf o hallazgos_ambientales; región 09.

    Ejemplo ambiental: variable=dewpoint_2m_c, territory_id=09.
    Resúmenes deterministas de análisis existentes, sin nuevas estimaciones.
    Los ambientales son exploratorios de 2014–2023, no nuevas asociaciones CONAF.
    """
    return query_results(publication, kind=Kind.FINDINGS, **params.model_dump())
