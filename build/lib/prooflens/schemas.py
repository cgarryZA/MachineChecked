"""JSON Schemas of the inventory, the evidence record and the presentation manifest."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources

import jsonschema


@cache
def schema(name: str) -> dict:
    return json.loads(resources.files("prooflens").joinpath(f"data/schema/{name}.schema.json")
                      .read_text())


def validate(obj, name: str) -> None:
    jsonschema.validate(obj, schema(name))
