"""
QR-code based Wireless ADB pairing dialog.

Flow:
  1. Show live webcam preview.
  2. Detect QR code (WIFI:T:ADB;S:<service>;P:<password>;;).
  3. Use mDNS (zeroconf) to find IP:port for that pairing service.
  4. Run `adb pair <ip>:<port>` with the password.
  5. Run `adb connect <ip>:<connect-port>` afterwards.
  6. Save device for auto-reconnect.
"""

import re
import socket
import threading

import cv2
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from zeroconf import ServiceBrowser, Zeroconf

from core import adb_bridge
from core.settings_store import save_paired_device


# ── QR helpers ────────────────────────────────────────────────────────────────

def _parse_qr(data: str) -> tuple[str, str] | None:
    """Parse WIFI:T:ADB;S:<service>;P:<password>;; → (service_name, password)."""
    if "T:ADB" not in data:
        return None
    s = re.search(r"S:([^;]+)", data)
    p = re.search(r"P:([^;]+)", data)
    if s and p:
        return s.group(1), p.group(1)
    return None


# ── mDNS discovery ────────────────────────────────────────────────────────────

class _DiscoverySignals(QObject):
    found = Signal(str, int)   # ip, port
    timeout = Signal()


class _PairingFinder:
    """Browses _adb-tls-pairing._tcp until it finds the target service."""

    def __init__(self, target_service: str, signals: _DiscoverySignals):
        self._target = target_service
        self._signals = signals
        self._done = False
        self._zc = Zeroconf()
        self._browser = ServiceBrowser(
            self._zc, "_adb-tls-pairing._tcp.local.", self
        )
        # Timeout after 15 s
        t = threading.Timer(15.0, self._on_timeout)
        t.daemon = True
        t.start()

    def add_service(self, zc: Zeroconf, type_: str, name: str):
        if self._done:
            return
        info = zc.get_service_info(type_, name)
        if not info:
            return
        # Match by service instance name containing our target
        if self._target.lower() in name.lower():
            self._done = True
            ip = socket.inet_ntoa(info.addresses[0]) if info.addresses else ""
            if ip:
                self._signals.found.emit(ip, info.port)
            self._close()

    def remove_service(self, *_):
        pass

    def update_service(self, *_):
        pass

    def _on_timeout(self):
        if not self._done:
            self._done = True
            self._signals.timeout.emit()
            self._close()

    def _close(self):
        try:
            self._browser.cancel()
            self._zc.close()
        except Exception:
            pass


# ── Camera widget ─────────────────────────────────────────────────────────────

class _CameraPreview(QWidget):
    """Live webcam preview that emits decoded QR data."""

    qr_detected = Signal(str)

    _PREVIEW_W = 400
    _PREVIEW_H = 300

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self._PREVIEW_W, self._PREVIEW_H)

        self._lbl = QLabel(self)
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setFixedSize(self._PREVIEW_W, self._PREVIEW_H)
        self._lbl.setStyleSheet("background:#1a1a1a; color:#555; font-size:13px;")
        self._lbl.setText("Starting camera…")

        self._cap: cv2.VideoCapture | None = None
        self._detector = cv2.QRCodeDetector()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._grab)
        self._active = False

    def start(self):
        self._cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not self._cap.isOpened():
            self._lbl.setText("No webcam detected.\nUse 'Load from image' instead.")
            return
        self._active = True
        self._timer.start(33)  # ~30 fps

    def stop(self):
        self._active = False
        self._timer.stop()
        if self._cap:
            self._cap.release()
            self._cap = None

    def _grab(self):
        if not self._cap:
            return
        ret, frame = self._cap.read()
        if not ret:
            return

        # QR detection
        data, _, _ = self._detector.detectAndDecode(frame)
        if data:
            self.stop()
            self.qr_detected.emit(data)
            return

        # Draw viewfinder guide
        h, w = frame.shape[:2]
        cx, cy, size = w // 2, h // 2, min(w, h) // 2
        cv2.rectangle(frame,
                      (cx - size // 2, cy - size // 2),
                      (cx + size // 2, cy + size // 2),
                      (0, 200, 100), 2)

        # Convert to QPixmap
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = QImage(rgb.data, rgb.shape[1], rgb.shape[0],
                     rgb.shape[1] * 3, QImage.Format_RGB888)
        pix = QPixmap.fromImage(img).scaled(
            self._PREVIEW_W, self._PREVIEW_H,
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._lbl.setPixmap(pix)


# ── Main dialog ────────────────────────────────────────────────────────────────

class QRPairingDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pair via QR Code")
        self.setMinimumWidth(440)
        self.setModal(True)

        self._service_name = ""
        self._password = ""
        self._finder: _PairingFinder | None = None

        self._setup_ui()
        QTimer.singleShot(200, self._camera.start)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # Instructions
        instr = QLabel(
            "On your Pixel:\n"
            "Settings → Developer Options → Wireless debugging\n"
            "→ <b>Pair device with QR code</b>\n\n"
            "Point your webcam at the QR code shown on the phone."
        )
        instr.setTextFormat(Qt.RichText)
        instr.setWordWrap(True)
        instr.setStyleSheet("color:#aaa; font-size:12px;")
        lay.addWidget(instr)

        # Camera preview
        self._camera = _CameraPreview()
        self._camera.qr_detected.connect(self._on_qr_detected)
        lay.addWidget(self._camera, alignment=Qt.AlignHCenter)

        # "Load from image" fallback
        btn_file = QPushButton("📁  Load QR from image file instead…")
        btn_file.clicked.connect(self._load_from_file)
        lay.addWidget(btn_file)

        # Status label
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("font-size:12px; color:#aaa;")
        lay.addWidget(self._status)

        # Manual fallback (hidden until needed)
        self._manual_box = QWidget()
        mlay = QVBoxLayout(self._manual_box)
        mlay.setContentsMargins(0, 0, 0, 0)

        self._manual_status = QLabel(
            "mDNS discovery timed out. Enter details manually:"
        )
        self._manual_status.setStyleSheet("color:#ff9800; font-size:12px;")
        self._manual_status.setWordWrap(True)
        mlay.addWidget(self._manual_status)

        row = QHBoxLayout()
        self._ip_field = QLineEdit()
        self._ip_field.setPlaceholderText("IP address")
        row.addWidget(self._ip_field)
        self._pair_port_field = QSpinBox()
        self._pair_port_field.setRange(1, 65535)
        self._pair_port_field.setValue(37000)
        self._pair_port_field.setPrefix("pair: ")
        row.addWidget(self._pair_port_field)
        self._conn_port_field = QSpinBox()
        self._conn_port_field.setRange(1, 65535)
        self._conn_port_field.setValue(5555)
        self._conn_port_field.setPrefix("conn: ")
        row.addWidget(self._conn_port_field)
        mlay.addLayout(row)

        btn_manual = QPushButton("Pair with these details")
        btn_manual.clicked.connect(self._do_manual_pair)
        mlay.addWidget(btn_manual)

        lay.addWidget(self._manual_box)
        self._manual_box.hide()

        # Close button
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    # ── QR detected ───────────────────────────────────────────────────────────

    def _on_qr_detected(self, data: str):
        parsed = _parse_qr(data)
        if not parsed:
            self._status.setStyleSheet("color:#f44336; font-size:12px;")
            self._status.setText("QR code found but doesn't look like Android pairing QR.\nTry again.")
            QTimer.singleShot(2000, self._camera.start)
            return

        self._service_name, self._password = parsed
        self._status.setStyleSheet("color:#4caf50; font-size:12px;")
        self._status.setText(f"✓ QR decoded! Searching for device via mDNS…")
        self._start_mdns()

    def _load_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select QR code image", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        self._camera.stop()
        img = cv2.imread(path)
        if img is None:
            self._status.setStyleSheet("color:#f44336; font-size:12px;")
            self._status.setText("Could not read image file.")
            return
        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(img)
        if not data:
            self._status.setStyleSheet("color:#f44336; font-size:12px;")
            self._status.setText("No QR code found in image.")
            return
        self._on_qr_detected(data)

    # ── mDNS ─────────────────────────────────────────────────────────────────

    def _start_mdns(self):
        signals = _DiscoverySignals(self)
        signals.found.connect(self._on_service_found)
        signals.timeout.connect(self._on_mdns_timeout)
        self._finder = _PairingFinder(self._service_name, signals)

    def _on_service_found(self, ip: str, pairing_port: int):
        self._status.setText(f"Found device at {ip}:{pairing_port} — pairing…")
        self._do_pair(ip, pairing_port)

    def _on_mdns_timeout(self):
        self._status.setStyleSheet("color:#ff9800; font-size:12px;")
        self._status.setText("mDNS timed out. Enter IP manually below.")
        self._manual_box.show()
        self.adjustSize()

    # ── Pairing ───────────────────────────────────────────────────────────────

    def _do_pair(self, ip: str, pairing_port: int):
        self._status.setText(f"Pairing {ip}:{pairing_port}…")
        self.repaint()

        ok, msg = adb_bridge.pair(ip, pairing_port, self._password)
        if not ok:
            self._status.setStyleSheet("color:#f44336; font-size:12px;")
            self._status.setText(f"Pairing failed: {msg}")
            return

        # After pairing, connect on the adb-tls-connect port (try 5555 default;
        # advanced users can adjust in the manual box)
        connect_port = 5555
        self._status.setText(f"Paired! Connecting to {ip}:{connect_port}…")
        self.repaint()

        ok2, msg2 = adb_bridge.connect(ip, connect_port)
        save_paired_device(ip, connect_port)

        if ok2:
            self._status.setStyleSheet("color:#4caf50; font-size:12px;")
            self._status.setText(f"✓ Connected to {ip}! You can close this dialog.")
        else:
            self._status.setStyleSheet("color:#ff9800; font-size:12px;")
            self._status.setText(
                f"Paired but connect failed ({msg2}).\n"
                f"Try 'adb connect {ip}:{connect_port}' manually."
            )

    def _do_manual_pair(self):
        ip = self._ip_field.text().strip()
        if not ip:
            return
        self._do_pair(ip, self._pair_port_field.value())

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._camera.stop()
        if self._finder:
            self._finder._close()
        super().closeEvent(event)

    def reject(self):
        self._camera.stop()
        if self._finder:
            self._finder._close()
        super().reject()
