"""
Backend do komunikacji z modułem kernela msi-ec przez sysfs.

Odczyt stanu MSI Katana 17 B13VEK.
"""

from pathlib import Path
from dataclasses import dataclass, field

MSI_EC_ROOT = Path("/sys/devices/platform/msi-ec")
BATTERY_ROOT = next(
    Path("/sys/class/power_supply").glob("BAT*"),
    Path("/sys/class/power_supply/BAT0"),
)


class MsiEcNotAvailableError(Exception):
    """Podnoszone, gdy katalog msi-ec nie istnieje."""
    pass


def _read(path: Path) -> str | None:
    """
    Bezpieczny odczyt pliku sysfs.
    """
    try:
        return path.read_text().strip()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _read_list(path: Path) -> list[str]:
    """Odczyt listy wartości oddzielonych spacjami/newline."""
    raw = _read(path)
    if raw is None:
        return []
    return raw.split()


def is_msi_ec_available() -> bool:
    """Sprawdza, czy moduł msi-ec jest dostępny."""
    return MSI_EC_ROOT.is_dir()


@dataclass
class MsiEcStatus:
    """Migawka pełnego stanu odczytanego z msi-ec."""

    # Bateria
    battery_start_threshold: int | None = None
    battery_end_threshold: int | None = None

    # Performance / fan
    shift_mode: str | None = None
    available_shift_modes: list[str] = field(default_factory=list)

    fan_mode: str | None = None
    available_fan_modes: list[str] = field(default_factory=list)

    cooler_boost: str | None = None

    # Temperatury i obroty
    cpu_temperature: int | None = None
    cpu_fan_speed: int | None = None

    gpu_temperature: int | None = None
    gpu_fan_speed: int | None = None

    # Dodatkowe
    webcam: str | None = None
    webcam_block: str | None = None
    fw_version: str | None = None
    fw_release_date: str | None = None


def _read_int(path: Path) -> int | None:
    raw = _read(path)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def read_status() -> MsiEcStatus:
    """
    Odczytuje pełny stan msi-ec oraz limitów ładowania baterii.
    """
    if not is_msi_ec_available():
        raise MsiEcNotAvailableError(
            f"Katalog {MSI_EC_ROOT} nie istnieje. "
            f"Czy moduł msi_ec jest załadowany? "
            f"(lsmod | grep msi_ec)"
        )

    return MsiEcStatus(
        # Bateria
        battery_start_threshold=_read_int(
            BATTERY_ROOT / "charge_control_start_threshold"
        ),
        battery_end_threshold=_read_int(
            BATTERY_ROOT / "charge_control_end_threshold"
        ),

        # Performance
        shift_mode=_read(MSI_EC_ROOT / "shift_mode"),
        available_shift_modes=_read_list(
            MSI_EC_ROOT / "available_shift_modes"
        ),

        fan_mode=_read(MSI_EC_ROOT / "fan_mode"),
        available_fan_modes=_read_list(
            MSI_EC_ROOT / "available_fan_modes"
        ),

        cooler_boost=_read(MSI_EC_ROOT / "cooler_boost"),

        # Temperatury i obroty
        cpu_temperature=_read_int(
            MSI_EC_ROOT / "cpu" / "realtime_temperature"
        ),
        cpu_fan_speed=_read_int(
            MSI_EC_ROOT / "cpu" / "realtime_fan_speed"
        ),

        gpu_temperature=_read_int(
            MSI_EC_ROOT / "gpu" / "realtime_temperature"
        ),
        gpu_fan_speed=_read_int(
            MSI_EC_ROOT / "gpu" / "realtime_fan_speed"
        ),

        # Dodatkowe
        webcam=_read(MSI_EC_ROOT / "webcam"),
        webcam_block=_read(MSI_EC_ROOT / "webcam_block"),
        fw_version=_read(MSI_EC_ROOT / "fw_version"),
        fw_release_date=_read(MSI_EC_ROOT / "fw_release_date"),
    )
