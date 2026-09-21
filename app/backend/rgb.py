"""
Backend do sterowania podświetleniem klawiatury MSI przez HID.

Klawiatura RGB notebooka MSI Katana 17 B13VEK to osobny kontroler USB HID
(MysticLight MS-1565, VID 0x1462, PID 0x1601) - NIE jest częścią Embedded
Controller, dlatego nie ma jej w module msi-ec.

Protokół (reversowany przez OpenRGB, MR !2619, plik FeaturePacket_MS1565):
    komunikacja = 64-bajtowe feature reports z report ID 0x02,
    wysyłane w dwóch krokach:
      1) wybór strefy:  [0x02, 0x01, zone_mask, ... 64 bajty]
      2) pakiet koloru: FeaturePacket_MS1565 (patrz _build_color_packet)

Sterowanie idzie przez /dev/hidraw* właściwego urządzenia. Na tym systemie
hidraw ma uprawnienia rw dla użytkownika, więc NIE wymaga sudo ani polkit.

Zero zależności zewnętrznych (czysty fcntl/ioctl, bez pip install).
"""

import fcntl
import os
from pathlib import Path

VID = 0x1462
PID = 0x1601

HIDRAW_CLASS = Path("/sys/class/hidraw")

# Tryby (wg OpenRGB - MS-1565)
MODE_OFF = 0
MODE_STEADY = 1
MODE_BREATHING = 2
MODE_CYCLE = 3
MODE_WAVE = 4

# Maski stref: klawiatura dzieli się na 4 strefy + "wszystkie"
ZONE_1, ZONE_2, ZONE_3, ZONE_4, ZONE_ALL = 0x01, 0x02, 0x04, 0x08, 0x0F
ZONE_MASKS = [ZONE_1, ZONE_2, ZONE_3, ZONE_4]

# Paleta tęczy używana dla efektów fala / cykl
RAINBOW = [
    (255, 0, 0),
    (255, 165, 0),
    (255, 255, 0),
    (0, 255, 0),
    (0, 191, 255),
    (0, 0, 255),
    (138, 43, 226),
]

# Prędkość animacji: w centys (s * 100), jak w OpenRGB/wrapperze
SPEED_MIN_CS = 300
SPEED_MAX_CS = 1200
SPEED_DEFAULT_CS = 900

_IOC_WRITE = 1
_IOC_READ = 2


def _hid_ioc(size: int, nr: int) -> int:
    """
    Buduje numer ioctl HIDIOCSFEATURE/HIDIOCGFEATURE.

    Ze wzoru z linux/hidraw.h (64-bit):
        HIDIOCSFEATURE(len)  = _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x06, len)
        HIDIOCGFEATURE(len)  = _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x07, len)
    Ważny detal: kierunek to WRITE|READ (3), nie sam WRITE - inaczej
    urządzenie odrzuca ioctl z EINVAL.
    """
    return (
        ((_IOC_WRITE | _IOC_READ) << 30)
        | (ord("H") << 8)
        | (nr << 0)
        | (size << 16)
    )


HIDIOCGFEATURE64 = _hid_ioc(64, 0x07)
HIDIOCSFEATURE64 = _hid_ioc(64, 0x06)

_REPORT_SIZE = 64


class Ms1565UnavailableError(Exception):
    """Urządzenie MysticLight MS-1565 nie zostało znalezione w systemie."""
    pass


class Ms1565CommandError(Exception):
    """Błąd zapisu/odczytu feature report (ioctl)."""
    pass


def find_device_path() -> str | None:
    """
    Znajduje /dev/hidraw* dla MysticLight MS-1565 (1462:1601),
    skanując /sys/class/hidraw/*/device/uevent.
    """
    try:
        entries = sorted(HIDRAW_CLASS.iterdir())
    except OSError:
        return None

    for hidraw in entries:
        uevent = hidraw / "device" / "uevent"
        try:
            text = uevent.read_text()
        except OSError:
            continue

        for line in text.splitlines():
            if not line.startswith("HID_ID="):
                continue
            # Format: HID_ID=<bus>:<vid>:<pid>
            parts = line.split("=", 1)[1].split(":")
            if len(parts) < 3:
                continue
            try:
                vid, pid = int(parts[1], 16), int(parts[2], 16)
            except ValueError:
                continue
            if vid == VID and pid == PID:
                return f"/dev/{hidraw.name}"

    return None


def is_available() -> bool:
    return find_device_path() is not None


class MsiRgbKeyboard:
    """Obiekt sterujący podświetleniem klawiatury (jednorazowe otwarcie)."""

    def __init__(self):
        self._fd: int | None = None
        self._path: str | None = None
        # Ostatnio ustawiony stan - urządzenie nie pozwala go odczytać,
        # więc trzymamy własną kopię do wyświetlania w GUI.
        self._last: dict = {
            "mode": MODE_OFF,
            "color": (0, 0, 0),
            "zones": [None] * 4,
        }

    # ---------------- zarządzanie otwarciem ----------------

    def open(self) -> None:
        path = find_device_path()
        if path is None:
            raise Ms1565UnavailableError(
                "Nie znaleziono MysticLight MS-1565 (1462:1601) w /sys/class/hidraw. "
                "Sprawdź `lsusb` - urządzenie musi być widoczne."
            )
        try:
            # O_RDWR bo feature reports bywają odczytywane zwrotnie
            fd = os.open(path, os.O_RDWR)
        except OSError as e:
            raise Ms1565CommandError(f"Nie udało się otworzyć {path}: {e}")
        self._fd = fd
        self._path = path

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
        self._fd = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc_info):
        self.close()

    def is_open(self) -> bool:
        return self._fd is not None

    # ---------------- niskopoziomowy HID ----------------

    def _send(self, data: bytes) -> None:
        """
        Wysyła feature report (report ID 0x02) przez HIDIOCSFEATURE.

        Dokładnie tak robi OpenRGB (MR !2619 / hidapi) dla MS-1565:
        deskryptor tego urządzenia deklaruje report ID 0x02 również
        jako FEATURE (drugi usage), więc ten kanał jest poprawny.
        """
        if self._fd is None:
            raise Ms1565CommandError("Urządzenie nie jest otwarte.")
        try:
            fcntl.ioctl(self._fd, HIDIOCSFEATURE64, data)
        except OSError as e:
            raise Ms1565CommandError(
                f"Zapis feature report nie powiódł się ({self._path}): {e}"
            )

    def _receive(self) -> bytes | None:
        """
        Odczytuje feature report (HIDIOCGFEATURE).

        Zwraca None, jeśli urządzenie nie odpowiedziało - GUI i tak
        trzyma własny stan.
        """
        if self._fd is None:
            return None
        buf = bytearray(_REPORT_SIZE)
        try:
            fcntl.ioctl(self._fd, HIDIOCGFEATURE64, buf)
        except OSError:
            return None
        return bytes(buf)

    # ---------------- budowa pakietów ----------------

    @staticmethod
    def _select_zone_packet(zone_mask: int) -> bytes:
        buf = bytearray(_REPORT_SIZE)
        buf[0] = 0x02  # report ID
        buf[1] = 0x01  # komenda "wybór strefy"
        buf[2] = zone_mask
        return bytes(buf)

    @staticmethod
    def _color_packet(
        mode: int,
        colors: list[tuple[int, int, int]],
        speed_cs: int = 900,
        wave_dir: int = 0,
    ) -> bytes:
        """
        FeaturePacket_MS1565 (64 bajty):
          [0] report_id  = 0x02
          [1] packet_id  = 0x02
          [2] mode
          [3] speed2     (niski bajt prędkości w centys, s * 100)
          [4] speed1     (wysoki bajt prędkości w centys)
          [5][6]         = 0x00
          [7]            = 0x0F (stała z OpenRGB)
          [8]            = 0x01 (stała z OpenRGB)
          [9] wave_dir   = 0x00 (R->L) / 0x01 (L->R)

        Keyframes: kolory są rozprowadzane równomiernie w czasie 0..100,
        a ostatni keyframe zamyka pętlę powrotem do pierwszego koloru
        (identycznie jak testowany wrapper Python dla MS-1565).
        """
        buf = bytearray(_REPORT_SIZE)
        buf[0] = 0x02
        buf[1] = 0x02
        buf[2] = mode

        speed_cs = max(SPEED_MIN_CS, min(SPEED_MAX_CS, speed_cs))
        buf[3] = speed_cs & 0xFF
        buf[4] = (speed_cs >> 8) & 0xFF

        buf[7] = 0x0F
        buf[8] = 0x01
        buf[9] = wave_dir & 0xFF

        colors = [c for c in colors if c is not None][:9]
        num = len(colors)

        for i, (r, g, b) in enumerate(colors):
            off = 10 + i * 4
            buf[off] = (i * 100) // max(1, num)
            buf[off + 1] = int(r) & 0xFF
            buf[off + 2] = int(g) & 0xFF
            buf[off + 3] = int(b) & 0xFF

        if num:
            off = 10 + num * 4
            buf[off] = 100
            buf[off + 1] = int(colors[0][0]) & 0xFF
            buf[off + 2] = int(colors[0][1]) & 0xFF
            buf[off + 3] = int(colors[0][2]) & 0xFF

        return bytes(buf)

    # ---------------- operacje na kolorach ----------------

    def _apply_to_mask(self, zone_mask: int, mode: int, *args) -> None:
        self._send(self._select_zone_packet(zone_mask))
        self._send(self._color_packet(mode, *args))

    def set_color_all(self, r: int, g: int, b: int) -> None:
        """Ustawia całą klawiaturę na jeden kolor (steady)."""
        self._apply_to_mask(ZONE_ALL, MODE_STEADY, [(r, g, b)])
        self._last.update({"mode": MODE_STEADY, "color": (r, g, b),
                           "zones": [(r, g, b)] * 4})

    def set_color_zone(self, zone_index: int, r: int, g: int, b: int) -> None:
        """Ustawia jedną strefę (0-3) na jeden kolor (steady)."""
        if not 0 <= zone_index < len(ZONE_MASKS):
            raise ValueError("zone_index musi być w zakresie 0-3")
        self._apply_to_mask(ZONE_MASKS[zone_index], MODE_STEADY, [(r, g, b)])
        zones = list(self._last["zones"])
        zones[zone_index] = (r, g, b)
        self._last.update({"mode": MODE_STEADY, "color": (r, g, b), "zones": zones})

    def set_zones(self, colors: list[tuple[int, int, int] | None]) -> None:
        """Ustawia osobne kolory dla wszystkich 4 stref naraz (None = pominąć)."""
        if len(colors) != len(ZONE_MASKS):
            raise ValueError("colors musi mieć dokładnie 4 wpisy")
        zones = list(self._last["zones"])
        for i, color in enumerate(colors):
            if color is not None:
                self.set_color_zone(i, *color)
                zones[i] = color
        first = next((c for c in colors if c is not None), (0, 0, 0))
        self._last.update({"mode": MODE_STEADY, "color": first, "zones": zones})

    def set_breathe(
        self,
        r: int,
        g: int,
        b: int,
        speed_cs: int = 750,
    ) -> None:
        """Oddychający kolor na całej klawiaturze."""
        self._apply_to_mask(ZONE_ALL, MODE_BREATHING, [(r, g, b)], speed_cs)
        self._last.update({"mode": MODE_BREATHING, "color": (r, g, b),
                           "zones": [(r, g, b)] * 4})

    def set_cycle(
        self,
        colors: list[tuple[int, int, int]],
        speed_cs: int = 900,
    ) -> None:
        """Cykl kolorów (przejścia tętna przez zadaną paletę)."""
        if not colors:
            raise ValueError("colors nie może być puste")
        self._apply_to_mask(ZONE_ALL, MODE_CYCLE, colors, speed_cs)
        self._last.update({"mode": MODE_CYCLE, "color": colors[0],
                           "zones": [colors[0]] * 4})

    def set_wave(
        self,
        colors: list[tuple[int, int, int]],
        speed_cs: int = 900,
        direction: int = 0,
    ) -> None:
        """Fala kolorów przesuwająca się po klawiaturze."""
        if not colors:
            raise ValueError("colors nie może być puste")
        self._apply_to_mask(ZONE_ALL, MODE_WAVE, colors, speed_cs, direction)
        self._last.update({"mode": MODE_WAVE, "color": colors[0],
                           "zones": [colors[0]] * 4})

    def turn_off(self) -> None:
        self._apply_to_mask(ZONE_ALL, MODE_OFF, [(0, 0, 0)])
        self._last.update({"mode": MODE_OFF, "color": (0, 0, 0),
                           "zones": [None] * 4})

    # ---------------- podgląd stanu ----------------

    def read_status(self) -> dict:
        """
        Zwraca opis stanu podświetlenia (na bazie ostatnio ustawionych
        wartości + best-effort odczyt z urządzenia, jeśli zechce odpowiedzieć).
        """
        mode_names = {
            MODE_OFF: "off",
            MODE_STEADY: "steady",
            MODE_BREATHING: "breathe",
            MODE_CYCLE: "cycle",
            MODE_WAVE: "wave",
        }
        status = {
            "mode": mode_names.get(self._last["mode"], "unknown"),
            "color": self._last["color"],
            "zones": self._last["zones"],
        }

        raw = self._receive()
        if raw is None or len(raw) < 14:
            return status

        mode = raw[2]
        probe = (raw[11], raw[12], raw[13])
        status["probe_mode"] = mode_names.get(mode, f"mode={mode}")
        status["probe_color"] = probe

        return status