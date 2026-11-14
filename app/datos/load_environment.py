"""Carga directa de archivos originales al iniciar; no copia ni genera publicaciones."""

import logging
from datetime import UTC, datetime
from pathlib import Path

from app.datos.environment import (
    CLEAN,
    DATA,
    INPUT_PATHS,
    TRENDS_REPORT,
    VALIDATION,
    EnvironmentAdapter,
    digest,
)
from app.datos.models import ArtifactSpec, Kind, Manifest, SourceSpec, Status
from app.datos.publication import AssetState, Publication

logger = logging.getLogger(__name__)


def load_environment(project_root: Path) -> Publication:
    files = {}
    input_states = {}
    for path in INPUT_PATHS:
        try:
            files[path] = (project_root / path).read_bytes()
            input_states[path] = AssetState(Status.READY)
        except OSError:
            input_states[path] = AssetState(Status.UNAVAILABLE, (f"No se pudo leer {path}.",))
            logger.warning("No se pudo leer el archivo ambiental %s", project_root / path)

    common = [f"{DATA}/metadatos.json", VALIDATION, TRENDS_REPORT]
    datasets = {
        "ambiente_region": (Kind.SERIES, "Series ambientales regionales", common + [
            f"{DATA}/region_mensual.csv", f"{CLEAN}/region_mensual_limpio.csv",
        ]),
        "ambiente_comunas": (Kind.SERIES, "Series ambientales comunales", common + [
            f"{DATA}/comunas_mensual.csv", f"{CLEAN}/comunas_mensual_limpio.csv",
        ]),
        "tendencias_ambientales": (Kind.TRENDS, "Tendencias ambientales publicadas", list(INPUT_PATHS)),
    }
    adapter = None
    global_error = None
    try:
        adapter = EnvironmentAdapter(files, strict=False)
        for path, reason in adapter.verification_errors.items():
            if input_states[path].status == Status.READY:
                input_states[path] = AssetState(Status.STALE, (reason,))
                logger.warning("Resultado ambiental desactualizado: %s", reason)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.warning("No se pudieron validar los datos ambientales: %s", exc)
        missing = any(path not in files for path in common)
        global_error = AssetState(
            Status.UNAVAILABLE if missing else Status.INVALID,
            ("Los reportes ambientales no están disponibles o no son compatibles.",),
        )

    sources = {
        path: SourceSpec(id=f"input:{path}", path=path, sha256=digest(files[path]) if path in files else "0" * 64)
        for path in INPUT_PATHS
    }
    states = {sources[path].id: state for path, state in input_states.items()}
    documents = {}
    artifacts = []
    priority = {Status.READY: 0, Status.STALE: 1, Status.UNAVAILABLE: 2, Status.INVALID: 3}
    for key, (kind, label, dependencies) in datasets.items():
        problems = [input_states[path] for path in dependencies if input_states[path].status != Status.READY]
        if global_error:
            problems.append(global_error)
        status = max((item.status for item in problems), key=priority.get, default=Status.READY)
        reasons = tuple(reason for item in problems for reason in item.reasons)
        sha256 = "0" * 64
        if status == Status.READY:
            try:
                if key == "tendencias_ambientales":
                    document = adapter.trend_results()
                else:
                    document = adapter.series("region" if key == "ambiente_region" else "commune")
                documents[key] = document
                sha256 = digest(document.model_dump_json().encode("utf-8"))
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                logger.warning("El conjunto %s no es válido: %s", key, exc)
                status, reasons = Status.INVALID, ("Los datos no cumplen el contrato ambiental.",)
        states[key] = AssetState(status, reasons)
        artifacts.append(ArtifactSpec(
            id=key, path=f"memory/{key}", sha256=sha256, kind=kind, label=label,
            depends_on={sources[path].id: sources[path].sha256 for path in dependencies},
        ))
    # Registro interno únicamente en memoria; ningún manifiesto se escribe ni se solicita.
    registry = Manifest(
        publication_id="local-environment", generated_at=datetime.now(UTC),
        procedure_version="environment-direct-v1", sources=list(sources.values()), artifacts=artifacts,
        analysis_config={"reestimated": False, "load_mode": "direct",
                         "historical_hash_verification": adapter.audit if adapter else []},
    )
    return Publication(manifest=registry, states=states, documents=documents)
