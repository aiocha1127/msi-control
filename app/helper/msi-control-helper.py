#!/usr/bin/env python3
"""
msi-control-helper

Ograniczony skrypt wykonywany z uprawnieniami roota (przez pkexec).

ZASADA BEZPIECZEŃSTWA: ten skrypt NIE przyjmuje dowolnych komend ani
dowolnych wartości. Każda operacja jest jawnie zdefiniowana w kodzie,
a każda wartość wejściowa jest sprawdzana względem sztywnej whitelisty
PRZED jakąkolwiek operacją zapisu czy wywołaniem subprocess.

Nigdy nie używamy tu:
- os.system()
- subprocess z shell=True
- f-stringów budujących komendy z inputu usera
"""

import sys
import subprocess
from pathlib import Path

MSI_EC_ROOT = Path("/sys/devices/platform/msi-ec")

# --- Whitelisty. To jest jedyne źródło prawdy o tym, co wolno zapisać. ---
# Wartości potwierdzone na sprzęcie: MSI Katana 17 B13VEK.
ALLOWED_SHIFT_MODES = {"eco", "comfort", "turbo"}
ALLOWED_FAN_MODES = {"auto", "silent", "advanced"}
ALLOWED_COOLER_BOOST = {"on", "off"}
ALLOWED_GPU_MODES = {"integrated", "hybrid", "manual", "smart"}
BATTERY_ROOT = next(
    Path("/sys/class/power_supply").glob("BAT*"),
    Path("/sys/class/power_supply/BAT0"),
)

# Minimalny odstęp między progiem "start" a "end" - bez tego dałoby się
# ustawić np. start=80, end=80, co nie ma sensu (bateria nigdy by się
# nie ładowała, bo warunek "poniżej progu start" nigdy by nie zaszedł
# jednocześnie z "poniżej progu end").
MIN_BATTERY_THRESHOLD_GAP = 1


class HelperError(Exception):
    """Błąd operacji helpera - komunikat trafi na stderr i zakończy proces kodem 1."""
    pass


def _write_sysfs(path: Path, value: str) -> None:
    """
    Zapisuje pojedynczą wartość do pliku sysfs.
    `value` musi być już zwalidowane przez wywołującego (whitelist) -
    ta funkcja nie robi żadnej dodatkowej interpretacji.
    """
    try:
        path.write_text(value)
    except FileNotFoundError:
        raise HelperError(f"Plik sysfs nie istnieje: {path}")
    except PermissionError:
        raise HelperError(
            f"Brak uprawnień do zapisu {path}. Ten skrypt musi być uruchomiony jako root."
        )
    except OSError as e:
        raise HelperError(f"Błąd zapisu do {path}: {e}")


def _read_battery_threshold(filename: str) -> int | None:
    """
    Bezpieczny odczyt aktualnej wartości progu baterii z sysfs.
    Zwraca None, jeśli plik nie istnieje lub zawiera coś, co nie jest liczbą -
    w takim wypadku walidacja start<end jest pomijana (nie blokujemy operacji
    z powodu braku danych, tylko z powodu jawnie sprzecznych wartości).
    """
    path = BATTERY_ROOT / filename
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, PermissionError, OSError, ValueError):
        return None


def _validate_battery_threshold(value: str) -> int:
    try:
        threshold = int(value)
    except ValueError:
        raise HelperError("Próg baterii musi być liczbą całkowitą 0-100.")

    if not 0 <= threshold <= 100:
        raise HelperError("Próg baterii musi być w zakresie 0-100.")

    return threshold


def set_battery_start_threshold(value: str) -> None:
    threshold = _validate_battery_threshold(value)

    current_end = _read_battery_threshold("charge_control_end_threshold")
    if current_end is not None and threshold > current_end - MIN_BATTERY_THRESHOLD_GAP:
        raise HelperError(
            f"Próg 'start' ({threshold}%) musi być co najmniej {MIN_BATTERY_THRESHOLD_GAP} "
            f"mniejszy niż aktualny próg 'stop' ({current_end}%). "
            f"Jeśli chcesz przesunąć oba progi w dół, najpierw zmień 'stop'."
        )

    _write_sysfs(BATTERY_ROOT / "charge_control_start_threshold", str(threshold))


def set_battery_end_threshold(value: str) -> None:
    threshold = _validate_battery_threshold(value)

    current_start = _read_battery_threshold("charge_control_start_threshold")
    if current_start is not None and threshold < current_start + MIN_BATTERY_THRESHOLD_GAP:
        raise HelperError(
            f"Próg 'stop' ({threshold}%) musi być co najmniej {MIN_BATTERY_THRESHOLD_GAP} "
            f"większy niż aktualny próg 'start' ({current_start}%). "
            f"Jeśli chcesz przesunąć oba progi w górę, najpierw zmień 'start'."
        )

    _write_sysfs(BATTERY_ROOT / "charge_control_end_threshold", str(threshold))


def set_shift_mode(value: str) -> None:
    if value not in ALLOWED_SHIFT_MODES:
        raise HelperError(
            f"Niedozwolona wartość shift_mode: '{value}'. "
            f"Dozwolone: {', '.join(sorted(ALLOWED_SHIFT_MODES))}"
        )
    _write_sysfs(MSI_EC_ROOT / "shift_mode", value)


def set_fan_mode(value: str) -> None:
    if value not in ALLOWED_FAN_MODES:
        raise HelperError(
            f"Niedozwolona wartość fan_mode: '{value}'. "
            f"Dozwolone: {', '.join(sorted(ALLOWED_FAN_MODES))}"
        )
    _write_sysfs(MSI_EC_ROOT / "fan_mode", value)


def set_cooler_boost(value: str) -> None:
    if value not in ALLOWED_COOLER_BOOST:
        raise HelperError(
            f"Niedozwolona wartość cooler_boost: '{value}'. "
            f"Dozwolone: {', '.join(sorted(ALLOWED_COOLER_BOOST))}"
        )
    _write_sysfs(MSI_EC_ROOT / "cooler_boost", value)


def set_gpu_mode(value: str) -> None:
    if value not in ALLOWED_GPU_MODES:
        raise HelperError(
            f"Niedozwolona wartość GPU mode: '{value}'. "
            f"Dozwolone: {', '.join(sorted(ALLOWED_GPU_MODES))}"
        )
    try:
        result = subprocess.run(
            ["cardwire", "set", value],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        raise HelperError("Binarka 'cardwire' nie została znaleziona.")
    except subprocess.TimeoutExpired:
        raise HelperError("Komenda cardwire przekroczyła limit czasu.")

    if result.returncode != 0:
        raise HelperError(
            f"cardwire set {value} zakończyło się błędem: {result.stderr.strip()}"
        )


def get_gpu_mode() -> str:
    """Odczyt trybu GPU - nie wymaga roota, ale trzymamy w tym samym miejscu dla spójności."""
    try:
        result = subprocess.run(
            ["cardwire", "get"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        raise HelperError("Binarka 'cardwire' nie została znaleziona.")

    if result.returncode != 0:
        raise HelperError(f"cardwire get zakończyło się błędem: {result.stderr.strip()}")

    return result.stdout.strip()


ACTIONS_WITH_ARG = {
    "set-shift-mode": set_shift_mode,
    "set-fan-mode": set_fan_mode,
    "set-battery-start": set_battery_start_threshold,
    "set-battery-end": set_battery_end_threshold,
    "set-cooler-boost": set_cooler_boost,
    "set-gpu-mode": set_gpu_mode,
}

ACTIONS_NO_ARG = {
    "get-gpu-mode": get_gpu_mode,
}


def main() -> int:
    args = sys.argv[1:]

    if len(args) == 0:
        print("Użycie: msi_control_helper.py <akcja> [wartość]", file=sys.stderr)
        print(f"Dostępne akcje z argumentem: {', '.join(ACTIONS_WITH_ARG)}", file=sys.stderr)
        print(f"Dostępne akcje bez argumentu: {', '.join(ACTIONS_NO_ARG)}", file=sys.stderr)
        return 1

    action = args[0]

    try:
        if action in ACTIONS_NO_ARG:
            if len(args) != 1:
                raise HelperError(f"Akcja '{action}' nie przyjmuje argumentów.")
            output = ACTIONS_NO_ARG[action]()
            print(output)
            return 0

        if action in ACTIONS_WITH_ARG:
            if len(args) != 2:
                raise HelperError(f"Akcja '{action}' wymaga dokładnie jednej wartości.")
            ACTIONS_WITH_ARG[action](args[1])
            print("OK")
            return 0

        raise HelperError(
            f"Nieznana akcja: '{action}'. "
            f"Dostępne: {', '.join(list(ACTIONS_WITH_ARG) + list(ACTIONS_NO_ARG))}"
        )

    except HelperError as e:
        print(f"BŁĄD: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
