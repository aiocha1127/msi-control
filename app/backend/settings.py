"""
Trwały zapis ustawień MSI Control (JSON w ~/.config/msi-control/config.json).

Używane do:
  - zapisywania bieżącego stanu przez GUI,
  - przywracania ustawień (tryb mocy, wentylatory, RGB, autopilot) po
    starcie/restarcie - także bez otwierania okna (tryb --restore).
"""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "msi-control"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "shift_mode": None,
    "fan_mode": None,
    "cooler_boost": None,
    "battery_start": None,
    "battery_end": None,
    "autopilot_enabled": False,
    "autopilot_threshold": 82,
    "lang": "pl",
    "rgb": {
        "mode": "steady",
        "color": [0, 0, 0],
        "target": 0,
        "speed_cs": 900,
        "wave_direction": 0,
        "colors": [],
    },
}


def load() -> dict:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _deep_copy(DEFAULTS)
    merged = _deep_copy(DEFAULTS)
    merged.update(data)
    if isinstance(data.get("rgb"), dict):
        merged["rgb"].update(data["rgb"])
    return merged


def save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _deep_copy(value):
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value