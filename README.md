# MSI Control

Control panel for MSI laptops (tested on **Katana 17 B13VEK / MS-1565**) on Linux.
Manage GPU mode (MSHybrid/mGPU/dGPU), performance profiles, fans, Cooler Boost,
battery (charge limits), a cooling autopilot, and the RGB keyboard backlight.

![UI: GPU MODE, PERFORMANCE, BATTERY, SETTINGS, KEYBOARD RGB, AUTOPILOT, MONITORING]

## Features

- **GPU MODE** — switch between GPU modes (writes to sysfs and HWRS, handles refresh).
- **PERFORMANCE / FAN / COOLER BOOST** — shift modes (Silent/Comfort/Sport/Turbo), fan mode and the loud Cooler Boost.
- **BATTERY** — charge limits (start/stop) through the EC.
- **COOLING AUTOPILOT** — automatically engages Cooler Boost above a temperature threshold.
- **KEYBOARD RGB** — color, zones, breathing, rainbow wave and cycle; works **without root** (via HID).
- **MONITORING** — CPU/GPU temperature and load charts.
- **Autostart + restore** of saved settings after login.
- **Multilingual**: PL / EN / DE / ES (choose in SETTINGS).

## Requirements

- Linux, Python 3.10+
- `PySide6`
- `python-msi-ec` (EC readout) — optional
- `pkexec`, `polkit`
- Root is needed **only** for sysfs/EC operations, which are delegated to a separate
  helper (`/usr/local/bin/msi-control-helper`). RGB works without root.

## Installation

```sh
git clone https://example.invalid/msi-control.git
cd msi-control
pip install PySide6
```

### Helper (sysfs/EC)

Install the helper as root and apply the polkit rule (removes the password prompt for this setup):

```sh
sudo install -m 755 -o root -g root app/helper/msi-control-helper.py /usr/local/bin/msi-control-helper
sudo install -m 644 polkit/10-msi-control.rules /etc/polkit-1/rules.d/msi-control.rules
sudo systemctl restart polkit
```

> **Security**: the helper accepts only a whitelist of actions (`set-shift-mode`,
> `set-fan-mode`, `set-cooler-boost`, `set-battery-start`, `set-battery-end`, ...) and
> never executes raw commands. The polkit rule matches only the exact path
> `/usr/local/bin/msi-control-helper`.

### Launcher (optional)

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

or run it directly:

```sh
python3 app/gui/main_window.py
```

## Usage

```sh
msi-control                    # GUI
msi-control --restore          # restore settings without opening the window (prints to stdout)
msi-control --restore-on-start # GUI + restore after startup (used by autostart)
```

Settings are stored in `~/.config/msi-control/config.json`. The `rgb` section remembers
the last lighting mode; enabling **Autostart** adds an entry to `~/.config/autostart/`.

## Configuration / i18n

Pick the GUI language in the **SETTINGS** section. Translations live in
`app/locales/{pl,en,de,es}.json` — the key is the Polish source string; a missing
translation safely falls back to Polish. A new language = a new JSON file (`pl` is the
default and needs no file).

## How it works (brief)

- `backend/rgb.py` — talks to the keyboard via **HID** (no root needed).
- `backend/msi_ec.py` — EC readout (temperatures, fans) via `python-msi-ec`.
- `backend/nvidia.py` — GPU mode / sysfs writes through the helper.
- `gui/helper_client.py` — runs `pkexec <helper> <action> <value>` in a `QThread` (non-blocking GUI).
- `app/helper/msi-control-helper.py` — root helper with a strict action/whitelist (installed to `/usr/local/bin`).
- `backend/restore.py` — restores saved settings (autostart / `--restore`).

## Tests / development

Without the hardware the app still opens; RGB and sysfs operations require the device.
There are no automated tests — verification is manual.

## License

MIT — see [LICENSE](LICENSE).