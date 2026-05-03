"""USB connection instructions dialog."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from core import adb_bridge
from core.worker import run_async


class UsbDialog(QDialog):
    """Step-by-step guide for connecting via USB debugging."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connect via USB")
        self.setMinimumWidth(440)
        self.setModal(True)
        self._setup_ui()

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 20, 20, 20)

        title = QLabel("🔌  Connect your Pixel 8a via USB")
        title.setStyleSheet("font-size:15px; font-weight:bold; color:#E2E8F0;")
        lay.addWidget(title)

        # Instruction steps
        steps = [
            ("1", "Connect your phone with a USB data cable."),
            ("2", "On your phone, unlock the screen."),
            ("3", 'Tap <b>Allow</b> on the “Allow USB debugging?” prompt.'),
            ("4", "Your device appears automatically in the device list above."),
        ]
        for num, text in steps:
            row = QHBoxLayout()
            badge = QLabel(num)
            badge.setFixedSize(24, 24)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(
                "background:#5B21B6; color:#EDE9FE; border-radius:12px;"
                "font-size:12px; font-weight:bold;"
            )
            row.addWidget(badge)
            lbl = QLabel(text)
            lbl.setTextFormat(Qt.RichText)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#CBD5E1; font-size:13px;")
            row.addWidget(lbl, 1)
            lay.addLayout(row)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#2A2A35;")
        lay.addWidget(sep)

        # Troubleshooting section
        trouble_title = QLabel("Troubleshooting")
        trouble_title.setStyleSheet("font-size:12px; font-weight:bold; color:#94A3B8;")
        lay.addWidget(trouble_title)

        tips = [
            "• Enable <b>Developer Options</b>: Settings → About phone → tap Build number 7×",
            "• Enable <b>USB Debugging</b> inside Developer Options",
            "• Try a different USB cable (some cables are charge-only)",
            "• If device shows as <i>Unauthorized</i>, revoke USB debugging on phone and retry",
        ]
        for tip in tips:
            lbl = QLabel(tip)
            lbl.setTextFormat(Qt.RichText)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#64748B; font-size:12px;")
            lay.addWidget(lbl)

        # Status
        self._status = QLabel("")
        self._status.setStyleSheet("font-size:12px;")
        self._status.setWordWrap(True)
        lay.addWidget(self._status)

        # Buttons
        btn_row = QHBoxLayout()
        self._btn_refresh = QPushButton("🔄  Refresh Device List")
        self._btn_refresh.setProperty("accent", True)
        self._btn_refresh.clicked.connect(self._refresh)
        btn_row.addWidget(self._btn_refresh)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)

    def _refresh(self):
        self._status.setStyleSheet("font-size:12px; color:#94A3B8;")
        self._status.setText("Scanning for USB devices…")
        self._btn_refresh.setEnabled(False)
        run_async(adb_bridge.list_devices, on_done=self._on_devices_found)

    def _on_devices_found(self, devices):
        self._btn_refresh.setEnabled(True)
        if devices is None:
            devices = []
        usb_devices = [d for d in devices if d.serial and ":" not in d.serial]
        if usb_devices:
            names = ", ".join(d.display_name for d in usb_devices)
            self._status.setStyleSheet("font-size:12px; color:#4caf50; font-weight:bold;")
            self._status.setText(f"✓ Found: {names}")
        else:
            self._status.setStyleSheet("font-size:12px; color:#ef5350;")
            self._status.setText(
                "No USB devices found. Make sure the cable is connected and "
                "you tapped Allow on the phone."
            )
