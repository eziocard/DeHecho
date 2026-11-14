"""Adaptadores de publicaciones. Los lectores de fuentes originales quedan pendientes."""

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
