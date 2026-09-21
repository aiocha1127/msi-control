"""
Backend do pobierania danych GPU przez `nvidia-smi`.

WAŻNE: nvidia-smi to proces zewnętrzny, który jest stosunkowo "ciężki"
do odpalania (kilkadziesiąt-kilkaset ms). Ten moduł NIE zawiera logiki
cache'owania/throttlingu - to będzie zadaniem warstwy `monitor.py`
(Etap 5), która będzie wołać tę funkcję maks. raz na sekundę z jednego
wątku/timera, a nie za każdym razem gdy GUI się przerysowuje.

Na tym etapie: prosty, pojedynczy odczyt na żądanie.
"""

import shutil
import subprocess
from dataclasses import dataclass

# Kolejność pól w zapytaniu musi się zgadzać z kolejnością parsowania w kodzie.
NVIDIA_SMI_QUERY_FIELDS = [
    "temperature.gpu",
    "utilization.gpu",
    "memory.used",
    "memory.total",
    "fan.speed",
]


class NvidiaSmiNotAvailableError(Exception):
    """Podnoszone, gdy binarka `nvidia-smi` nie jest dostępna."""
    pass


class NvidiaSmiCommandError(Exception):
    """Podnoszone, gdy nvidia-smi zwróci błąd lub nieoczekiwany format danych."""
    pass


@dataclass
class NvidiaGpuStatus:
    temperature_c: int | None
    utilization_percent: int | None
    memory_used_mb: int | None
    memory_total_mb: int | None
    fan_speed_percent: int | None  # nvidia-smi zwraca % PWM, nie RPM (inaczej niż msi-ec)


def is_nvidia_smi_available() -> bool:
    """Sprawdza, czy binarka `nvidia-smi` jest dostępna w PATH."""
    return shutil.which("nvidia-smi") is not None


def _parse_int_or_none(raw: str) -> int | None:
    """
    nvidia-smi czasem zwraca '[Not Supported]' zamiast liczby
    (np. dla fan.speed na laptopach bez sterowalnego wentylatora z poziomu nvidia).
    Traktujemy to jako brak danych, a nie błąd.
    """
    raw = raw.strip()
    try:
        return int(raw)
    except ValueError:
        return None


def get_status(timeout: float = 3.0) -> NvidiaGpuStatus:
    """
    Wykonuje pojedyncze zapytanie do nvidia-smi i zwraca dane GPU.

    Przykładowa komenda:
        nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used,
                    memory.total,fan.speed --format=csv,noheader,nounits
    """
    if not is_nvidia_smi_available():
        raise NvidiaSmiNotAvailableError(
            "Binarka 'nvidia-smi' nie została znaleziona w PATH."
        )

    query = ",".join(NVIDIA_SMI_QUERY_FIELDS)

    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise NvidiaSmiCommandError(f"nvidia-smi przekroczyło limit czasu: {e}")

    if result.returncode != 0:
        raise NvidiaSmiCommandError(
            f"nvidia-smi zwróciło błąd (kod {result.returncode}): {result.stderr.strip()}"
        )

    line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    parts = [p.strip() for p in line.split(",")]

    if len(parts) != len(NVIDIA_SMI_QUERY_FIELDS):
        raise NvidiaSmiCommandError(
            f"Nieoczekiwany format odpowiedzi nvidia-smi: '{line}'"
        )

    temperature, utilization, mem_used, mem_total, fan_speed = parts

    return NvidiaGpuStatus(
        temperature_c=_parse_int_or_none(temperature),
        utilization_percent=_parse_int_or_none(utilization),
        memory_used_mb=_parse_int_or_none(mem_used),
        memory_total_mb=_parse_int_or_none(mem_total),
        fan_speed_percent=_parse_int_or_none(fan_speed),
    )
