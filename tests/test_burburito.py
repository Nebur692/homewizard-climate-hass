"""Every burburito key the code uses is in the catalogue, and the lock matches it."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from custom_components.homewizard_climate import burburito

ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "homewizard_climate"
KEY = re.compile(r"""["']([a-z0-9-]+/[a-z0-9-]+/[a-z0-9-]+)["']""")
CATALOGUE = json.loads((ROOT / "burburito.json").read_text(encoding="utf-8"))
LOCK = json.loads((ROOT / "burburito.lock.json").read_text(encoding="utf-8"))
MODULES = {m["slug"] for m in CATALOGUE["modulos"]}


def _keys_used_in_the_code() -> set[str]:
    found = set()
    for path in ROOT.rglob("*.py"):
        for key in KEY.findall(path.read_text(encoding="utf-8")):
            if key.split("/")[0] in MODULES:
                found.add(key)
    return found


def test_every_key_in_the_code_is_catalogued() -> None:
    used = _keys_used_in_the_code()
    # The total, not just "none bad": an empty scan would pass that vacuously.
    assert len(used) == 7, sorted(used)
    assert not used - burburito.known_keys()
    for key in used:
        assert burburito.code(key) != burburito.UNCATALOGUED


def test_every_catalogued_code_is_used() -> None:
    assert burburito.known_keys() == _keys_used_in_the_code()


def test_the_lock_matches_its_catalogue() -> None:
    in_catalogue = {f"{c['modulo']}/{c['accion']}/{c['causa']}" for c in CATALOGUE["codigos"]}
    assert in_catalogue == set(LOCK["codigos"]), "run: bin/burburito sincroniza <this burburito.json>"


def test_codes_are_well_formed_and_belong_to_this_project() -> None:
    for key in burburito.known_keys():
        assert re.fullmatch(r"028-\d{3}-\d{3}-\d{3}", burburito.code(key)), key


def test_an_unknown_key_says_so_instead_of_raising() -> None:
    # The lie: a key nobody catalogued must come out as the uncatalogued code.
    assert burburito.code("mando/vigilar/no-existe") == burburito.UNCATALOGUED
    assert burburito.footer("mando/vigilar/no-existe")["code"] == burburito.UNCATALOGUED


def test_footer_speaks_the_home_assistant_language() -> None:
    lines_es = {p["es"] for p in LOCK["frases"]["aviso"]}
    lines_en = {p["en"] for p in LOCK["frases"]["aviso"]}
    footer_es = burburito.footer("conexion/arrancar-servicio/sin-conexion", "es-ES")
    footer_en = burburito.footer("conexion/arrancar-servicio/sin-conexion", "en")
    assert footer_es["joke"].split(" ", 1)[1] in lines_es
    assert footer_en["joke"].split(" ", 1)[1] in lines_en
    assert footer_es["code"] == footer_en["code"] == "028-001-140-001"


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("es", "es"),
        ("es-ES", "es"),
        ("ES", "es"),
        ("es-419", "es"),
        ("en", "en"),
        ("en-GB", "en"),
        ("fr", "en"),
        ("pt-BR", "en"),
        ("de", "en"),
        ("", "en"),
        (None, "en"),
    ],
)
def test_any_language_but_spanish_gets_english(language, expected) -> None:
    lines = {p[expected] for p in LOCK["frases"]["aviso"]}
    joke = burburito.footer("conexion/arrancar-servicio/sin-conexion", language)["joke"]
    assert joke.split(" ", 1)[1] in lines


def test_every_line_exists_in_both_languages() -> None:
    for severity, lines in LOCK["frases"].items():
        for line in lines:
            assert line.get("es") and line.get("en"), (severity, line)


def test_a_line_missing_in_english_never_shows_the_spanish_one(monkeypatch) -> None:
    only_spanish = {"aviso": [{"es": "Solo en español"}]}
    monkeypatch.setitem(burburito._lock, "frases", only_spanish)  # noqa: SLF001
    joke = burburito.footer("conexion/arrancar-servicio/sin-conexion", "en")["joke"]
    assert "español" not in joke
    assert joke.endswith(burburito._EMERGENCY["en"])  # noqa: SLF001
