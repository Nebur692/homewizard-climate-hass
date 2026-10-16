"""Burburito codes: the footer every error a person sees ends with.

A light-hearted line, picked at random, and a `Burburito code` —
PPP-MMM-AAA-CCC: project, module, what the person was trying to do, and why it
failed. Whoever hits an error only has to pass that line on: the code says
where to look, with no logs and no screenshots.

Reads only burburito.lock.json next to this file, generated from
burburito.json (the catalogue's source). No database, no network: an error
message has to come out even when everything else is down. And nothing here
may raise — a failure inside the error reporter would leave the person with
no message at all.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

UNCATALOGUED = "000-000-000-000"
_LOCK = Path(__file__).with_name("burburito.lock.json")
_EMERGENCY = {
    "es": "Algo se ha quemado en las cocinas de Burbujalandia y ni siquiera sé qué burburito ha sido.",
    "en": "Something got burnt in the kitchens of Burbujalandia and I do not even know which burburito did it.",
}
_EMOJI = {"aviso": "🫧", "error": "🍳", "catastrofe": "🔥"}


def _load() -> dict:
    try:
        return json.loads(_LOCK.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - must never raise
        _LOGGER.error("Could not read %s: %s", _LOCK, exc)
        return {"codigos": {}, "frases": {}}


_lock = _load()


def _entry(key: str) -> dict:
    entry = (_lock.get("codigos") or {}).get(key)
    if isinstance(entry, dict) and entry.get("codigo"):
        return entry
    _LOGGER.error("Burburito key not in the catalogue: %s", key)
    return {"codigo": UNCATALOGUED, "severidad": "error", "actuar": True}


def code(key: str) -> str:
    try:
        return _entry(key)["codigo"]
    except Exception:  # noqa: BLE001
        return UNCATALOGUED


def footer(key: str, language: str | None = "en") -> dict[str, str]:
    """{code, joke} for this key; Spanish when Home Assistant speaks it."""
    try:
        lang = "es" if (language or "").lower().startswith("es") else "en"
        entry = _entry(key)
        severity = entry.get("severidad", "error")
        phrases = (_lock.get("frases") or {}).get(severity) or []
        chosen = random.choice(phrases) if phrases else {}
        # Never the other language: a line missing in this one falls back to the emergency one.
        line = chosen.get(lang) or _EMERGENCY[lang]
        return {"code": entry["codigo"], "joke": f"{_EMOJI.get(severity, '🍳')} {line}"}
    except Exception as exc:  # noqa: BLE001
        _LOGGER.error("Burburito footer failed for %s: %s", key, exc)
        return {"code": UNCATALOGUED, "joke": _EMERGENCY["en"]}


def known_keys() -> set[str]:
    return set((_lock.get("codigos") or {}).keys())
