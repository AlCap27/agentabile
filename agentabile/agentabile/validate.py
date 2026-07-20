"""
Validazione dell'output ACP contro lo schema JSON ufficiale (vendored).

Usa jsonschema Draft 2020-12 e valida ogni prodotto contro $defs/Product
di schema.feed.json (spec 2026-04-17).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "schema.feed.json"


def _product_validator() -> Draft202012Validator:
    bundle = json.loads(_SCHEMA_PATH.read_text())
    # Schema puntato su $defs/Product, mantenendo il bundle per i $ref interni
    schema = {**bundle, "$ref": "#/$defs/Product"}
    return Draft202012Validator(schema)


def validate_acp_products(products: list[dict[str, Any]]) -> list[str]:
    """Ritorna lista di errori 'prodotto[i]: messaggio'. Vuota = conforme."""
    validator = _product_validator()
    errors: list[str] = []
    for i, prod in enumerate(products):
        for err in sorted(validator.iter_errors(prod), key=lambda e: e.json_path):
            errors.append(f"prodotto[{i}] ({prod.get('id', '?')}) {err.json_path}: {err.message}")
    return errors
