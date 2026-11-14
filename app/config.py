"""La raíz de datos se resuelve desde el código, no desde el directorio de ejecución."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_root: Path = Path(__file__).resolve().parents[1]
