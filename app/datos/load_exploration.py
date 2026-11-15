"""Lectura aislada de resultados exploratorios existentes en docs/investigacion."""

import logging
from datetime import UTC, datetime
from pathlib import Path

from app.datos.environment import digest
from app.datos.exploration import INPUT_PATHS, ExplorationAdapter, StaleExplorationData
from app.datos.models import ArtifactSpec, Kind, Manifest, SourceSpec, Status
from app.datos.publication import AssetState, Publication

logger = logging.getLogger(__name__)


def load_exploration(project_root: Path, *, captured_files: dict[str, bytes] | None = None) -> Publication:
    files, states, sources = {}, {}, []
    for path in INPUT_PATHS:
        identifier = f"exploration-input:{path}"
        try:
            files[path] = captured_files[path] if captured_files is not None else (project_root / path).read_bytes()
            states[identifier] = AssetState(Status.READY)
        except (OSError, KeyError):
            states[identifier] = AssetState(Status.UNAVAILABLE, (f"No se pudo leer {path}.",))
            logger.warning("No se pudo leer la entrada exploratoria %s", project_root / path)
        sources.append(SourceSpec(id=identifier, path=path, sha256=digest(files[path]) if path in files else "0" * 64))
    documents, adapter = {}, None
    if len(files) != len(INPUT_PATHS):
        state = AssetState(Status.UNAVAILABLE, ("Faltan entradas de la investigación exploratoria.",))
    else:
        try:
            adapter = ExplorationAdapter(files)
            documents = {"tendencias_regionales_exploratorias": adapter.trends(), "hallazgos_ambientales": adapter.findings()}
            state = AssetState(Status.READY)
        except StaleExplorationData as exc:
            logger.warning("La investigación está desactualizada: %s", exc)
            state = AssetState(Status.STALE, (str(exc),))
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
            logger.warning("La investigación no es válida: %s", exc)
            state = AssetState(Status.INVALID, ("Los resultados exploratorios no cumplen el contrato esperado.",))
    artifacts = []
    for key, kind, label in (
        ("tendencias_regionales_exploratorias", Kind.TRENDS, "Tendencias regionales exploratorias (Holm sobre 14 series)"),
        ("hallazgos_ambientales", Kind.FINDINGS, "Hallazgos ambientales regionales exploratorios"),
    ):
        states[key] = state
        sha256 = digest(documents[key].model_dump_json().encode("utf-8")) if key in documents else "0" * 64
        artifacts.append(ArtifactSpec(
            id=key, path=f"memory/{key}", sha256=sha256, kind=kind, label=label,
            depends_on={source.id: source.sha256 for source in sources},
        ))
    registry = Manifest(
        publication_id="local-exploration", generated_at=datetime.now(UTC), procedure_version="exploration-direct-v1",
        sources=sources, artifacts=artifacts,
        analysis_config={"reestimated": False, "load_mode": "direct", "exploratory": True,
                         "historical_hash_verification": adapter.audit if adapter else []},
    )
    return Publication(manifest=registry, states=states, documents=documents)
