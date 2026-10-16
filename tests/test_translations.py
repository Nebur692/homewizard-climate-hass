"""English and Spanish carry the same strings, with the same placeholders."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "homewizard_climate"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def _leaves(tree: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_leaves(value, path))
        else:
            out[path] = value
    return out


EN = _leaves(_load("translations/en.json"))
ES = _leaves(_load("translations/es.json"))
STRINGS = _leaves(_load("strings.json"))


def test_same_keys_in_both_languages_and_in_strings_json() -> None:
    assert set(EN) == set(ES)
    assert set(EN) == set(STRINGS)
    assert len(EN) == 46, len(EN)


def test_same_placeholders_in_both_languages() -> None:
    for key, text in EN.items():
        assert set(PLACEHOLDER.findall(text)) == set(PLACEHOLDER.findall(ES[key])), key


def test_custom_integration_translations_are_resolved() -> None:
    # Home Assistant only resolves [%key:...%] references for core integrations.
    assert not [k for k, v in {**EN, **ES}.items() if "[%key:" in v]


def test_every_error_and_issue_carries_its_burburito_code() -> None:
    for key, text in {**EN, **ES}.items():
        if ".error." in key or (key.startswith("issues.") and key.endswith(".description")):
            assert "{code}" in text and "{joke}" in text, key
            assert ("Burburito code" in text) or ("Código burburito" in text), key


def test_spanish_is_written_in_full() -> None:
    joined = " ".join(ES.values())
    for word in ("Contraseña", "está", "conexión", "¿Tienes que hacer algo?"):
        assert word in joined, word
