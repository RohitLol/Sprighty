"""WiFi pairing dialog — all ADB calls run off the main thread."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from core import adb_bridge
from core.adb_discover import find_adb_port
from core.settings_store import save_paired_device
from core.worker import run_async


class PairingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Device via WiFi")
        self.setMinimumWidth(440)
        self.setModal(True)
        self._busy = False
        self._setup_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        # ── Network requirement notice ────────────────────────────────────────
        net_note = QLabel(
            "<b>Requirement:</b> your PC and phone must be on the <b>same Wi-Fi network</b>.<br>"
            "Different networks (e.g. mobile data ↔ home Wi-Fi) are not supported by ADB."
        )
        net_note.setTextFormat(Qt.RichText)
        net_note.setWordWrap(True)
        net_note.setStyleSheet(
            "background:#1A1A10; color:#C8B45A; border:1px solid #3A3A20;"
            "border-radius:6px; padding:8px; font-size:12px;"
        )
        lay.addWidget(net_note)

        tabs = QTabWidget()
        tabs.addTab(self._build_pair_tab(),    "Pair new device")
        tabs.addTab(self._build_connect_tab(), "Reconnect (already paired)")
        lay.addWidget(tabs)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("font-size:12px;")
        lay.addWidget(self._status)

    def _build_pair_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(6)

        info = QLabel(
            "<b>On your Pixel:</b>  Settings → Developer Options → Wireless debugging<br>"
            "→ tap <b>Pair device with pairing code</b><br><br>"
            "The phone will show three pieces of information — fill them in below:"
        )
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)
        info.setStyleSheet("color:#94A3B8; font-size:12px; padding:4px;")
        lay.addWidget(info)

        form = QFormLayout()
        form.setSpacing(6)

        self._ip = QLineEdit()
        self._ip.setPlaceholderText("e.g.  192.168.1.42")
        form.addRow("IP Address:", self._ip)
        form.addRow("", QLabel(
            "<i>Main Wireless debugging page — shown at the top</i>",
        ))

        self._connect_port = QSpinBox()
        self._connect_port.setRange(1, 65535)
        self._connect_port.setValue(0)
        self._connect_port.setSpecialValueText("—")
        self._connect_port.setToolTip(
            "Port shown next to the IP address on the main Wireless debugging page.\n"
            "This is a random high port like 38291 — NOT the pairing port."
        )
        form.addRow("Connect Port:", self._connect_port)
        form.addRow("", QLabel(
            "<i>Port next to IP on <b>main</b> Wireless debugging page (e.g. 38291)</i>"
        ))

        self._pairing_port = QSpinBox()
        self._pairing_port.setRange(1, 65535)
        self._pairing_port.setValue(0)
        self._pairing_port.setSpecialValueText("—")
        form.addRow("Pairing Port:", self._pairing_port)
        form.addRow("", QLabel(
            "<i>Port shown next to the 6-digit code (under \"Pair device with pairing code\")</i>"
        ))

        self._code = QLineEdit()
        self._code.setPlaceholderText("6-digit code")
        self._code.setMaxLength(6)
        form.addRow("Pairing Code:", self._code)

        lay.addLayout(form)

        self._btn_pair = QPushButton("Pair && Connect")
        self._btn_pair.clicked.connect(self._do_pair)
        lay.addWidget(self._btn_pair)
        lay.addStretch()
        return w

    def _build_connect_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(6)

        note = QLabel(
            "Use this if you've paired before and just need to reconnect.<br><br>"
            "<b>On your Pixel:</b>  Settings → Developer Options → Wireless debugging<br>"
            "The <b>IP address &amp; Port</b> is shown at the top of that page."
        )
        note.setTextFormat(Qt.RichText)
        note.setWordWrap(True)
        note.setStyleSheet("color:#94A3B8; font-size:12px; padding:4px;")
        lay.addWidget(note)

        form = QFormLayout()
        form.setSpacing(6)
        self._c_ip = QLineEdit()
        self._c_ip.setPlaceholderText("e.g.  192.168.1.42")
        form.addRow("IP Address:", self._c_ip)

        self._c_port = QSpinBox()
        self._c_port.setRange(1, 65535)
        self._c_port.setValue(0)
        self._c_port.setSpecialValueText("—")
        form.addRow("Connect Port:", self._c_port)
        lay.addLayout(form)

        self._btn_auto = QPushButton("Auto-detect Port && Connect")
        self._btn_auto.setToolTip(
            "Scans the phone for an open ADB port automatically.\n"
            "Takes a few seconds — the UI stays responsive."
        )
        self._btn_auto.clicked.connect(self._do_auto_connect)
        lay.addWidget(self._btn_auto)

        self._btn_manual = QPushButton("Connect with entered port")
        self._btn_manual.clicked.connect(self._do_connect_only)
        lay.addWidget(self._btn_manual)
        lay.addStretch()
        return w

    # ── Actions (all ADB calls off main thread) ───────────────────────────────

    def _do_pair(self):
        if self._busy:
            return
        ip           = self._ip.text().strip()
        pairing_port = self._pairing_port.value()
        connect_port = self._connect_port.value()
        code         = self._code.text().strip()

        if not ip:
            return self._err("IP address is required.")
        if connect_port == 0:
            return self._err("Connect port is required (port shown next to the IP).")
        if pairing_port == 0:
            return self._err("Pairing port is required (port shown next to the 6-digit code).")
        if len(code) != 6 or not code.isdigit():
            return self._err("Pairing code must be exactly 6 digits.")

        self._set_busy(True, "Pairing… (this takes a few seconds)")

        def _work():
            ok, msg = adb_bridge.pair(ip, pairing_port, code)
            if not ok:
                return ("pair_fail", msg)
            ok2, msg2 = adb_bridge.connect(ip, connect_port)
            if not ok2:
                return ("conn_fail", msg2, connect_port)
            save_paired_device(ip, connect_port)
            return ("ok", ip, connect_port)

        run_async(_work, on_done=self._on_pair_done)

    def _on_pair_done(self, result):
        self._set_busy(False)
        if result is None or result[0] == "pair_fail":
            msg = result[1] if result else "Unknown error"
            self._err(f"Pairing failed: {msg}")
        elif result[0] == "conn_fail":
            self._err(
                f"Paired OK but connect failed: {result[1]}\n"
                f"Make sure the Connect Port matches what's shown on the Wireless debugging page."
            )
        else:
            _, ip, port = result
            self._ok(f"✓ Connected to {ip}:{port} — device should appear in the list.")

    def _do_auto_connect(self):
        if self._busy:
            return
        ip = self._c_ip.text().strip()
        if not ip:
            return self._err("IP address is required.")

        self._set_busy(True, f"Scanning {ip} for ADB port… (a few seconds)")

        def _work():
            port = find_adb_port(ip)
            if not port:
                return ("no_port",)
            ok, msg = adb_bridge.connect(ip, port)
            if not ok:
                return ("conn_fail", port, msg)
            save_paired_device(ip, port)
            return ("ok", ip, port)

        run_async(_work, on_done=self._on_auto_done)

    def _on_auto_done(self, result):
        self._set_busy(False)
        if result is None or result[0] == "no_port":
            self._err(
                "No open ADB port found. Make sure:\n"
                "• Wireless debugging is ON\n"
                "• Phone screen is unlocked\n"
                "• Phone and PC are on the same Wi-Fi network"
            )
        elif result[0] == "conn_fail":
            port, msg = result[1], result[2]
            self._c_port.setValue(port)
            self._err(f"Found port {port} but connect failed: {msg}")
        else:
            _, ip, port = result
            self._c_port.setValue(port)
            self._ok(f"✓ Connected to {ip}:{port} — device should appear in the list.")

    def _do_connect_only(self):
        if self._busy:
            return
        ip   = self._c_ip.text().strip()
        port = self._c_port.value()
        if not ip:
            return self._err("IP address is required.")
        if port == 0:
            return self._err("Connect port is required.")

        self._set_busy(True, f"Connecting to {ip}:{port}…")

        def _work():
            ok, msg = adb_bridge.connect(ip, port)
            if not ok:
                return ("fail", msg)
            save_paired_device(ip, port)
            return ("ok", ip, port)

        run_async(_work, on_done=self._on_connect_done)

    def _on_connect_done(self, result):
        self._set_busy(False)
        if result is None or result[0] == "fail":
            msg = result[1] if result else "Unknown error"
            self._err(f"Connect failed: {msg}")
        else:
            _, ip, port = result
            self._ok(f"✓ Connected to {ip}:{port} — device should appear in the list.")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool, msg: str = ""):
        self._busy = busy
        for btn in (self._btn_pair, self._btn_auto, self._btn_manual):
            btn.setEnabled(not busy)
        if msg:
            self._info(msg)

    def _err(self, msg: str):
        self._status.setStyleSheet("color:#f44336; font-size:12px;")
        self._status.setText(msg)

    def _info(self, msg: str):
        self._status.setStyleSheet("color:#94A3B8; font-size:12px;")
        self._status.setText(msg)

    def _ok(self, msg: str):
        self._status.setStyleSheet("color:#4caf50; font-size:12px; font-weight:bold;")
        self._status.setText(msg)
