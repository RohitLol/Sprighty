from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)
from PySide6.QtCore import Qt

from core.settings_store import ScrcpySettings, load_scrcpy_settings, save_scrcpy_settings


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Video Settings")
        self.setMinimumWidth(320)
        self.setModal(True)
        self._cfg = load_scrcpy_settings()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self._max_size = QSpinBox()
        self._max_size.setRange(480, 2160)
        self._max_size.setSingleStep(120)
        self._max_size.setValue(self._cfg.max_size)
        self._max_size.setSuffix(" px")
        form.addRow("Max Resolution:", self._max_size)

        self._bitrate = QComboBox()
        for br in ["1M", "2M", "4M", "6M", "8M", "12M"]:
            self._bitrate.addItem(br)
        idx = self._bitrate.findText(self._cfg.bitrate)
        if idx >= 0:
            self._bitrate.setCurrentIndex(idx)
        form.addRow("Video Bitrate:", self._bitrate)

        self._max_fps = QSpinBox()
        self._max_fps.setRange(15, 120)
        self._max_fps.setSingleStep(5)
        self._max_fps.setValue(self._cfg.max_fps)
        self._max_fps.setSuffix(" fps")
        form.addRow("Max FPS:", self._max_fps)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        cfg = ScrcpySettings(
            max_size=self._max_size.value(),
            bitrate=self._bitrate.currentText(),
            max_fps=self._max_fps.value(),
        )
        save_scrcpy_settings(cfg)
        self.accept()
