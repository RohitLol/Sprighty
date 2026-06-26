import os
import subprocess
import webbrowser

from PySide6.QtCore import Qt, QSize, QTimer, QEvent
from PySide6.QtGui import QAction, QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QSystemTrayIcon,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.file_panel import FilePanel
from app.mirror_container import MIRROR_H, PHONE_W, PHONE_H, PhoneFrame
from app.pairing_dialog import PairingDialog
from app.settings_dialog import SettingsDialog
from app.usb_dialog import UsbDialog
from core import adb_bridge
from core.device_manager import DeviceManager
from core.scrcpy_launcher import ScrcpyLauncher
from core.settings_store import load_paired_devices, load_scrcpy_settings, load_window_geometry, save_window_geometry
from core.worker import run_async
from models.device import Device, DeviceState, Transport
from utils.icon_loader import icon
from utils.vendor_paths import scrcpy_dir, validate


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sprightly")
        self.setMinimumSize(PHONE_W + 440, MIRROR_H + 80)

        self._launcher = ScrcpyLauncher(self)
        self._device_manager = DeviceManager(self)
        self._devices: dict[str, Device] = {}
        self._mirroring_serial: str | None = None
        self._best_quality: bool = False
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self._file_panel_auto_refresh)
        self._auto_refresh_timer.setInterval(30_000)  # 30 s
        # Debounce file-list refresh: a WiFi device may reconnect several times
        # in quick succession; we only want one refresh at the end, not one per event.
        self._file_refresh_debounce = QTimer(self)
        self._file_refresh_debounce.setSingleShot(True)
        self._file_refresh_debounce.setInterval(3000)   # wait 3 s after last event

        self._setup_ui()
        self._setup_tray()
        self._connect_signals()
        self._restore_geometry()
        self._init_adb()

    # ── UI setup ──────────────────────────────────────────────────────────────

    def _setup_ui(self):
        # ── Toolbar ───────────────────────────────────────────────────────────
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        tb.setStyleSheet("QToolBar { spacing: 2px; }")
        self.addToolBar(tb)

        tb.addWidget(QLabel("  Device: "))

        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(220)
        self._device_combo.setPlaceholderText("No devices")
        tb.addWidget(self._device_combo)

        self._btn_mirror = QAction(icon("play"), "Mirror", self)
        self._btn_mirror.setToolTip("Start / stop screen mirror")
        self._btn_mirror.setEnabled(False)
        self._btn_mirror.triggered.connect(self._toggle_mirror)
        tb.addAction(self._btn_mirror)

        tb.addSeparator()

        # ── Connection ────────────────────────────────────────────────────────
        act_usb = QAction(icon("usb"), "USB", self)
        act_usb.setToolTip("Connect via USB — step-by-step guide")
        act_usb.triggered.connect(self._open_usb_dialog)
        tb.addAction(act_usb)

        act_wifi = QAction(icon("wifi"), "WiFi", self)
        act_wifi.setToolTip("Pair & connect wirelessly (same network required)")
        act_wifi.triggered.connect(self._open_pairing)
        tb.addAction(act_wifi)

        act_settings = QAction(icon("settings"), "Settings", self)
        act_settings.setToolTip("Video / quality settings")
        act_settings.triggered.connect(self._open_settings)
        tb.addAction(act_settings)

        act_refresh = QAction(icon("refresh"), "Refresh", self)
        act_refresh.setToolTip("Refresh file list")
        act_refresh.triggered.connect(self._refresh_files)
        tb.addAction(act_refresh)

        tb.addSeparator()

        # ── Phone control ─────────────────────────────────────────────────────
        act_wake = QAction(icon("wake"), "Wake", self)
        act_wake.setToolTip("Wake phone screen (works even when locked)")
        act_wake.triggered.connect(self._phone_wake)
        tb.addAction(act_wake)

        act_recents = QAction(icon("recents"), "Recents", self)
        act_recents.setToolTip("Open Recent Apps  (also: middle-click in mirror)")
        act_recents.triggered.connect(self._phone_recents)
        tb.addAction(act_recents)

        act_home = QAction(icon("home"), "Home", self)
        act_home.setToolTip("Press Home button")
        act_home.triggered.connect(self._phone_home)
        tb.addAction(act_home)

        act_back = QAction(icon("back"), "Back", self)
        act_back.setToolTip("Press Back button")
        act_back.triggered.connect(self._phone_back)
        tb.addAction(act_back)

        tb.addSeparator()

        # ── Share / clipboard ─────────────────────────────────────────────────
        act_browser = QAction(icon("send_url"), "Send Media", self)
        act_browser.setToolTip(
            "Open what's playing on the phone in your PC browser\n"
            "(YouTube video, Spotify track, Chrome tab…)")
        act_browser.triggered.connect(self._send_to_browser)
        tb.addAction(act_browser)

        act_clip = QAction(icon("clipboard"), "Clipboard", self)
        act_clip.setToolTip("Push PC clipboard text to phone")
        act_clip.triggered.connect(self._push_clipboard)
        tb.addAction(act_clip)

        tb.addSeparator()

        self._act_panel = QAction(icon("panel"), "Files", self)
        self._act_panel.setToolTip("Toggle file panel on/off (phone-only mode)")
        self._act_panel.setCheckable(True)
        self._act_panel.setChecked(True)
        self._act_panel.triggered.connect(self._toggle_panel)
        tb.addAction(self._act_panel)

        # ── Central: splitter ─────────────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)
        self._splitter = splitter
        splitter.setHandleWidth(3)

        # Left pane: dark wrapper that holds the phone frame widget
        left_wrap = QWidget()
        left_wrap.setStyleSheet("background:#000;")
        left_wrap.setFixedWidth(PHONE_W + 20)   # 10 px padding each side
        lv = QVBoxLayout(left_wrap)
        lv.setContentsMargins(10, 10, 10, 10)
        lv.setSpacing(0)

        self._mirror = PhoneFrame()
        lv.addWidget(self._mirror, 0, Qt.AlignHCenter | Qt.AlignTop)

        # ── Mirror quality toggle ──────────────────────────────────────────────
        quality_bar = QWidget()
        quality_bar.setStyleSheet("background:transparent;")
        ql = QHBoxLayout(quality_bar)
        ql.setContentsMargins(0, 8, 0, 0)
        ql.setSpacing(2)

        _btn_style_off = (
            "QPushButton{background:#111118;color:#44445A;border:1px solid #222230;"
            "border-radius:4px;padding:3px 14px;font-size:11px;font-weight:500;}"
            "QPushButton:hover{background:#1A1A28;color:#6666AA;}"
        )
        _btn_style_on = (
            "QPushButton{background:#2A2A60;color:#AAAAFF;border:1px solid #4444AA;"
            "border-radius:4px;padding:3px 14px;font-size:11px;font-weight:600;}"
        )

        self._btn_q_normal = QPushButton("Normal")
        self._btn_q_best   = QPushButton("Best")
        self._btn_q_normal.setStyleSheet(_btn_style_on)
        self._btn_q_best.setStyleSheet(_btn_style_off)
        self._btn_q_normal.clicked.connect(lambda: self._set_quality(False))
        self._btn_q_best.clicked.connect(lambda: self._set_quality(True))

        ql.addStretch()
        ql.addWidget(self._btn_q_normal)
        ql.addWidget(self._btn_q_best)
        ql.addStretch()

        lv.addWidget(quality_bar, 0, Qt.AlignHCenter)
        lv.addStretch()

        splitter.addWidget(left_wrap)

        self._file_panel = FilePanel()
        splitter.addWidget(self._file_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self.setCentralWidget(splitter)

        # ── Status bar ────────────────────────────────────────────────────────
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Starting ADB server…")

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        icon_path = str(scrcpy_dir() / "icon.png")
        tray_icon = QIcon(icon_path)
        self._tray.setIcon(tray_icon)
        self.setWindowIcon(tray_icon)
        self._tray.setToolTip("Sprightly")

        menu = QMenu()
        menu.addAction("Show").triggered.connect(self._show_window)
        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(QApplication.quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda r: self._show_window() if r == QSystemTrayIcon.DoubleClick else None
        )
        self._tray.show()

    def _connect_signals(self):
        self._device_manager.device_added.connect(self._on_device_added)
        self._device_manager.device_removed.connect(self._on_device_removed)
        self._device_manager.device_state_changed.connect(self._on_device_state_changed)
        self._file_refresh_debounce.timeout.connect(self._file_panel.refresh_files)

        self._device_combo.currentIndexChanged.connect(self._on_combo_changed)

        self._launcher.mirror_started.connect(self._on_mirror_started)
        self._launcher.mirror_stopped.connect(self._on_mirror_stopped)
        self._launcher.mirror_error.connect(self._on_mirror_error)

        # Middle-click in mirror → Recent Apps
        self._mirror.set_middle_click_callback(self._phone_recents)

        # Shift+Scroll / Shift+Arrow over mirror → horizontal swipe
        self._mirror.set_swipe_callbacks(self._phone_swipe_left,
                                         self._phone_swipe_right)

        # Monitor PC clipboard for changes synced from the phone via scrcpy
        QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)
        self._last_clipboard = ""

    def _init_adb(self):
        """Start the ADB server off the main thread to avoid startup freeze."""
        try:
            validate()
        except FileNotFoundError as e:
            QMessageBox.critical(self, "Missing vendor files", str(e))
            return

        def _start_adb():
            adb_bridge.kill_server()
            adb_bridge.start_server()

        run_async(_start_adb, on_done=self._on_adb_ready)

    def _on_adb_ready(self, _result):
        """Called on the main thread once ADB server is up."""
        self._device_manager.start()
        QTimer.singleShot(500, self._reconnect_saved_devices)
        self._status.showMessage("Ready — connect a device to begin.")

    def _reconnect_saved_devices(self):
        seen_ips: set[str] = set()
        for saved in load_paired_devices():
            if saved.ip not in seen_ips:      # one reconnect attempt per IP
                seen_ips.add(saved.ip)
                run_async(self._reconnect_one, saved.ip, saved.port)

    def _reconnect_one(self, ip: str, port: int):
        """Try saved port; fall back to port auto-detect if it fails."""
        ok, _ = adb_bridge.connect(ip, port)
        if not ok:
            from core.adb_discover import find_adb_port
            from core.settings_store import save_paired_device
            new_port = find_adb_port(ip)
            if new_port:
                ok2, _ = adb_bridge.connect(ip, new_port)
                if ok2:
                    save_paired_device(ip, new_port)

    def _restore_geometry(self):
        geom = load_window_geometry()
        if geom:
            self.restoreGeometry(geom)

    # ── Device management ─────────────────────────────────────────────────────

    def _toggle_panel(self):
        visible = self._file_panel.isVisible()
        self._file_panel.setVisible(not visible)
        self._act_panel.setChecked(not visible)

    def _file_panel_auto_refresh(self):
        """Auto-refresh file list every 30s — skipped during active mirror.

        Running 'adb shell ls -la' over the same WiFi link that carries the
        video stream competes for bandwidth and causes brief stutter.
        """
        if self._devices and not self._mirroring_serial:
            self._file_panel.refresh_files()

    def _on_device_added(self, device: Device):
        self._devices[device.serial] = device
        self._rebuild_combo()
        adb_bridge.set_target(device.serial)
        # Debounce: rapid WiFi reconnects restart the timer; only ONE refresh fires
        # 3 s after the last device_added event — prevents constant loading spinner.
        self._file_refresh_debounce.start()
        self._auto_refresh_timer.start()
        self._tray.showMessage("Sprightly", f"{device.display_name} connected",
                               QSystemTrayIcon.Information, 2000)
        self._status.showMessage(f"{device.display_name} connected.")

    def _on_device_removed(self, device: Device):
        self._devices.pop(device.serial, None)
        if self._mirroring_serial == device.serial:
            self._launcher.stop()
        if not self._devices:
            self._auto_refresh_timer.stop()
        self._rebuild_combo()
        self._status.showMessage(f"{device.display_name} disconnected.")

    def _on_device_state_changed(self, device: Device):
        self._devices[device.serial] = device
        self._rebuild_combo()
        if device.state == DeviceState.UNAUTHORIZED:
            self._status.showMessage(
                f"⚠  {device.display_name}: Check your phone and tap Allow for USB debugging.")

    def _transport_tag(self, device: Device) -> str:
        return "WiFi" if (device.serial and ":" in device.serial) else "USB"

    @staticmethod
    def _state_dot(device: Device) -> str:
        from models.device import DeviceState
        return {
            DeviceState.DEVICE: "●",
            DeviceState.UNAUTHORIZED: "◐",
            DeviceState.OFFLINE: "○",
        }.get(device.state, "○")

    @staticmethod
    def _usb_serial_from_mdns(serial: str) -> str:
        """Extract the USB serial embedded in a mDNS ADB serial.

        mDNS serials look like: adb-R3CX20YK8BX-XXXXX._adb-tls-connect._tcp.local:PORT
        Returns the USB serial portion, or "" if this isn't a mDNS serial.
        """
        import re as _re
        m = _re.match(r'adb-([A-Za-z0-9]+)', serial)
        return m.group(1) if m else ""

    def _rebuild_combo(self):
        self._device_combo.blockSignals(True)
        prev = self._device_combo.currentData()
        self._device_combo.clear()

        # USB serials currently connected — used to suppress mDNS duplicates.
        usb_serials = {d.serial for d in self._devices.values()
                       if d.transport == Transport.USB}

        for d in self._devices.values():
            # Skip a mDNS WiFi entry when the same physical device is already
            # listed via its USB cable (avoids "Pixel 8a · USB" + "Pixel 8a (WiFi)"
            # for the exact same device).
            if d.transport == Transport.TCPIP:
                usb_part = self._usb_serial_from_mdns(d.serial)
                if usb_part and usb_part in usb_serials:
                    continue

            tag = self._transport_tag(d)
            dot = self._state_dot(d)
            label = f"{dot}  {d.display_name}  ·  {tag}  ·  {d.state.value}"
            self._device_combo.addItem(label, userData=d.serial)
        for i in range(self._device_combo.count()):
            if self._device_combo.itemData(i) == prev:
                self._device_combo.setCurrentIndex(i)
                break
        self._device_combo.blockSignals(False)
        if self._device_combo.currentIndex() == -1 and self._device_combo.count() > 0:
            self._device_combo.setCurrentIndex(0)
        self._on_combo_changed()

    def _on_combo_changed(self):
        serial = self._device_combo.currentData()
        device = self._devices.get(serial) if serial else None
        if serial:
            adb_bridge.set_target(serial)
        mirroring = self._mirroring_serial is not None
        can_start = device and device.is_connectable and not mirroring
        self._btn_mirror.setEnabled(bool(can_start) or mirroring)
        if mirroring:
            self._btn_mirror.setIcon(icon("stop"))
            self._btn_mirror.setText("Stop")
        else:
            self._btn_mirror.setIcon(icon("play"))
            self._btn_mirror.setText("Mirror")
        self._update_quality_bar()

    def _selected_device(self) -> Device | None:
        serial = self._device_combo.currentData()
        return self._devices.get(serial) if serial else None

    # ── Mirror actions ────────────────────────────────────────────────────────

    _Q_ON  = ("QPushButton{background:#2A2A60;color:#AAAAFF;border:1px solid #4444AA;"
              "border-radius:4px;padding:3px 14px;font-size:11px;font-weight:600;}")
    _Q_OFF = ("QPushButton{background:#111118;color:#44445A;border:1px solid #222230;"
              "border-radius:4px;padding:3px 14px;font-size:11px;font-weight:500;}"
              "QPushButton:hover{background:#1A1A28;color:#6666AA;}")

    def _set_quality(self, best: bool) -> None:
        if self._best_quality == best:
            return
        self._best_quality = best
        self._btn_q_normal.setStyleSheet(self._Q_ON  if not best else self._Q_OFF)
        self._btn_q_best.setStyleSheet(  self._Q_ON  if best  else self._Q_OFF)
        # If currently mirroring over WiFi, stop and restart with new quality
        if self._mirroring_serial is not None:
            device = self._selected_device()
            if device and device.transport == Transport.TCPIP:
                self._launcher.stop()
                QTimer.singleShot(800, self._toggle_mirror)

    def _update_quality_bar(self) -> None:
        """Show/hide quality toggle based on selected device transport."""
        device = self._selected_device()
        is_wifi = device is not None and device.transport == Transport.TCPIP
        # Always enabled — changing while mirroring triggers an auto-restart
        self._btn_q_normal.setVisible(is_wifi)
        self._btn_q_best.setVisible(is_wifi)

    def _toggle_mirror(self):
        if self._mirroring_serial:
            self._launcher.stop()
        else:
            device = self._selected_device()
            if device and device.is_connectable:
                settings = load_scrcpy_settings()
                if device.transport == Transport.USB:
                    # USB: 1080p, 8M bitrate, 60fps — best quality, zero lag
                    settings.max_size = 1080
                    settings.bitrate  = "8M"
                    settings.max_fps  = 60
                elif self._best_quality:
                    # WiFi Best: match USB quality
                    settings.wifi_max_fps  = 60
                    settings.wifi_max_size = 1080
                    settings.wifi_bitrate  = "4M"
                self._launcher.start(device, settings)

    def _on_mirror_started(self):
        device = self._selected_device()
        if device:
            self._mirroring_serial = device.serial
        self._btn_mirror.setIcon(icon("stop"))
        self._btn_mirror.setText("Stop")
        self._btn_mirror.setEnabled(True)
        self._status.showMessage(f"Mirroring {device.display_name if device else ''}…")
        self._mirror.start_embedding(self._launcher.window_title)
        self._update_quality_bar()

    def _on_mirror_stopped(self):
        self._mirroring_serial = None
        self._mirror.stop_embedding()
        self._btn_mirror.setIcon(icon("play"))
        self._btn_mirror.setText("Mirror")
        self._on_combo_changed()
        self._status.showMessage("Mirror stopped.")

    def _on_mirror_error(self, msg: str):
        self._mirroring_serial = None
        self._mirror.stop_embedding()
        self._btn_mirror.setIcon(icon("play"))
        self._btn_mirror.setText("Mirror")
        self._on_combo_changed()
        self._status.showMessage(f"Error: {msg[:120]}")

    # ── Other actions ─────────────────────────────────────────────────────────

    def _open_usb_dialog(self):
        UsbDialog(self).exec()

    def _open_pairing(self):
        if PairingDialog(self).exec():
            self._status.showMessage("Device paired and connected via WiFi.")

    def _open_settings(self):
        SettingsDialog(self).exec()

    def _refresh_files(self):
        self._file_panel.refresh_files()

    # ── Phone control (all off main thread) ───────────────────────────────────

    def _refocus(self):
        """Return keyboard focus to scrcpy after a toolbar action."""
        if self._mirroring_serial:
            self._mirror.request_scrcpy_focus()

    def _phone_wake(self):
        self._status.showMessage("Waking screen…")
        run_async(adb_bridge.wake,
                  on_done=lambda _: self._status.showMessage("Screen wake sent."))
        QTimer.singleShot(150, self._refocus)

    def _phone_recents(self):
        run_async(adb_bridge.recent_apps)
        QTimer.singleShot(150, self._refocus)

    def _phone_home(self):
        run_async(adb_bridge.home)
        QTimer.singleShot(150, self._refocus)

    def _phone_back(self):
        run_async(adb_bridge.back)
        QTimer.singleShot(150, self._refocus)

    def _phone_swipe_left(self):
        """Swipe left on device (next carousel item / scroll forward)."""
        run_async(adb_bridge.swipe_h, -1)
        QTimer.singleShot(150, self._refocus)

    def _phone_swipe_right(self):
        """Swipe right on device (prev carousel item / scroll back)."""
        run_async(adb_bridge.swipe_h, 1)
        QTimer.singleShot(150, self._refocus)

    # ── Clipboard ─────────────────────────────────────────────────────────────

    def _on_clipboard_changed(self):
        if not self._mirroring_serial:
            return
        text = QApplication.clipboard().text()
        if text and text != self._last_clipboard:
            self._last_clipboard = text
            preview = text[:60].replace("\n", " ")
            self._status.showMessage(f"Clipboard from phone: {preview}")

    def _push_clipboard(self):
        text = QApplication.clipboard().text()
        if not text:
            self._status.showMessage("Clipboard is empty.")
            return
        preview = text[:60].replace("\n", " ")
        self._status.showMessage(f"Sending to phone: {preview}")

        def _done(_):
            self._status.showMessage(f"Clipboard sent to phone: {preview}")
            self._refocus()

        run_async(adb_bridge.push_clipboard_text, text, on_done=_done)

    # ── Send to browser ───────────────────────────────────────────────────────

    def _open_in_chrome(self, url: str) -> None:
        """Open url in Chrome. If Chrome is not found, fall back to the default browser."""
        chrome_candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        for path in chrome_candidates:
            if os.path.isfile(path):
                subprocess.Popen([path, url])
                return
        webbrowser.open(url)

    def _send_to_browser(self):
        """Detect what's playing on the phone and open it in Chrome."""
        self._status.showMessage("Detecting what's playing on phone…")
        run_async(adb_bridge.get_foreground_url, on_done=self._on_url_found)

    def _on_url_found(self, url):
        if url:
            self._open_in_chrome(url)
            if "youtube.com/watch" in url:
                label = "YouTube video"
            elif "youtube.com/results" in url:
                label = "YouTube search"
            elif "spotify.com" in url:
                label = "Spotify track"
            elif "netflix.com" in url:
                label = "Netflix title"
            else:
                label = url[:70]
            self._status.showMessage(f"✓ Opened {label} in Chrome")
        else:
            self._status.showMessage(
                "Nothing detected — is a YouTube video playing on the phone?")
        QTimer.singleShot(150, self._refocus)

    def _focus_mirror(self):
        """Return keyboard focus to the embedded scrcpy window."""
        if self._launcher.is_running:
            self._mirror.request_scrcpy_focus()

    def keyPressEvent(self, event):
        """Press Escape while mirroring → return keyboard focus to scrcpy."""
        if event.key() == Qt.Key_Escape and self._mirroring_serial:
            self._focus_mirror()
            event.accept()
            return
        super().keyPressEvent(event)

    def _show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ── Close ─────────────────────────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent):
        save_window_geometry(self.saveGeometry())
        if self._launcher.is_running:
            self._launcher.stop()
        self._device_manager.stop()
        adb_bridge.kill_server()
        self._mirror.stop_embedding()
        self._mirror.cleanup()
        event.accept()
