# MSI Control

Panel sterowania dla laptopów MSI (testowany na **Katana 17 B13VEK / MS-1565**) pod systemami Linux.
Pozwala zarządzać trybem GPU (MSHybrid/mGPU/dGPU), profilami wydajności, wentylatorami,
Cooler Boost, baterią (limity ładowania), autopilotem chłodzenia oraz podświetleniem klawiatury RGB.

![UI: GPU MODE, PERFORMANCE, BATTERY, SETTINGS, KEYBOARD RGB, AUTOPILOT, MONITORING]

## Funkcje

- **GPU MODE** — przełączanie między trybami (zapis do sysfs i HWRS, obsługa odświeżania).
- **PERFORMANCE / FAN / COOLER BOOST** — tryby shift (Silent/Comfort/Sport/Turbo), tryb wentylatorów oraz głośny tryb Cooler Boost.
- **BATTERY** — limity ładowania (start/stop) przez EC.
- **AUTOPILOT CHŁODZENIA** — automatyczne włączanie Cooler Boost powyżej progu temperatury.
- **KEYBOARD RGB** — kolor, strefy, oddychanie, fala i cykl tęczy; działa **bez roota** (przez HID).
- **MONITORING** — wykresy temperatury CPU/GPU oraz obciążenia.
- **Autostart + przywracanie** zapisanych ustawień po zalogowaniu.
- **Wielojęzyczność**: PL / EN / DE / ES (wybór języka w USTAWIENIA).

## Wymagania

- Linux, Python 3.10+
- `PySide6`
- `python-msi-ec` (odczyt EC) — opcjonalnie
- `pkexec`, `polkit`
- Root potrzebny **tylko** do operacji w sysfs/EC, które wykonuje osobny helper
  (`/usr/local/bin/msi-control-helper`). RGB działa bez roota.

## Instalacja

```sh
git clone https://example.invalid/msi-control.git
cd msi-control
pip install PySide6
```

### Helper (sysfs/EC)

Skopiuj helper jako root i zainstaluj regułę polkit (usuwa okienko hasła dla tej konfiguracji):

```sh
sudo install -m 755 -o root -g root app/helper/msi-control-helper.py /usr/local/bin/msi-control-helper
sudo install -m 644 polkit/10-msi-control.rules /etc/polkit-1/rules.d/msi-control.rules
sudo systemctl restart polkit
```

> **Bezpieczeństwo**: helper przyjmuje wyłącznie białą listę akcji (`set-shift-mode`,
> `set-fan-mode`, `set-cooler-boost`, `set-battery-start`, `set-battery-end`, ...) i nie
> wykonuje surowych komend. Reguła polkit dotyczy tylko dokładnej ścieżki
> `/usr/local/bin/msi-control-helper`.

### Launcher (opcjonalnie)

```sh
mkdir -p ~/.local/bin
cat > ~/.local/bin/msi-control <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$HOME/.local/share/msi-control"
exec python3 "$APP_DIR/app/gui/main_window.py" "$@"
EOF
chmod +x ~/.local/bin/msi-control
```

lub uruchom wprost:

```sh
python3 app/gui/main_window.py
```

## Użytkowanie

```sh
msi-control                    # GUI
msi-control --restore          # przywróć ustawienia bez otwierania okna (print do stdout)
msi-control --restore-on-start # GUI + przywrócenie po starcie (używane przez autostart)
```

Ustawienia zapisywane są w `~/.config/msi-control/config.json`. Sekcja `rgb` zapamiętuje
ostatni tryb podświetlenia; włączenie **Autostart** dodaje wpis w `~/.config/autostart/`.

## Konfiguracja / i18n

Język GUI wybiera się w sekcji **USTAWIENIA**. Tłumaczenia leżą w
`app/locales/{pl,en,de,es}.json` — kluczem jest polski tekst źródłowy; brak tłumaczenia
bezpiecznie wraca do polskiego. Nowy język = nowy plik JSON (`pl` jest domyślny i nie
wymaga pliku).

## Jak to działa (skrót)

- `backend/rgb.py` — komunikacja z klawiaturą przez **HID** (root niepotrzebny).
- `backend/msi_ec.py` — odczyt EC (temperatury, obroty) przez `python-msi-ec`.
- `backend/nvidia.py` — tryb GPU / zapis do sysfs przez helper.
- `gui/helper_client.py` — wywołania `pkexec <helper> <action> <value>` w `QThread` (GUI bez blokady).
- `app/helper/msi-control-helper.py` — helper roota ze sztywną whitelistą akcji (instalowany do `/usr/local/bin`).
- `backend/restore.py` — przywracanie zapisanych ustawień (autostart / `--restore`).

## Testy / rozwój

Bez urządzenia aplikacja graficznie się otwiera; operacje RGB i sysfs wymagają sprzętu.
Kod nie zawiera testów automatycznych — do weryfikacji ręcznej.

## Licencja

MIT — patrz [LICENSE](LICENSE).