"""
Główne okno aplikacji MSI Control.

Etap 3:
- prawdziwe akcje przez helper (pkexec),
- monitoring odświeżany automatycznie co 1 sekundę,
- odczyt i zmiana limitów ładowania baterii.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QScrollArea,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QFrame,
    QPushButton,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QColorDialog,
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtGui import QColor

from backend.msi_ec import (
    read_status,
    is_msi_ec_available,
    MsiEcNotAvailableError,
)

from backend.cardwire import (
    get_status as cardwire_get_status,
    AVAILABLE_GPU_MODES,
    is_cardwire_available,
    CardwireNotAvailableError,
    CardwireCommandError,
)

from backend.nvidia import (
    get_status as nvidia_get_status,
    is_nvidia_smi_available,
    NvidiaSmiNotAvailableError,
    NvidiaSmiCommandError,
)

from backend.rgb import (
    MsiRgbKeyboard,
    is_available as is_rgb_available,
    RAINBOW,
    Ms1565UnavailableError,
    Ms1565CommandError,
)

from backend.settings import save as settings_save, load as settings_load
from backend.i18n import (
    tr,
    load as i18n_load,
    available as i18n_available,
    current_lang as i18n_current_lang,
)
from gui.helper_client import HelperActionWorker
from gui.monitor_chart import MonitorChart


def _rgb_mode_name(pending_label: str) -> str:
    """Mapuje etykietę efektu RGB z GUI na klucz trybu config (restore.py)."""
    label = (pending_label or "").lower()

    if "off" in label:
        return "off"
    if "fala" in label or "tęcza" in label and "cykl" not in label:
        return "wave"
    if "cykl" in label:
        return "cycle"
    if "oddychan" in label:
        return "breathe"
    return "steady"


DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: "Noto Sans", sans-serif;
    font-size: 13px;
}

QFrame#section {
    background-color: #2a2a2a;
    border-radius: 8px;
    padding: 4px;
}

QLabel#sectionTitle {
    font-size: 14px;
    font-weight: bold;
    color: #ffffff;
    padding-bottom: 4px;
}

QLabel#appTitle {
    font-size: 20px;
    font-weight: bold;
    color: #ffffff;
}

QLabel#appSubtitle {
    font-size: 12px;
    color: #888888;
}

QLabel#valueLabel {
    color: #4fc3f7;
    font-weight: bold;
}

QLabel#errorLabel {
    color: #e57373;
}

QLabel#statusBar {
    color: #aaaaaa;
    font-size: 11px;
    padding-top: 4px;
}

QPushButton {
    background-color: #3a3a3a;
    border: 1px solid #4a4a4a;
    border-radius: 6px;
    padding: 6px 12px;
    color: #e0e0e0;
}

QPushButton:hover {
    background-color: #454545;
}

QPushButton:disabled {
    color: #666666;
    background-color: #2f2f2f;
}

QPushButton[active="true"] {
    background-color: #4fc3f7;
    color: #1e1e1e;
    font-weight: bold;
    border: 1px solid #4fc3f7;
}

QComboBox {
    background-color: #3a3a3a;
    border: 1px solid #4a4a4a;
    border-radius: 6px;
    padding: 4px 8px;
    color: #e0e0e0;
}

QSpinBox {
    background-color: #3a3a3a;
    border: 1px solid #4a4a4a;
    border-radius: 6px;
    padding: 4px 8px;
    color: #e0e0e0;
}

QCheckBox {
    color: #e0e0e0;
    spacing: 6px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #4a4a4a;
    background-color: #3a3a3a;
}

QCheckBox::indicator:checked {
    background-color: #4fc3f7;
    border: 1px solid #4fc3f7;
}

QFrame#rgbSwatch {
    background-color: #000000;
    border: 1px solid #4a4a4a;
    border-radius: 4px;
}
"""


def _section_frame() -> QFrame:
    frame = QFrame()
    frame.setObjectName("section")
    return frame


def _refresh_button_style(button: QPushButton, is_active: bool) -> None:
    button.setProperty("active", "true" if is_active else "false")
    button.style().unpolish(button)
    button.style().polish(button)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("MSI Control")
        self.setMinimumWidth(440)

        self._worker: HelperActionWorker | None = None
        self._all_action_buttons: list = []

        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            want_w = min(620, avail.width() - 40)
            want_h = min(780, avail.height() - 40)
            self.resize(want_w, want_h)
        else:
            self.resize(620, 780)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setCentralWidget(self.scroll)

        self._build_ui()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._periodic_refresh)
        self.refresh_timer.start(1000)

        self.refresh_all()

    # =========================================================
    # Budowa UI (wywoływana przy starcie i po zmianie języka)
    # =========================================================

    def _build_ui(self) -> None:
        central = QWidget()
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setSpacing(12)
        self.main_layout.setContentsMargins(16, 16, 16, 16)

        self._all_action_buttons = []
        self.gpu_mode_buttons = {}
        self.shift_mode_buttons = {}
        self.monitoring_labels = {}

        # --- Tytuł ---

        title = QLabel(tr("MSI CONTROL"))
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignCenter)

        subtitle = QLabel("Katana 17 B13VEK")
        subtitle.setObjectName("appSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)

        self.main_layout.addWidget(title)
        self.main_layout.addWidget(subtitle)

        # --- GPU ---

        self.gpu_mode_buttons: dict = {}
        self.gpu_mode_current_label = QLabel()

        self.main_layout.addWidget(
            self._build_gpu_mode_section()
        )

        # --- Performance ---

        self.shift_mode_buttons: dict = {}
        self.fan_mode_combo = QComboBox()
        self.cooler_boost_button = QPushButton()

        self.main_layout.addWidget(
            self._build_performance_section()
        )

        # --- Battery ---

        self.battery_start_spin = QSpinBox()
        self.battery_end_spin = QSpinBox()

        self.battery_start_spin.setRange(0, 100)
        self.battery_end_spin.setRange(0, 100)

        self.battery_start_spin.setSuffix(" %")
        self.battery_end_spin.setSuffix(" %")

        self.battery_start_button = QPushButton("Apply")
        self.battery_end_button = QPushButton("Apply")

        self.battery_start_button.clicked.connect(
            self._on_battery_start_clicked
        )

        self.battery_end_button.clicked.connect(
            self._on_battery_end_clicked
        )

        self.main_layout.addWidget(
            self._build_battery_section()
        )

        # --- Keyboard RGB ---

        self.rgb_target_combo = QComboBox()
        self.rgb_target_combo.addItems(
            ["Cała klawiatura", "Strefa 1", "Strefa 2", "Strefa 3", "Strefa 4"]
        )

        self.rgb_current_color = (0, 0, 0)
        self._rgb_pending_label = ""
        self._rgb_pending_display = ""
        self.rgb_status_label = QLabel("")
        self.rgb_status_label.setObjectName("statusBar")
        self.rgb_status_label.setWordWrap(True)
        self.rgb_status_label.setAlignment(Qt.AlignCenter)

        self.rgb_color_swatch = QFrame()
        self.rgb_color_swatch.setObjectName("rgbSwatch")
        self.rgb_color_swatch.setFixedSize(22, 22)

        self.main_layout.addWidget(
            self._build_rgb_section()
        )

        # --- Autopilot chłodzenia ---

        self.autopilot_check = QCheckBox("Autopilot chłodzenia")
        self.autopilot_check.toggled.connect(self._on_autopilot_toggled)

        self.autopilot_threshold = QSpinBox()
        self.autopilot_threshold.setRange(70, 95)
        self.autopilot_threshold.setValue(82)
        self.autopilot_threshold.setSuffix(" °C")
        self.autopilot_threshold.setToolTip(
            "Gdy CPU lub GPU przekroczy ten próg, wentylatory przechodzą na max."
        )

        self.autopilot_status_label = QLabel("")
        self.autopilot_status_label.setObjectName("statusBar")
        self.autopilot_status_label.setWordWrap(True)

        self._autopilot_engaged = False
        self._last_cpu_temp: int | None = None
        self._last_gpu_temp: int | None = None
        self._last_cpu_fan: int | None = None
        self._last_gpu_fan: int | None = None

        self.main_layout.addWidget(
            self._build_autopilot_section()
        )

        # --- Ustawienia / autostart ---

        self.autostart_check = QCheckBox(
            "Autostart + przywracanie ustawień po zalogowaniu"
        )
        self.settings_save_btn = QPushButton("Zapisz teraz")
        self.settings_save_btn.clicked.connect(self._on_settings_save_clicked)
        self.settings_status_label = QLabel("")
        self.settings_status_label.setObjectName("statusBar")
        self.settings_status_label.setWordWrap(True)

        self.main_layout.addWidget(
            self._build_settings_section()
        )

        # --- Monitoring ---

        self.monitoring_labels: dict = {}

        self.main_layout.addWidget(
            self._build_monitoring_section()
        )

        # --- Status ---

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusBar")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignCenter)

        self.main_layout.addWidget(self.status_label)
        self.main_layout.addStretch()

        self.scroll.setWidget(central)

    def _rebuild_ui(self) -> None:
        self._build_ui()
        self.refresh_all()

    def _on_language_changed(self, index: int) -> None:
        code = list(i18n_available())[index]
        if code == i18n_current_lang():
            return
        i18n_load(code)
        try:
            cfg = settings_load()
            cfg["lang"] = code
            settings_save(cfg)
        except OSError:
            pass
        self.language_combo.blockSignals(True)
        QTimer.singleShot(0, self._rebuild_ui)

    # =========================================================
    # Budowa sekcji
    # =========================================================

    def _build_gpu_mode_section(self) -> QFrame:
        frame = _section_frame()
        layout = QVBoxLayout(frame)

        section_title = QLabel(tr("GPU MODE"))
        section_title.setObjectName("sectionTitle")
        layout.addWidget(section_title)

        if not is_cardwire_available():
            layout.addWidget(QLabel(tr("cardwire niedostępne")))
            return frame

        buttons_row = QHBoxLayout()

        for mode in AVAILABLE_GPU_MODES:
            btn = QPushButton(mode.capitalize())

            btn.clicked.connect(
                lambda checked=False, m=mode:
                self._on_gpu_mode_clicked(m)
            )

            buttons_row.addWidget(btn)

            self.gpu_mode_buttons[mode] = btn
            self._all_action_buttons.append(btn)

        layout.addLayout(buttons_row)

        current_row = QHBoxLayout()
        current_row.addWidget(QLabel(tr("Aktualny tryb:")))
        current_row.addStretch()

        self.gpu_mode_current_label.setObjectName("valueLabel")
        current_row.addWidget(self.gpu_mode_current_label)

        layout.addLayout(current_row)

        return frame

    def _build_performance_section(self) -> QFrame:
        frame = _section_frame()
        layout = QVBoxLayout(frame)

        section_title = QLabel(
            tr("PERFORMANCE / FAN / COOLER BOOST")
        )
        section_title.setObjectName("sectionTitle")
        layout.addWidget(section_title)

        if not is_msi_ec_available():
            layout.addWidget(QLabel(tr("msi-ec niedostępne")))
            return frame

        try:
            status = read_status()

            available_shift_modes = (
                status.available_shift_modes
            )

            available_fan_modes = (
                status.available_fan_modes
            )

        except MsiEcNotAvailableError:
            available_shift_modes = []
            available_fan_modes = []

        # Performance mode

        perf_row = QHBoxLayout()

        for mode in available_shift_modes:
            btn = QPushButton(mode.capitalize())

            btn.clicked.connect(
                lambda checked=False, m=mode:
                self._on_shift_mode_clicked(m)
            )

            perf_row.addWidget(btn)

            self.shift_mode_buttons[mode] = btn
            self._all_action_buttons.append(btn)

        layout.addLayout(perf_row)

        # Fan mode

        fan_row = QHBoxLayout()
        fan_row.addWidget(QLabel(tr("Fan mode:")))

        self.fan_mode_combo.addItems(
            [m.capitalize() for m in available_fan_modes]
        )

        self.fan_mode_combo.currentTextChanged.connect(
            self._on_fan_mode_changed
        )

        fan_row.addWidget(self.fan_mode_combo)

        self._all_action_buttons.append(
            self.fan_mode_combo
        )

        layout.addLayout(fan_row)

        # Cooler Boost

        cooler_row = QHBoxLayout()

        cooler_row.addWidget(
            QLabel(tr("Cooler Boost:"))
        )

        cooler_row.addStretch()

        self.cooler_boost_button.clicked.connect(
            self._on_cooler_boost_clicked
        )

        cooler_row.addWidget(
            self.cooler_boost_button
        )

        self._all_action_buttons.append(
            self.cooler_boost_button
        )

        layout.addLayout(cooler_row)

        return frame

    def _build_battery_section(self) -> QFrame:
        frame = _section_frame()
        layout = QVBoxLayout(frame)

        section_title = QLabel(tr("BATTERY"))
        section_title.setObjectName("sectionTitle")
        layout.addWidget(section_title)

        # Start charging

        start_row = QHBoxLayout()

        start_row.addWidget(
            QLabel(tr("Start charging:"))
        )

        start_row.addStretch()

        start_row.addWidget(
            self.battery_start_spin
        )

        start_row.addWidget(
            self.battery_start_button
        )

        layout.addLayout(start_row)

        # Stop charging

        end_row = QHBoxLayout()

        end_row.addWidget(
            QLabel(tr("Stop charging:"))
        )

        end_row.addStretch()

        end_row.addWidget(
            self.battery_end_spin
        )

        end_row.addWidget(
            self.battery_end_button
        )

        layout.addLayout(end_row)

        self._all_action_buttons.append(
            self.battery_start_spin
        )

        self._all_action_buttons.append(
            self.battery_end_spin
        )

        self._all_action_buttons.append(
            self.battery_start_button
        )

        self._all_action_buttons.append(
            self.battery_end_button
        )

        return frame

    def _build_settings_section(self) -> QFrame:
        frame = _section_frame()
        layout = QVBoxLayout(frame)

        section_title = QLabel(tr("USTAWIENIA / AUTOSTART"))
        section_title.setObjectName("sectionTitle")
        layout.addWidget(section_title)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel(tr("Język / Language:")))
        self.language_combo = QComboBox()
        self.language_combo.addItems(list(i18n_available().values()))
        self.language_combo.setCurrentIndex(
            list(i18n_available()).index(i18n_current_lang())
        )
        self.language_combo.currentIndexChanged.connect(
            self._on_language_changed
        )
        lang_row.addWidget(self.language_combo)
        lang_row.addStretch()
        layout.addLayout(lang_row)

        layout.addWidget(self.autostart_check)

        save_row = QHBoxLayout()
        save_row.addWidget(self.settings_save_btn)
        save_row.addWidget(self.settings_status_label)
        save_row.addStretch()
        layout.addLayout(save_row)

        note = QLabel(
            tr("Przycisk trwale zapisuje tryb mocy, wentylatory, baterię, "
                "autopilot oraz RGB do ~/.config/msi-control/config.json "
                "i - po zaznaczeniu autostartu - tworzy wpis "
                "~/.config/autostart/msi-control.desktop, który po zalogowaniu "
                "przywraca te ustawienia (wymaga reguły polkit).")
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            "color: #666666; font-size: 11px; font-style: italic;"
        )
        layout.addWidget(note)

        return frame

    def _build_rgb_section(self) -> QFrame:
        frame = _section_frame()
        layout = QVBoxLayout(frame)

        section_title = QLabel(tr("KEYBOARD RGB (MS-1565, USB HID)"))
        section_title.setObjectName("sectionTitle")
        layout.addWidget(section_title)

        if not is_rgb_available():
            layout.addWidget(
                QLabel(tr("Klawiatura MysticLight MS-1565 nie została wykryta"))
            )
            return frame

        row_picker = QHBoxLayout()

        pick_btn = QPushButton(tr("Wybierz kolor..."))
        pick_btn.clicked.connect(self._on_rgb_pick_color)

        self.rgb_apply_btn = QPushButton(tr("Zastosuj"))
        self.rgb_apply_btn.clicked.connect(self._on_rgb_apply)

        row_picker.addWidget(pick_btn)
        row_picker.addWidget(self.rgb_color_swatch)
        row_picker.addStretch()
        row_picker.addWidget(self.rgb_target_combo)
        row_picker.addWidget(self.rgb_apply_btn)

        layout.addLayout(row_picker)

        presets_grid = QGridLayout()
        presets_grid.setSpacing(6)

        preset_buttons = [
            ("Biały", (255, 255, 255)),
            ("Czerwony", (255, 0, 0)),
            ("Zielony", (0, 255, 0)),
            ("Niebieski", (0, 120, 255)),
            ("Żółty", (255, 200, 0)),
            ("Niebiesko-fioletowy", (120, 0, 255)),
        ]
        for idx, (name, color) in enumerate(preset_buttons):
            btn = QPushButton(tr(name))
            btn.clicked.connect(
                lambda checked=False, c=color: self._on_rgb_preset(c)
            )
            presets_grid.addWidget(btn, idx // 3, idx % 3)

        breathe_btn = QPushButton(tr("Oddychanie"))
        breathe_btn.clicked.connect(self._on_rgb_breathe)
        presets_grid.addWidget(breathe_btn, 2, 0)

        off_btn = QPushButton(tr("Off"))
        off_btn.clicked.connect(self._on_rgb_off)
        presets_grid.addWidget(off_btn, 2, 1)

        layout.addLayout(presets_grid)

        effects_row = QHBoxLayout()

        self.rgb_speed_spin = QSpinBox()
        self.rgb_speed_spin.setRange(300, 1200)
        self.rgb_speed_spin.setSingleStep(100)
        self.rgb_speed_spin.setValue(900)
        self.rgb_speed_spin.setSuffix(" cs")
        self.rgb_speed_spin.setToolTip(
            tr("Czas trwania cyklu animacji (centys); mniej = szybciej")
        )

        wave_btn = QPushButton(tr("Fala"))
        wave_btn.clicked.connect(self._on_rgb_wave)
        cycle_btn = QPushButton(tr("Cykl"))
        cycle_btn.clicked.connect(self._on_rgb_cycle)

        effects_row.addWidget(QLabel(tr("Tęcza:")))
        effects_row.addWidget(wave_btn)
        effects_row.addWidget(cycle_btn)
        effects_row.addWidget(self.rgb_speed_spin)
        effects_row.addStretch()

        layout.addLayout(effects_row)

        current_row = QHBoxLayout()
        current_row.addWidget(QLabel(tr("Stan:")))
        current_row.addStretch()
        self.rgb_status_label.setObjectName("valueLabel")
        current_row.addWidget(self.rgb_status_label)
        layout.addLayout(current_row)

        note = QLabel(
            tr("Sterowanie bezpośrednio przez USB HID - nie wymaga hasła.")
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            "color: #666666; font-size: 11px; font-style: italic;"
        )
        layout.addWidget(note)

        return frame

    def _build_autopilot_section(self) -> QFrame:
        frame = _section_frame()
        layout = QVBoxLayout(frame)

        section_title = QLabel(tr("AUTOPILOT CHŁODZENIA"))
        section_title.setObjectName("sectionTitle")
        layout.addWidget(section_title)

        row = QHBoxLayout()

        row.addWidget(self.autopilot_check)

        row.addSpacing(8)

        row.addWidget(QLabel(tr("Próg:")))
        row.addWidget(self.autopilot_threshold)

        row.addStretch()

        self.autopilot_status_label.setObjectName("valueLabel")
        row.addWidget(self.autopilot_status_label)

        layout.addLayout(row)

        note = QLabel(
            tr("Gdy CPU lub GPU przekroczy próg, włącza cooler boost (max obroty); "
                "po ostygnięciu o 8°C wraca do normalnej pracy.")
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            "color: #666666; font-size: 11px; font-style: italic;"
        )
        layout.addWidget(note)

        return frame

    def _build_monitoring_section(self) -> QFrame:
        frame = _section_frame()
        layout = QVBoxLayout(frame)

        section_title = QLabel(tr("MONITORING"))
        section_title.setObjectName("sectionTitle")
        layout.addWidget(section_title)

        for key, label_text in [
            ("cpu_temp", "CPU temp"),
            ("cpu_fan", "CPU fan"),
            ("gpu_fan", "GPU fan"),
            ("gpu_temp", "GPU temp"),
            ("gpu_usage", "GPU usage"),
            ("vram", "VRAM"),
        ]:
            row = QHBoxLayout()

            row.addWidget(
                QLabel(tr(label_text))
            )

            row.addStretch()

            value_label = QLabel("—")
            value_label.setObjectName("valueLabel")

            row.addWidget(value_label)

            self.monitoring_labels[key] = value_label

            layout.addLayout(row)

        chart_row = QHBoxLayout()
        self.monitor_chart = MonitorChart()
        clear_btn = QPushButton(tr("Wyczyść wykres"))
        clear_btn.clicked.connect(self.monitor_chart.clear)
        clear_btn.setMaximumWidth(140)
        self.monitor_chart.setMinimumHeight(190)

        chart_wrapper = QVBoxLayout()
        chart_wrapper.addWidget(self.monitor_chart)
        chart_wrapper.addWidget(clear_btn, alignment=Qt.AlignRight)

        layout.addLayout(chart_wrapper)

        note = QLabel(
            tr("Odświeżanie automatyczne co 1s")
        )

        note.setWordWrap(True)

        note.setStyleSheet(
            "color: #666666; "
            "font-size: 11px; "
            "font-style: italic;"
        )

        layout.addWidget(note)

        return frame

    # =========================================================
    # Odświeżanie
    # =========================================================

    def refresh_all(self) -> None:
        """Pełny refresh - GPU/performance/monitoring + bateria. Wołany przy starcie i po akcji."""
        self._refresh_gpu_mode()
        self._refresh_performance()
        self._refresh_battery()
        self._refresh_monitoring()

    def _periodic_refresh(self) -> None:
        """
        Refresh wołany co sekundę przez timer. CELOWO pomija baterię:
        próg ładowania nie zmienia się sam z siebie, więc odpytywanie go
        co sekundę tylko przeszkadzałoby w ustawianiu wartości w SpinBoxie
        (kursor/wpisywana liczba byłyby nadpisywane w trakcie edycji).
        Bateria jest odświeżana tylko przy starcie i po udanym Apply
        (patrz refresh_all / _on_action_finished).
        """
        self._refresh_gpu_mode()
        self._refresh_performance()
        self._refresh_monitoring()
        self._update_thermal_autopilot()

    def _refresh_gpu_mode(self) -> None:
        if not is_cardwire_available():
            return

        try:
            status = cardwire_get_status()
            current = status.current_mode

        except (
            CardwireNotAvailableError,
            CardwireCommandError,
        ) as e:

            self.gpu_mode_current_label.setText(tr("błąd"))
            self._set_status(
                tr("Błąd odczytu GPU mode: {e}", e=e),
                is_error=True,
            )

            return

        self.gpu_mode_current_label.setText(
            current or tr("nieznany")
        )

        for mode, btn in self.gpu_mode_buttons.items():
            _refresh_button_style(
                btn,
                is_active=(mode == current),
            )

    def _refresh_performance(self) -> None:
        if not is_msi_ec_available():
            return

        try:
            status = read_status()

        except MsiEcNotAvailableError as e:
            self._set_status(
                tr("Błąd odczytu msi-ec: {e}", e=e),
                is_error=True,
            )
            return

        for mode, btn in self.shift_mode_buttons.items():
            _refresh_button_style(
                btn,
                is_active=(mode == status.shift_mode),
            )

        if status.fan_mode is not None:
            idx = self.fan_mode_combo.findText(
                status.fan_mode.capitalize()
            )

            if idx >= 0:
                self.fan_mode_combo.blockSignals(True)
                self.fan_mode_combo.setCurrentIndex(idx)
                self.fan_mode_combo.blockSignals(False)

        is_on = status.cooler_boost == "on"

        self.cooler_boost_button.setText(
            "ON" if is_on else "OFF"
        )

        _refresh_button_style(
            self.cooler_boost_button,
            is_active=is_on,
        )

    def _refresh_battery(self) -> None:
        if not is_msi_ec_available():
            return

        try:
            status = read_status()

        except MsiEcNotAvailableError:
            return

        # hasFocus(): nie nadpisuj pola, w którym user właśnie coś ustawia
        # (np. kliknął Apply dla "start", a w tym czasie edytuje "end")
        if (
            status.battery_start_threshold is not None
            and not self.battery_start_spin.hasFocus()
        ):
            self.battery_start_spin.blockSignals(True)
            self.battery_start_spin.setValue(
                status.battery_start_threshold
            )
            self.battery_start_spin.blockSignals(False)

        if (
            status.battery_end_threshold is not None
            and not self.battery_end_spin.hasFocus()
        ):
            self.battery_end_spin.blockSignals(True)
            self.battery_end_spin.setValue(
                status.battery_end_threshold
            )
            self.battery_end_spin.blockSignals(False)

    def _refresh_monitoring(self) -> None:
        if is_msi_ec_available():
            try:
                ec_status = read_status()

                self.monitoring_labels["cpu_temp"].setText(
                    f"{ec_status.cpu_temperature}°C"
                    if ec_status.cpu_temperature is not None
                    else "—"
                )

                self.monitoring_labels["cpu_fan"].setText(
                    f"{ec_status.cpu_fan_speed} RPM"
                    if ec_status.cpu_fan_speed is not None
                    else "—"
                )

                self._last_cpu_fan = ec_status.cpu_fan_speed
                self._last_gpu_fan = ec_status.gpu_fan_speed

                self._last_cpu_temp = ec_status.cpu_temperature
                self._last_gpu_temp = ec_status.gpu_temperature

                self.monitoring_labels["gpu_fan"].setText(
                    f"{ec_status.gpu_fan_speed} RPM"
                    if ec_status.gpu_fan_speed is not None
                    else "—"
                )

            except MsiEcNotAvailableError:
                pass

        if is_nvidia_smi_available():
            try:
                nv_status = nvidia_get_status()

                self.monitoring_labels["gpu_temp"].setText(
                    f"{nv_status.temperature_c}°C"
                    if nv_status.temperature_c is not None
                    else "—"
                )

                if nv_status.temperature_c is not None:
                    self._last_gpu_temp = nv_status.temperature_c

                self.monitoring_labels["gpu_usage"].setText(
                    f"{nv_status.utilization_percent}%"
                    if nv_status.utilization_percent is not None
                    else "—"
                )

                vram = "—"

                if (
                    nv_status.memory_used_mb is not None
                    and nv_status.memory_total_mb is not None
                ):
                    vram = (
                        f"{nv_status.memory_used_mb} / "
                        f"{nv_status.memory_total_mb} MB"
                    )

                self.monitoring_labels["vram"].setText(vram)

            except (
                NvidiaSmiNotAvailableError,
                NvidiaSmiCommandError,
            ):
                pass

        sample = {
            "cpu_temp": self._last_cpu_temp,
            "gpu_temp": self._last_gpu_temp,
            "cpu_fan": self._last_cpu_fan,
            "gpu_fan": self._last_gpu_fan,
        }
        self.monitor_chart.push(sample)

    # =========================================================
    # Status
    # =========================================================

    def _set_status(
        self,
        message: str,
        is_error: bool = False,
    ) -> None:

        self.status_label.setText(message)

        self.status_label.setStyleSheet(
            "color: #e57373;"
            if is_error
            else
            "color: #81c784;"
        )

    # =========================================================
    # Akcje
    # =========================================================

    def _set_buttons_enabled(
        self,
        enabled: bool,
    ) -> None:

        for widget in self._all_action_buttons:
            widget.setEnabled(enabled)

    def _run_action(
        self,
        action: str,
        value: str,
    ) -> None:

        if (
            self._worker is not None
            and self._worker.isRunning()
        ):
            return

        self._set_buttons_enabled(False)

        self._set_status(
            tr("Wykonywanie: {action} {value}...", action=action, value=value)
        )

        self._worker = HelperActionWorker(
            action,
            value,
        )

        self._worker.finished_signal.connect(
            self._on_action_finished
        )

        self._worker.start()

    def _on_action_finished(
        self,
        success: bool,
        message: str,
    ) -> None:

        self._set_buttons_enabled(True)

        if success:
            self._set_status(tr("Gotowe."))
            self.refresh_all()

        else:
            self._set_status(
                tr("Błąd: {message}", message=message),
                is_error=True,
            )

    # =========================================================
    # GPU
    # =========================================================

    def _on_gpu_mode_clicked(
        self,
        mode: str,
    ) -> None:

        self._run_action(
            "set-gpu-mode",
            mode,
        )

    # =========================================================
    # Performance
    # =========================================================

    def _on_settings_save_clicked(self) -> None:
        """Zapisuje bieżący stan do config.json (+ autostart .desktop)."""
        cfg = self._collect_current_state()

        try:
            settings_save(cfg)
        except OSError as e:
            self.settings_status_label.setText(tr("błąd zapisu: {e}", e=e))
            return

        self._sync_autostart(cfg.get("autostart", False))

        suffix = tr(", autostart OK") if cfg.get("autostart") else ""
        self.settings_status_label.setText(tr("zapisano") + suffix)
        self._period_of = ()

    def _collect_current_state(self) -> dict:
        """Składa dict stanu z aktualnych widgetów (spójny z restore.py)."""
        cfg: dict = {}

        if hasattr(self, "shift_mode_buttons"):
            for mode, btn in self.shift_mode_buttons.items():
                if btn.property("active") == "true":
                    cfg["shift_mode"] = mode
                    break

        if hasattr(self, "fan_mode_combo"):
            cfg["fan_mode"] = self.fan_mode_combo.currentText().lower()

        if hasattr(self, "cooler_boost_button"):
            cfg["cooler_boost"] = (
                self.cooler_boost_button.text() == "ON"
            )

        if hasattr(self, "battery_start_spin"):
            cfg["battery_start"] = self.battery_start_spin.value()
        if hasattr(self, "battery_end_spin"):
            cfg["battery_end"] = self.battery_end_spin.value()

        if hasattr(self, "autopilot_check"):
            cfg["autopilot_enabled"] = self.autopilot_check.isChecked()
        if hasattr(self, "autopilot_threshold"):
            cfg["autopilot_threshold"] = self.autopilot_threshold.value()

        cfg["rgb"] = self._collect_rgb_state()
        cfg["autostart"] = (
            self.autostart_check.isChecked()
            if hasattr(self, "autostart_check")
            else False
        )

        return cfg

    def _collect_rgb_state(self) -> dict:
        """Stan RGB do zapisu: tryb, kolor(e), szybkość, strefa."""
        rgb = {
            "mode": _rgb_mode_name(self._rgb_pending_label),
            "color": list(self.rgb_current_color),
            "zone": (
                self.rgb_target_combo.currentIndex()
                if hasattr(self, "rgb_target_combo")
                else 0
            ),
            "speed_cs": (
                self.rgb_speed_spin.value()
                if hasattr(self, "rgb_speed_spin")
                else 900
            ),
        }

        pending = self._rgb_pending_label
        if "tęcza" in pending:
            rgb["colors"] = [list(c) for c in RAINBOW]

        return rgb

    def _sync_autostart(self, enabled: bool) -> None:
        """Tworzy/usuwa ~/.config/autostart/msi-control.desktop."""
        desktop_dir = Path.home() / ".config" / "autostart"
        desktop_file = desktop_dir / "msi-control.desktop"

        if not enabled:
            if desktop_file.exists():
                desktop_file.unlink(missing_ok=True)
            return

        desktop_dir.mkdir(parents=True, exist_ok=True)
        launcher = Path.home() / ".local" / "bin" / "msi-control"
        if not launcher.exists():
            import shutil

            shutil.rmtree(desktop_file, ignore_errors=True)
            raise OSError(
                "brak launcher a ~/.local/bin/msi-control"
            )

        desktop_file.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=MSI Control\n"
            f"Comment={tr('Przywracanie ustawień MSI po zalogowaniu')}\n"
            f"Exec={launcher} --restore\n"
            "Terminal=false\n"
            "Hidden=false\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )

    def _on_shift_mode_clicked(
        self,
        mode: str,
    ) -> None:

        self._run_action(
            "set-shift-mode",
            mode,
        )

    def _on_fan_mode_changed(
        self,
        text: str,
    ) -> None:

        self._run_action(
            "set-fan-mode",
            text.lower(),
        )

    def _on_cooler_boost_clicked(self) -> None:
        new_value = (
            "off"
            if self.cooler_boost_button.text() == "ON"
            else "on"
        )

        self._run_action(
            "set-cooler-boost",
            new_value,
        )

    # =========================================================
    # Battery
    # =========================================================

    def _on_battery_start_clicked(self) -> None:
        value = self.battery_start_spin.value()
        end_value = self.battery_end_spin.value()

        if value >= end_value:
            self._set_status(
                tr(
                    "Błąd: próg 'start' ({value}%) musi być mniejszy niż 'stop' ({end_value}%).",
                    value=value,
                    end_value=end_value,
                ),
                is_error=True,
            )
            return

        self._run_action(
            "set-battery-start",
            str(value),
        )

    def _on_battery_end_clicked(self) -> None:
        value = self.battery_end_spin.value()
        start_value = self.battery_start_spin.value()

        if value <= start_value:
            self._set_status(
                tr(
                    "Błąd: próg 'stop' ({value}%) musi być większy niż 'start' ({start_value}%).",
                    value=value,
                    start_value=start_value,
                ),
                is_error=True,
            )
            return

        self._run_action(
            "set-battery-end",
            str(value),
        )

    # =========================================================
    # Keyboard RGB
    # =========================================================

    def _on_rgb_pick_color(self) -> None:
        color = QColor(*self.rgb_current_color)
        chosen = QColorDialog.getColor(
            color,
            self,
            tr("Kolor podświetlenia"),
        )
        if not chosen.isValid():
            return

        self.rgb_current_color = (
            chosen.red(),
            chosen.green(),
            chosen.blue(),
        )
        self._set_rgb_swatch(self.rgb_current_color)

    def _set_rgb_pending(self, template: str, **fmt) -> None:
        """Zapisuje label efektu: kanoniczny (PL, do mapowania trybu) + wersję tłumaczoną."""
        self._rgb_pending_label = template.format_map(fmt) if fmt else template
        try:
            self._rgb_pending_display = tr(template, **fmt)
        except (KeyError, ValueError, IndexError):
            self._rgb_pending_display = self._rgb_pending_label

    def _on_rgb_preset(self, color: tuple) -> None:
        self.rgb_current_color = color
        self._set_rgb_swatch(color)
        self._set_rgb_pending(f"rgb({color[0]},{color[1]},{color[2]})")
        self._apply_rgb(MsiRgbKeyboard.set_color_all, color)

    def _on_rgb_breathe(self) -> None:
        r, g, b = self.rgb_current_color
        self._set_rgb_pending("oddychanie rgb({r},{g},{b})", r=r, g=g, b=b)
        self._apply_rgb(MsiRgbKeyboard.set_breathe, self.rgb_current_color)

    def _on_rgb_off(self) -> None:
        self._set_rgb_pending("off")
        self._apply_rgb(MsiRgbKeyboard.turn_off, None)

    def _on_rgb_wave(self) -> None:
        speed = self.rgb_speed_spin.value()
        self._set_rgb_pending("Fala tęcza ({speed} cs)", speed=speed)
        self._apply_rgb(MsiRgbKeyboard.set_wave, (RAINBOW, speed))

    def _on_rgb_cycle(self) -> None:
        speed = self.rgb_speed_spin.value()
        self._set_rgb_pending("Cykl tęcza ({speed} cs)", speed=speed)
        self._apply_rgb(MsiRgbKeyboard.set_cycle, (RAINBOW, speed))

    def _on_rgb_apply(self) -> None:
        color = self.rgb_current_color
        target = self.rgb_target_combo.currentIndex()
        self._set_rgb_swatch(color)

        if target == 0:
            self._set_rgb_pending(
                f"rgb({color[0]},{color[1]},{color[2]})"
            )
            self._apply_rgb(MsiRgbKeyboard.set_color_all, color)
        else:
            zone = target - 1
            self._set_rgb_pending(
                "strefa {target}: rgb({color[0]},{color[1]},{color[2]})",
                target=target,
                color=color,
            )

            def apply_zone(kb: MsiRgbKeyboard) -> None:
                kb.set_color_zone(zone, *color)

            self._apply_rgb(apply_zone, None)

    def _set_rgb_swatch(self, color: tuple) -> None:
        r, g, b = color
        self.rgb_color_swatch.setStyleSheet(
            f"background-color: rgb({r},{g},{b});"
        )

    def _apply_rgb(self, operation, color) -> None:
        """
        Wykonuje operację RGB w tle (QThread), żeby GUI nie blokowało się
        w oczekiwaniu na desktruktor urządzenia HID.
        """
        if not is_rgb_available():
            self.rgb_status_label.setText(tr("brak urządzenia"))
            return

        try:
            if color is not None:
                def runner() -> None:
                    with MsiRgbKeyboard() as kb:
                        operation(kb, *color)
            else:
                def runner() -> None:
                    with MsiRgbKeyboard() as kb:
                        operation(kb)
        except Exception as e:
            self.rgb_status_label.setText(tr("błąd: {e}", e=e))
            return

        class RgbThread(QThread):
            done = Signal(bool, str)

            def __init__(self, fn):
                super().__init__()
                self._fn = fn

            def run(self):
                try:
                    self._fn()
                    self.done.emit(True, "")
                except Exception as e:
                    self.done.emit(False, str(e))

        self._rgb_thread = RgbThread(runner)
        self._rgb_thread.done.connect(self._on_rgb_done)
        self._rgb_thread.start()

    def _on_rgb_done(self, success: bool, message: str) -> None:
        if not success:
            self.rgb_status_label.setText(tr("błąd: {e}", e=message))
            return

        self.rgb_status_label.setText(self._rgb_pending_display)

    # =========================================================
    # Autopilot chłodzenia
    # =========================================================

    def _on_autopilot_toggled(self, enabled: bool) -> None:
        if not enabled and self._autopilot_engaged:
            self._autopilot_engaged = False
            self.autopilot_status_label.setText(tr("normalnie"))
            self._run_action("set-cooler-boost", "off")
            return

        self._update_thermal_autopilot()

    def _update_thermal_autopilot(self) -> None:
        if not self.autopilot_check.isChecked():
            return

        if (
            self._worker is not None
            and self._worker.isRunning()
        ):
            return

        temps = [
            t
            for t in (self._last_cpu_temp, self._last_gpu_temp)
            if t is not None
        ]
        if not temps:
            return

        peak = max(temps)
        threshold = self.autopilot_threshold.value()

        if not self._autopilot_engaged and peak >= threshold:
            self._autopilot_engaged = True
            self.autopilot_status_label.setText(
                tr("max obroty ({peak}°C)", peak=peak)
            )
            self._run_action("set-cooler-boost", "on")
            return

        if self._autopilot_engaged and peak <= threshold - 8:
            self._autopilot_engaged = False
            self.autopilot_status_label.setText(tr("normalnie"))
            self._run_action("set-cooler-boost", "off")


def main() -> int:
    from backend.settings import load as _settings_load
    from backend.i18n import load as _i18n_load

    _i18n_load(_settings_load().get("lang", "pl"))

    if "--restore" in sys.argv:
        from backend.restore import restore

        for section, result in restore():
            print(f"{section}: {result}")
        return 0

    app = QApplication(sys.argv)

    app.setStyleSheet(
        DARK_STYLESHEET
    )

    window = MainWindow()
    window.show()

    if "--restore-on-start" in sys.argv:
        from PySide6.QtCore import QTimer

        def _do_restore() -> None:
            from backend.restore import restore

            window.status_label.setText(
                tr("Przywracanie zapisanych ustawień...")
            )
            for section, result in restore():
                window.status_label.setText(
                    f"{section}: {result}"
                )

        QTimer.singleShot(1500, _do_restore)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
