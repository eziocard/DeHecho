"""Lectura JSON y verificación de integridad compartidas por los adaptadores."""

import hashlib
import json
from typing import Protocol

from pydantic import JsonValue, TypeAdapter

from app.datos.models import (
    Document,
    Kind,
    ResultDocument,
    SeriesDocument,
    ensure_finite,
)

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def hash_match(content: bytes, expected: str) -> str:
    """Equivalencia histórica limitada a saltos de línea; no normaliza otros bytes."""
    if hashlib.sha256(content).hexdigest() == expected:
        return "exact"
    lf = content.replace(b"\r\n", b"\n")
    if expected in (
        hashlib.sha256(lf).hexdigest(),
        hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest(),
    ):
        return "line_endings_only"
    return "mismatch"


def read_json(content: bytes) -> dict[str, JsonValue]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"Constante JSON no válida: {value}")

    def unique_keys(pairs: list[tuple]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Clave JSON duplicada: {key}")
            result[key] = value
        return result

    value = json.loads(
        content.decode("utf-8-sig"),
        parse_constant=reject_constant,
        object_pairs_hook=unique_keys,
    )
    ensure_finite(value)
    return JSON_OBJECT.validate_python(value)


class PublicationAdapter(Protocol):
    def load(self, content: bytes, kind: Kind) -> Document: ...


class JsonPublicationAdapter:
    def load(self, content: bytes, kind: Kind) -> Document:
        model = SeriesDocument if kind == Kind.SERIES else ResultDocument
        return model.model_validate(read_json(content))
