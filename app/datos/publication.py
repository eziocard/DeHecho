"""Carga única al arrancar; nunca mezcla archivos de publicaciones distintas."""

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.datos.adapters import JsonPublicationAdapter, read_json
from app.datos.models import ArtifactSpec, Document, Manifest, SourceSpec, Status

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AssetState:
    status: Status
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Publication:
    manifest: Manifest | None = None
    states: dict[str, AssetState] = field(default_factory=dict)
    documents: dict[str, Document] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


def _read_asset(root: Path, spec: SourceSpec) -> bytes:
    relative = Path(spec.path)
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root):
        raise ValueError("Los archivos deben permanecer dentro de la publicación.")
    return path.read_bytes()


def load_publication(manifest_path: Path | None) -> Publication:
    if manifest_path is None:
        return Publication(warnings=("No se ha configurado una publicación de datos.",))
    try:
        manifest = Manifest.model_validate(read_json(manifest_path.read_bytes()))
    except (OSError, ValueError) as exc:
        logger.warning("No se pudo cargar el manifiesto: %s", exc)
        return Publication(warnings=("El manifiesto no está disponible o no es válido.",))

    root = manifest_path.resolve().parent
    specs = {item.id: item for item in [*manifest.sources, *manifest.artifacts]}
    local: dict[str, AssetState] = {}
    documents: dict[str, Document] = {}
    adapter = JsonPublicationAdapter()

    for key, spec in specs.items():
        try:
            content = _read_asset(root, spec)
            if hashlib.sha256(content).hexdigest() != spec.sha256:
                status = Status.INVALID if isinstance(spec, ArtifactSpec) else Status.STALE
                local[key] = AssetState(status, ("La huella del archivo ha cambiado.",))
                continue
            if isinstance(spec, ArtifactSpec):
                documents[key] = adapter.load(content, spec.kind)
            local[key] = AssetState(Status.READY)
        except OSError:
            local[key] = AssetState(Status.UNAVAILABLE, ("No se pudo leer el archivo.",))
        except ValueError as exc:
            logger.warning("Archivo %s inválido: %s", key, exc)
            local[key] = AssetState(Status.INVALID, ("El archivo no cumple el contrato de publicación.",))

    states: dict[str, AssetState] = {}

    def resolve(key: str, visiting: frozenset[str]) -> AssetState:
        if key in states:
            return states[key]
        if key in visiting:
            return AssetState(Status.INVALID, ("Hay un ciclo entre dependencias.",))
        spec = specs[key]
        own = local[key]
        problems = [] if own.status == Status.READY else [own]
        if isinstance(spec, ArtifactSpec):
            for dependency, expected in spec.depends_on.items():
                if dependency not in specs:
                    problems.append(AssetState(Status.INVALID, (f"Dependencia desconocida: {dependency}.",)))
                    continue
                state = resolve(dependency, visiting | {key})
                if state.status != Status.READY:
                    problems.append(AssetState(state.status, (f"Dependencia {dependency}: {state.status.value}.",)))
                elif specs[dependency].sha256 != expected:
                    problems.append(AssetState(Status.STALE, (f"La versión de {dependency} no coincide con el análisis.",)))
        priority = {Status.READY: 0, Status.STALE: 1, Status.UNAVAILABLE: 2, Status.INVALID: 3}
        status = max((item.status for item in problems), key=priority.get, default=Status.READY)
        state = AssetState(status, tuple(reason for item in problems for reason in item.reasons))
        states[key] = state
        return state

    for key in specs:
        resolve(key, frozenset())
    # Los documentos inválidos o desactualizados no son consultables.
    ready = {key: value for key, value in documents.items() if states[key].status == Status.READY}
    return Publication(manifest=manifest, states=states, documents=ready)
