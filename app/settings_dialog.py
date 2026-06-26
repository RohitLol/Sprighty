from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)
from PySide6.QtCore import Qt

from core.settings_store import ScrcpySettings, load_scrcpy_settings, save_scrcpy_settings


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Video Settings")
        self.setMinimumWidth(340)
        self.setModal(True)
        self._cfg = load_scrcpy_settings()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── USB ───────────────────────────────────────────────────────────────
        usb_label = QLabel("USB")
        usb_label.setStyleSheet("font-weight:600; margin-top:4px;")
        layout.addWidget(usb_label)

        usb_form = QFormLayout()
        usb_form.setSpacing(8)

        self._max_size = QSpinBox()
        self._max_size.setRange(480, 2160)
        self._max_size.setSingleStep(120)
        self._max_size.setValue(self._cfg.max_size)
        self._max_size.setSuffix(" px")
        usb_form.addRow("Max Resolution:", self._max_size)

        self._bitrate = QComboBox()
        for br in ["1M", "2M", "4M", "6M", "8M", "12M"]:
            self._bitrate.addItem(br)
        idx = self._bitrate.findText(self._cfg.bitrate)
        if idx >= 0:
            self._bitrate.setCurrentIndex(idx)
        usb_form.addRow("Video Bitrate:", self._bitrate)

        self._max_fps = QSpinBox()
        self._max_fps.setRange(15, 120)
        self._max_fps.setSingleStep(5)
        self._max_fps.setValue(self._cfg.max_fps)
        self._max_fps.setSuffix(" fps")
        usb_form.addRow("Max FPS:", self._max_fps)

        layout.addLayout(usb_form)

        # ── WiFi ──────────────────────────────────────────────────────────────
        wifi_label = QLabel("WiFi")
        wifi_label.setStyleSheet("font-weight:600; margin-top:10px;")
        layout.addWidget(wifi_label)

        wifi_form = QFormLayout()
        wifi_form.setSpacing(8)

        self._wifi_max_size = QSpinBox()
        self._wifi_max_size.setRange(480, 2160)
        self._wifi_max_size.setSingleStep(120)
        self._wifi_max_size.setValue(self._cfg.wifi_max_size)
        self._wifi_max_size.setSuffix(" px")
        wifi_form.addRow("Max Resolution:", self._wifi_max_size)

        self._wifi_bitrate = QComboBox()
        for br in ["1M", "2M", "4M", "6M", "8M"]:
            self._wifi_bitrate.addItem(br)
        idx = self._wifi_bitrate.findText(self._cfg.wifi_bitrate)
        if idx >= 0:
            self._wifi_bitrate.setCurrentIndex(idx)
        wifi_form.addRow("Video Bitrate:", self._wifi_bitrate)

        self._wifi_max_fps = QSpinBox()
        self._wifi_max_fps.setRange(15, 120)
        self._wifi_max_fps.setSingleStep(5)
        self._wifi_max_fps.setValue(self._cfg.wifi_max_fps)
        self._wifi_max_fps.setSuffix(" fps")
        wifi_form.addRow("Max FPS:", self._wifi_max_fps)

        layout.addLayout(wifi_form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        cfg = ScrcpySettings(
            max_size=self._max_size.value(),
            bitrate=self._bitrate.currentText(),
            max_fps=self._max_fps.value(),
            wifi_max_fps=self._wifi_max_fps.value(),
            wifi_max_size=self._wifi_max_size.value(),
            wifi_bitrate=self._wifi_bitrate.currentText(),
        )
        save_scrcpy_settings(cfg)
        self.accept()
