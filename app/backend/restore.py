"""
Przywracanie zapisanych ustawień (tryb mocy, wentylatory, bateria, RGB).

Używane z GUI (przycisk "Przywróć zapisane" / autostart) oraz z wiersza
poleceń:  python main_window.py --restore   (bez otwierania okna).

Zmiany w sysfs idą przez helper (pkexec), więc przywracanie wymaga reguły
polkit albo jednorazowego podania hasła.
"""

import subprocess

from backend.settings import load
from backend.i18n import tr
from backend.rgb import (
    MsiRgbKeyboard,
    MODE_STEADY,
    MODE_BREATHING,
    MODE_CYCLE,
    MODE_WAVE,
    ZONE_1,
    ZONE_2,
    ZONE_3,
    ZONE_4,
    ZONE_ALL,
    ZONE_MASKS,
    RAINBOW,
    Ms1565UnavailableError,
    Ms1565CommandError,
)

HELPER_PATH = "/usr/local/bin/msi-control-helper"


def _run_action(action: str, value: str) -> str:
    """Wykonuje jedną akcję helpera przez pkexec."""
    proc = subprocess.run(
        ["pkexec", HELPER_PATH, action, value],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode == 0:
        return tr("ok")
    return proc.stderr.strip() or tr("błąd {e}", e=proc.returncode)


def _restore_rgb(cfg: dict) -> bool:
    """Przywraca ostatni stan RGB (bez roota, przez HID)."""
    rgb = cfg.get("rgb") or {}
    mode = rgb.get("mode")
    color = tuple(rgb.get("color") or (255, 255, 255))
    colors = [
        tuple(c) for c in (rgb.get("colors") or [color])
        if c is not None
    ]
    speed = int(rgb.get("speed_cs", 900))
    direction = int(rgb.get("wave_direction", 0))
    zone = int(rgb.get("zone", -1))

    try:
        with MsiRgbKeyboard() as kb:
            if mode == "off":
                kb.turn_off()
                return True
            if mode == "breathe":
                kb.set_breathe(*color, speed_ms=speed * 10)
                return True
            if mode == "cycle":
                kb.set_cycle(colors, speed_cs=speed)
                return True
            if mode == "wave":
                kb.set_wave(colors, speed_cs=speed, direction=direction)
                return True
            if zone in (ZONE_1, ZONE_2, ZONE_3, ZONE_4):
                kb.set_color_zone(zone - 1, *color)
            else:
                kb.set_color_all(*color)
            return True
    except (Ms1565UnavailableError, Ms1565CommandError, ValueError):
        return False


def restore() -> list[tuple[str, str]]:
    """Przywraca wszystkie zapisane ustawienia. Zwraca listę (sekcja, wynik)."""
    try:
        cfg = load()
    except Exception as e:  # noqa: BLE001 - brak konfiguracji nie jest błędem krytycznym
        return [("config", tr("brak konfiguracji: {e}", e=e))]

    results: list[tuple[str, str]] = []

    if cfg.get("shift_mode"):
        results.append(("shift", _run_action("set-shift-mode", cfg["shift_mode"])))

    if cfg.get("fan_mode"):
        results.append(("fan", _run_action("set-fan-mode", cfg["fan_mode"])))

    if cfg.get("cooler_boost") is not None:
        value = "on" if cfg["cooler_boost"] else "off"
        results.append(("cooler", _run_action("set-cooler-boost", value)))

    if cfg.get("battery_start") is not None:
        results.append(("batt_start",
                        _run_action("set-battery-start", str(cfg["battery_start"]))))

    if cfg.get("battery_end") is not None:
        results.append(("batt_end",
                        _run_action("set-battery-end", str(cfg["battery_end"]))))

    if _restore_rgb(cfg):
        results.append(("rgb", tr("ok")))
    else:
        results.append(("rgb", tr("brak urządzenia")))

    return results


if __name__ == "__main__":
    print("\n".join(f"{k}: {v}" for k, v in restore()))
