import os
import subprocess
import threading

import psutil
from PySide6.QtCore import QObject, Signal

from core.settings_store import ScrcpySettings, load_scrcpy_settings
from models.device import Device, Transport
from app.mirror_container import MIRROR_W, MIRROR_H
from utils.vendor_paths import adb_exe, scrcpy_dir, scrcpy_exe


class ScrcpyLauncher(QObject):
    mirror_started = Signal()
    mirror_stopped = Signal()
    mirror_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: subprocess.Popen | None = None
        self._device: Device | None = None
        self._window_title: str = ""
        self._killed = False   # True when we initiated the kill ourselves

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def window_title(self) -> str:
        return self._window_title

    @staticmethod
    def _kill_existing_scrcpy() -> None:
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"] and proc.info["name"].lower() == "scrcpy.exe":
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def start(self, device: Device, settings: ScrcpySettings | None = None) -> None:
        if self.is_running:
            return
        self._kill_existing_scrcpy()
        if settings is None:
            settings = load_scrcpy_settings()

        self._device = device
        self._window_title = f"Sprightly — {device.display_name}"
        args = self._build_args(device, settings)
        env = self._build_env()

        self._process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(scrcpy_dir()),
        )
        self.mirror_started.emit()
        threading.Thread(target=self._monitor, daemon=True).start()

    def stop(self) -> None:
        if self._process and self._process.poll() is None:
            self._killed = True
            self._process.kill()

    def _build_args(self, device: Device, settings: ScrcpySettings) -> list[str]:
        args = [str(scrcpy_exe())]

        wifi = device.transport == Transport.TCPIP
        if wifi:
            args += ["-s", f"{device.ip}:{device.port}"]
        else:
            args += ["-s", device.serial]

        args += [
            "--video-codec", "h264",
            "--window-title", self._window_title,
            "--window-borderless",
            "--no-audio",
            # SDL must start at exactly the container size so it fills our embedded
            # window correctly from the first frame.  MoveWindow later confirms it.
            "--window-width", str(MIRROR_W),
            "--window-height", str(MIRROR_H),
            # Keep phone screen on while mirror is active.
            "--stay-awake",
        ]

        if wifi:
            # WiFi Normal: 720p/30fps/1M  |  WiFi Best: 1080p/60fps/4M
            # 50ms buffer smooths WiFi jitter; 0 causes divide-by-zero on lossy links.
            args += [
                "--max-size", str(settings.wifi_max_size),
                "--video-bit-rate", settings.wifi_bitrate,
                "--max-fps", str(settings.wifi_max_fps),
                "--video-buffer", "50",
            ]
        else:
            # USB: 1080p, 8M bitrate, zero buffer for real-time feel.
            args += [
                "--max-size", str(settings.max_size),
                "--video-bit-rate", settings.bitrate,
                "--max-fps", str(settings.max_fps),
                "--video-buffer", "0",
            ]

        return args

    def _build_env(self) -> dict:
        env = os.environ.copy()
        env["ADB_MDNS_OPENSCREEN"] = "1"
        vendor = str(scrcpy_dir())
        env["PATH"] = vendor + os.pathsep + env.get("PATH", "")
        env["ADB"] = str(adb_exe())
        return env

    # Lines that appear in scrcpy stderr during normal startup / operation.
    # They must never be surfaced as errors to the user.
    _STDERR_NOISE = (
        "file pushed",      # "scrcpy-server: 1 file pushed, 0 skipped. 7.4 MB/s…"
        "file skipped",
        "MB/s",             # transfer-rate stats
        "bytes in 0.",      # short push duration  e.g. "(90980 bytes in 0.012s)"
        "adb-tls",          # mDNS TLS reconnect messages
        "tls-connect",
    )

    def _monitor(self):
        stdout, stderr = self._process.communicate()
        rc = self._process.returncode
        was_killed = self._killed
        self._killed = False
        self._process = None

        # rc == 0  → scrcpy exited cleanly (user closed the window)
        # rc == 1  → Windows TerminateProcess from our kill() call
        # rc == -1 → POSIX SIGKILL (shouldn't happen on Windows, but guard anyway)
        if rc == 0 or was_killed:
            self.mirror_stopped.emit()
        else:
            raw = stderr.decode(errors="replace").strip()
            # Strip normal startup / connection chatter so we only show real errors
            lines = [
                ln for ln in raw.splitlines()
                if not any(noise in ln for noise in self._STDERR_NOISE)
            ]
            msg = "\n".join(lines).strip()
            self.mirror_error.emit(msg or f"scrcpy exited with code {rc}")
