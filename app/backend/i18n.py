"""
Lekki system tłumaczeń MSI Control (bez zależności, bez Qt Linguist).

Każdy język to plik JSON w katalogu locales/. Klucz = polski tekst
źródłowy, wartość = tłumaczenie. Brak wpisu => fallback do PL, więc
aplikacja zawsze działa nawet przy niepełnym katalogu.
"""

import json
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"

SUPPORTED = {
    "pl": "Polski",
    "en": "English",
    "de": "Deutsch",
    "es": "Español",
}

_current = "pl"
_catalog: dict[str, str] = {}


def available() -> dict[str, str]:
    """Zbiór obsługiwanych języków: kod -> nazwa w języku macierzystym."""
    return dict(SUPPORTED)


def current_lang() -> str:
    return _current


def load(lang: str) -> None:
    """Ustawia aktywny język (kod). Nieznany kod -> PL."""
    global _current, _catalog

    if lang not in SUPPORTED:
        lang = "pl"

    _current = lang
    if lang == "pl":
        _catalog = {}
        return

    path = LOCALES_DIR / f"{lang}.json"
    try:
        _catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _catalog = {}


def tr(message: str, **kwargs) -> str:
    """Zwraca przetłumaczony tekst. `kwargs` formatują placeholdery {x}."""
    text = _catalog.get(message, message)
    if kwargs:
        try:
            text = text.format_map(kwargs)
        except (KeyError, ValueError, IndexError):
            pass
    return text