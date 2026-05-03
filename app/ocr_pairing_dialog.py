"""
OCR-based wireless pairing dialog.

Flow:
  1. Show webcam preview.
  2. User holds phone up showing:
       Settings → Developer Options → Wireless Debugging
       → Pair device with pairing code
     (phone shows: IP address, port, and 6-digit code)
  3. EasyOCR scans frames every 600ms in a background thread.
  4. When IP + port + 6-digit code are all detected, show confirmation.
  5. User confirms (or edits) → adb pair → adb connect → done.
"""

import re
import threading

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core import adb_bridge
from core.settings_store import save_paired_device


# ── Regex helpers ─────────────────────────────────────────────────────────────

_RE_IP_PORT = re.compile(
    r"(\d{1,3}[.,]\d{1,3}[.,]\d{1,3}[.,]\d{1,3})\s*[:\s]\s*(\d{4,5})"
)
_RE_CODE = re.compile(r"\b(\d{6})\b")


def _clean_ip(raw: str) -> str:
    """Fix common OCR mistakes: commas instead of dots."""
    return raw.replace(",", ".")


def _extract(texts: list[str]) -> tuple[str, int, str] | None:
    """Return (ip, port, code) if all three are found across the text lines."""
    joined = " ".join(texts)
    ip_m = _RE_IP_PORT.search(joined)
    if not ip_m:
        return None
    ip = _clean_ip(ip_m.group(1))
    port = int(ip_m.group(2))

    # 6-digit code — exclude the port itself
    candidates = _RE_CODE.findall(joined)
    code = next((c for c in candidates if int(c) != port), None)
    if not code:
        return None

    return ip, port, code


# ── Background OCR worker ─────────────────────────────────────────────────────

class _OCRWorker(QThread):
    """Runs EasyOCR on frames posted via process(). Emits results signal."""

    results_ready = Signal(list, np.ndarray)   # (detections, frame)
    ready = Signal()                            # reader initialised
    init_failed = Signal(str)

    def __init__(self):
        super().__init__()
        self._reader = None
        self._pending_frame = None
        self._lock = threading.Lock()
        self._busy = False

    # Called from main thread; starts the thread if not running
    def init_reader(self):
        self.start()

    def process(self, frame: np.ndarray):
        if self._reader is None or self._busy:
            return
        with self._lock:
            self._pending_frame = frame.copy()
        self._busy = True
        # Wake up a one-shot thread for this frame
        t = threading.Thread(target=self._run_ocr, daemon=True)
        t.start()

    def run(self):
        """Initialise EasyOCR reader (may download models on first run)."""
        try:
            import easyocr
            self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            self.ready.emit()
        except Exception as e:
            self.init_failed.emit(str(e))

    def _run_ocr(self):
        with self._lock:
            frame = self._pending_frame
        if frame is None:
            self._busy = False
            return
        try:
            # Preprocess: grayscale + CLAHE for better contrast
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            results = self._reader.readtext(enhanced, detail=1, paragraph=False)
        except Exception:
            results = []
        finally:
            self._busy = False
        self.results_ready.emit(results, frame)


# ── Main dialog ───────────────────────────────────────────────────────────────

class OCRPairingDialog(QDialog):

    _PREVIEW_W = 480
    _PREVIEW_H = 360

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scan Pairing Code with Webcam")
        self.setMinimumWidth(520)
        self.setModal(True)

        self._cap: cv2.VideoCapture | None = None
        self._latest_frame: np.ndarray | None = None
        self._detections: list = []
        self._found: tuple | None = None          # (ip, port, code) once detected
        self._confirmed = False

        self._ocr = _OCRWorker()
        self._ocr.ready.connect(self._on_ocr_ready)
        self._ocr.init_failed.connect(self._on_ocr_failed)
        self._ocr.results_ready.connect(self._on_ocr_results)

        self._cam_timer = QTimer(self)
        self._cam_timer.timeout.connect(self._grab_frame)

        self._ocr_timer = QTimer(self)
        self._ocr_timer.timeout.connect(self._queue_ocr)

        self._setup_ui()
        self._start_camera()
        self._ocr.init_reader()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # Instructions
        instr = QLabel(
            "On your Pixel:\n"
            "Settings → Developer Options → Wireless Debugging\n"
            "→ <b>Pair device with pairing code</b>\n\n"
            "Hold that screen up to your webcam. "
            "Sprightly will read the IP, port, and code automatically."
        )
        instr.setTextFormat(Qt.RichText)
        instr.setWordWrap(True)
        instr.setStyleSheet("color:#aaa; font-size:12px;")
        lay.addWidget(instr)

        # Camera preview
        self._preview = QLabel()
        self._preview.setFixedSize(self._PREVIEW_W, self._PREVIEW_H)
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setStyleSheet("background:#111; border-radius:6px;")
        self._preview.setText("Starting camera…")
        lay.addWidget(self._preview, alignment=Qt.AlignHCenter)

        # OCR status bar
        self._ocr_status = QLabel("⏳  Initialising OCR engine (first run may take a moment)…")
        self._ocr_status.setAlignment(Qt.AlignCenter)
        self._ocr_status.setStyleSheet("color:#888; font-size:11px;")
        lay.addWidget(self._ocr_status)

        # Detected values (hidden until found)
        self._found_box = QWidget()
        flay = QFormLayout(self._found_box)
        flay.setSpacing(6)

        self._f_ip = QLineEdit()
        self._f_port = QSpinBox()
        self._f_port.setRange(1, 65535)
        self._f_code = QLineEdit()
        self._f_code.setMaxLength(6)

        flay.addRow("IP address:", self._f_ip)
        flay.addRow("Pair port:", self._f_port)
        flay.addRow("6-digit code:", self._f_code)

        note = QLabel("Edit if OCR made a mistake, then click Pair.")
        note.setStyleSheet("color:#777; font-size:11px;")
        flay.addRow(note)

        self._found_box.hide()
        lay.addWidget(self._found_box)

        # Connect port (always shown after pairing succeeds or if user needs it)
        self._conn_row = QWidget()
        crow = QHBoxLayout(self._conn_row)
        crow.setContentsMargins(0, 0, 0, 0)
        crow.addWidget(QLabel("Connect port (from 'IP address & Port'):"))
        self._f_conn_port = QSpinBox()
        self._f_conn_port.setRange(1, 65535)
        self._f_conn_port.setValue(5555)
        crow.addWidget(self._f_conn_port)
        self._conn_row.hide()
        lay.addWidget(self._conn_row)

        # Action buttons
        btn_row = QHBoxLayout()
        self._btn_pair = QPushButton("✓  Pair Now")
        self._btn_pair.setEnabled(False)
        self._btn_pair.clicked.connect(self._do_pair)
        btn_row.addWidget(self._btn_pair)

        self._btn_rescan = QPushButton("↺  Re-scan")
        self._btn_rescan.hide()
        self._btn_rescan.clicked.connect(self._rescan)
        btn_row.addWidget(self._btn_rescan)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)

        self._pair_status = QLabel("")
        self._pair_status.setWordWrap(True)
        self._pair_status.setAlignment(Qt.AlignCenter)
        self._pair_status.setStyleSheet("font-size:12px; color:#aaa;")
        lay.addWidget(self._pair_status)

    # ── Camera ────────────────────────────────────────────────────────────────

    def _start_camera(self):
        self._cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not self._cap.isOpened():
            self._preview.setText("No webcam detected.")
            return
        self._cam_timer.start(33)    # ~30 fps preview

    def _grab_frame(self):
        if not self._cap:
            return
        ret, frame = self._cap.read()
        if not ret:
            return
        self._latest_frame = frame
        self._render_preview(frame, self._detections)

    def _render_preview(self, frame: np.ndarray, detections: list):
        display = frame.copy()

        # Draw boxes around detected text
        for det in detections:
            bbox, text, conf = det
            if conf < 0.3:
                continue
            pts = np.array(bbox, dtype=np.int32)
            # Green for high confidence, yellow otherwise
            color = (0, 220, 80) if conf > 0.6 else (0, 180, 220)
            cv2.polylines(display, [pts], True, color, 2)

        # If we have a found result, draw a banner
        if self._found:
            ip, port, code = self._found
            banner = f"  {ip}:{port}   code: {code}  "
            cv2.rectangle(display, (0, 0), (display.shape[1], 32), (0, 160, 60), -1)
            cv2.putText(display, banner, (8, 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        img = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
        pix = QPixmap.fromImage(img).scaled(
            self._PREVIEW_W, self._PREVIEW_H,
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._preview.setPixmap(pix)

    # ── OCR ───────────────────────────────────────────────────────────────────

    def _on_ocr_ready(self):
        self._ocr_status.setText("🔍  Scanning… hold phone screen up to the webcam.")
        self._ocr_timer.start(600)    # try OCR every 600 ms

    def _on_ocr_failed(self, err: str):
        self._ocr_status.setStyleSheet("color:#f44336; font-size:11px;")
        self._ocr_status.setText(f"OCR engine failed to load: {err}")

    def _queue_ocr(self):
        if self._latest_frame is not None and not self._confirmed:
            self._ocr.process(self._latest_frame)

    def _on_ocr_results(self, detections: list, frame: np.ndarray):
        self._detections = detections
        texts = [d[1] for d in detections]
        result = _extract(texts)
        if result and not self._found:
            self._on_detected(*result)

    def _on_detected(self, ip: str, port: int, code: str):
        self._found = (ip, port, code)
        self._ocr_timer.stop()
        self._ocr_status.setStyleSheet("color:#4caf50; font-size:12px; font-weight:bold;")
        self._ocr_status.setText(f"✓  Detected — {ip}:{port}  code: {code}")

        # Populate editable fields
        self._f_ip.setText(ip)
        self._f_port.setValue(port)
        self._f_code.setText(code)
        self._found_box.show()
        self._conn_row.show()
        self._btn_pair.setEnabled(True)
        self._btn_rescan.show()
        self.adjustSize()

    # ── Pairing ───────────────────────────────────────────────────────────────

    def _do_pair(self):
        ip = self._f_ip.text().strip()
        port = self._f_port.value()
        code = self._f_code.text().strip()
        conn_port = self._f_conn_port.value()

        if not ip or len(code) != 6:
            self._pair_status.setStyleSheet("color:#f44336; font-size:12px;")
            self._pair_status.setText("IP and 6-digit code are required.")
            return

        self._confirmed = True
        self._btn_pair.setEnabled(False)
        self._pair_status.setStyleSheet("color:#aaa; font-size:12px;")
        self._pair_status.setText(f"Pairing with {ip}:{port}…")
        self.repaint()

        ok, msg = adb_bridge.pair(ip, port, code)
        if not ok:
            self._pair_status.setStyleSheet("color:#f44336; font-size:12px;")
            self._pair_status.setText(f"Pairing failed: {msg}")
            self._confirmed = False
            self._btn_pair.setEnabled(True)
            return

        self._pair_status.setText(f"Paired! Connecting to {ip}:{conn_port}…")
        self.repaint()

        ok2, msg2 = adb_bridge.connect(ip, conn_port)
        save_paired_device(ip, conn_port)

        if ok2:
            self._pair_status.setStyleSheet("color:#4caf50; font-size:13px; font-weight:bold;")
            self._pair_status.setText(f"✓ Connected to {ip}! You can close this dialog.")
        else:
            self._pair_status.setStyleSheet("color:#ff9800; font-size:12px;")
            self._pair_status.setText(
                f"Paired but connect failed ({msg2}).\n"
                f"The device should still appear — try again or check the connect port."
            )

    def _rescan(self):
        self._found = None
        self._detections = []
        self._confirmed = False
        self._found_box.hide()
        self._conn_row.hide()
        self._btn_rescan.hide()
        self._btn_pair.setEnabled(False)
        self._pair_status.setText("")
        self._ocr_status.setStyleSheet("color:#888; font-size:11px;")
        self._ocr_status.setText("🔍  Scanning… hold phone screen up to the webcam.")
        self._ocr_timer.start(600)
        self.adjustSize()

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _stop_all(self):
        self._cam_timer.stop()
        self._ocr_timer.stop()
        if self._cap:
            self._cap.release()
            self._cap = None

    def closeEvent(self, event):
        self._stop_all()
        super().closeEvent(event)

    def reject(self):
        self._stop_all()
        super().reject()
