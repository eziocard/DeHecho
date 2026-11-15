"""Coordina una captura única de bytes para todos los conjuntos del inspector."""

from datetime import UTC, datetime
from pathlib import Path

from app.datos.conaf import INPUT_PATHS as CONAF_INPUTS
from app.datos.environment import INPUT_PATHS as ENVIRONMENT_INPUTS
from app.datos.exploration import INPUT_PATHS as EXPLORATION_INPUTS
from app.datos.load_conaf import load_conaf
from app.datos.load_environment import load_environment
from app.datos.load_exploration import load_exploration
from app.datos.models import Manifest
from app.datos.publication import Publication


def load_data(project_root: Path) -> Publication:
    files = {}
    for path in dict.fromkeys((*ENVIRONMENT_INPUTS, *CONAF_INPUTS, *EXPLORATION_INPUTS)):
        try:
            files[path] = (project_root / path).read_bytes()
        except OSError:
            # Cada cargador registra y bloquea únicamente los conjuntos afectados.
            continue
    environment = load_environment(project_root, captured_files=files)
    conaf = load_conaf(project_root, captured_files=files)
    exploration = load_exploration(project_root, captured_files=files)
    registry = Manifest(
        publication_id="local-data", generated_at=datetime.now(UTC), procedure_version="inspector-direct-v1",
        sources=[*environment.manifest.sources, *conaf.manifest.sources, *exploration.manifest.sources],
        artifacts=[*environment.manifest.artifacts, *conaf.manifest.artifacts, *exploration.manifest.artifacts],
        analysis_config={"load_mode": "direct", "reestimated": False,
                         "environment": environment.manifest.analysis_config, "conaf": conaf.manifest.analysis_config,
                         "exploration": exploration.manifest.analysis_config},
    )
    return Publication(
        manifest=registry, states={**environment.states, **conaf.states, **exploration.states},
        documents={**environment.documents, **conaf.documents, **exploration.documents},
    )
