"""Agenten-interne Helfer: JSON aus LLM-Antworten extrahieren, Inventar zu Merkmalen verdichten."""

from __future__ import annotations

import json
from typing import Any

from geo_audit_loop.domain.errors import ReasoningError
from geo_audit_loop.domain.inventory import PageInventory


def extract_json_object(text: str) -> dict[str, Any]:
    """Parst das erste JSON-Objekt aus ``text`` (toleriert umgebende Prosa/Codeblock-Zaeune).

    Sucht von der ersten ``{`` bis zur letzten ``}``. Wirft ``ReasoningError``, wenn kein
    gueltiges JSON-Objekt enthalten ist (der Agent entscheidet ueber Retry).
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ReasoningError("Reasoning-Antwort enthaelt kein JSON-Objekt")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ReasoningError(f"Reasoning-Antwort ist kein gueltiges JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ReasoningError("Reasoning-JSON ist kein Objekt")
    return data


def page_features(inv: PageInventory) -> dict[str, Any]:
    """Verdichtet ein ``PageInventory`` zu den fuer GEO relevanten On-Page-Merkmalen."""
    page = inv.page
    schema = inv.schema_inventory
    return {
        "url": page.url,
        "title": page.title,
        "word_count": page.word_count,
        "jsonld_types": list(schema.jsonld_types),
        "has_faq": schema.has_faq,
        "has_article": schema.has_article,
        "has_author": schema.has_author,
        "has_breadcrumb": schema.has_breadcrumb,
        "has_howto": "HowTo" in schema.jsonld_types,
    }
