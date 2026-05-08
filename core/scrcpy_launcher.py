import os
import subprocess
import threading

import psutil
from PySide6.QtCore import QObject, Signal

from app.mirror_container import MIRROR_W, MIRROR_H
from core.settings_store import ScrcpySettings, load_scrcpy_settings
from models.device import Device, Transport
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
            self._process.kill()

    def _build_args(self, device: Device, settings: ScrcpySettings) -> list[str]:
        args = [str(scrcpy_exe())]

        wifi = device.transport == Transport.TCPIP
        if wifi:
            args += ["-s", f"{device.ip}:{device.port}"]
        else:
            args += ["-s", device.serial]

        args += [
            "--max-size", str(settings.max_size),
            "--video-codec", "h264",
            "--window-title", self._window_title,
            "--window-borderless",
            "--no-audio",
            "--window-width", str(MIRROR_W),
            "--window-height", str(MIRROR_H),
            # Keep phone screen on while mirror is active.
            # Without this: screen timeout kills the video stream while ADB
            # (keyevent/shell) stays alive → mirror goes black mid-session.
            "--stay-awake",
        ]

        if wifi:
            # WiFi latency reduction strategy:
            # • 720p instead of 1080p  → frames are ~56 % smaller (biggest win)
            # • 1.5 Mbps bitrate       → less data per frame to transmit
            # • 30 fps                 → halves frame rate, halves bandwidth
            # • 0 ms buffer            → no added latency; small frames tolerate jitter
            # --stay-awake already prevents the screen-off black-screen issue.
            args += [
                "--max-size", "720",
                "--video-bit-rate", "1.5M",
                "--max-fps", "30",
                "--video-buffer", "0",
            ]
        else:
            # USB: use full user settings; zero buffer for real-time feel.
            args += [
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

    def _monitor(self):
        stdout, stderr = self._process.communicate()
        rc = self._process.returncode
        self._process = None
        if rc == 0 or rc == -1:
            self.mirror_stopped.emit()
        else:
            msg = stderr.decode(errors="replace").strip()
            self.mirror_error.emit(msg or f"scrcpy exited with code {rc}")
