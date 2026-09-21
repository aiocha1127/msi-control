"""
Backend do komunikacji z narzędziem `cardwire` (zarządzanie trybem GPU).

Na tym etapie: TYLKO ODCZYT (`cardwire get`). Zapis (`cardwire set ...`)
zostanie dodany w kroku, w którym budujemy helper z uprawnieniami roota.

Potwierdzone na sprzęcie (MSI Katana 17 B13VEK, RTX 4050):
- `cardwire get` nie wymaga sudo
- dostępne tryby wg `cardwire set --help`: integrated, hybrid, manual, smart
"""

import shutil
import subprocess
from dataclasses import dataclass

# Tryby potwierdzone przez `cardwire set --help` na tym sprzęcie.
# Trzymamy to jako stałą, żeby GUI miało z czego budować przyciski,
# ale przy odczycie i tak polegamy na realnym outpucie komendy.
AVAILABLE_GPU_MODES = ["integrated", "hybrid", "manual", "smart"]


class CardwireNotAvailableError(Exception):
    """Podnoszone, gdy binarka `cardwire` nie jest zainstalowana / nie ma jej w PATH."""
    pass


class CardwireCommandError(Exception):
    """Podnoszone, gdy komenda cardwire zwróci błąd (kod wyjścia != 0)."""
    pass


@dataclass
class CardwireStatus:
    current_mode: str | None
    raw_output: str  # pełny output `cardwire get`, przydatny do debugowania w GUI


def is_cardwire_available() -> bool:
    """Sprawdza, czy binarka `cardwire` jest dostępna w PATH."""
    return shutil.which("cardwire") is not None


def _run_cardwire(args: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
    """
    Uruchamia `cardwire` z podanymi argumentami.
    NIE przepuszcza dowolnego stringa - args to zawsze konkretna,
    z góry zdefiniowana lista argumentów (np. ["get"], nigdy user input).
    """
    if not is_cardwire_available():
        raise CardwireNotAvailableError(
            "Binarka 'cardwire' nie została znaleziona w PATH."
        )

    try:
        return subprocess.run(
            ["cardwire", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise CardwireCommandError(f"Komenda cardwire przekroczyła limit czasu: {e}")


def get_status() -> CardwireStatus:
    """
    Odczytuje aktualny tryb GPU przez `cardwire get`.

    Przykładowy output cardwire (potwierdzony):
        Current Mode: Manual
        Available Mode: hybrid, manual
    """
    result = _run_cardwire(["get"])

    if result.returncode != 0:
        raise CardwireCommandError(
            f"`cardwire get` zwróciło błąd (kod {result.returncode}): {result.stderr.strip()}"
        )

    raw = result.stdout.strip()
    current_mode = None

    for line in raw.splitlines():
        if line.lower().startswith("current mode:"):
            current_mode = line.split(":", 1)[1].strip().lower()
            break

    return CardwireStatus(current_mode=current_mode, raw_output=raw)
