"""
Warstwa łącząca GUI z helperem uruchamianym przez pkexec.

Wywołania pkexec blokują (czekają na hasło użytkownika), dlatego
wykonujemy je w osobnym wątku (QThread), żeby GUI się nie zamrażało
w oczekiwaniu na okienko autoryzacji.
"""

from PySide6.QtCore import QThread, Signal

from backend.i18n import tr

HELPER_PATH = "/usr/local/bin/msi-control-helper"


class HelperActionError(Exception):
    """Zgłaszane, gdy wywołanie helpera zakończy się błędem (kod wyjścia != 0)."""
    pass


class HelperActionWorker(QThread):
    """
    Wykonuje jedno wywołanie helpera (`pkexec msi-control-helper <action> <value>`)
    w tle. Emituje finished(success, message) po zakończeniu.
    """

    finished_signal = Signal(bool, str)

    def __init__(self, action: str, value: str | None = None, parent=None):
        super().__init__(parent)
        self.action = action
        self.value = value

    def run(self) -> None:
        import subprocess

        cmd = ["pkexec", HELPER_PATH, self.action]
        if self.value is not None:
            cmd.append(self.value)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # generous - user może się zastanawiać nad hasłem
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.finished_signal.emit(False, tr("Przekroczono limit czasu operacji."))
            return
        except FileNotFoundError:
            self.finished_signal.emit(False, tr("Nie znaleziono programu 'pkexec'."))
            return

        if result.returncode == 0:
            self.finished_signal.emit(True, result.stdout.strip() or "OK")
        else:
            # Kod 126/127 od pkexec zwykle oznacza anulowanie przez usera lub odmowę autoryzacji
            stderr = result.stderr.strip()
            if result.returncode in (126, 127) and not stderr:
                message = tr("Autoryzacja anulowana.")
            else:
                message = stderr or tr("Błąd (kod {rc})", rc=result.returncode)
            self.finished_signal.emit(False, message)
