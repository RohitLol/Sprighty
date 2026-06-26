import json
from dataclasses import asdict, dataclass

from PySide6.QtCore import QSettings


@dataclass
class ScrcpySettings:
    max_size: int = 1080
    bitrate: str = "4M"
    max_fps: int = 60
    wifi_max_fps: int = 30
    wifi_max_size: int = 720
    wifi_bitrate: str = "1M"


@dataclass
class SavedDevice:
    ip: str
    port: int
    label: str = ""


_ORG = "Sprightly"
_APP = "sprightly"


def _settings() -> QSettings:
    return QSettings(_ORG, _APP)


_SETTINGS_VERSION = 2  # bump when adding new fields that need fresh defaults


def load_scrcpy_settings() -> ScrcpySettings:
    s = _settings()
    # If schema version changed, drop old scrcpy/* keys so new defaults apply cleanly.
    if int(s.value("scrcpy/schema_version", 0)) < _SETTINGS_VERSION:
        for key in list(s.allKeys()):
            if key.startswith("scrcpy/") and key != "scrcpy/schema_version":
                s.remove(key)
        s.setValue("scrcpy/schema_version", _SETTINGS_VERSION)
    return ScrcpySettings(
        max_size=int(s.value("scrcpy/max_size", 1080)),
        bitrate=str(s.value("scrcpy/bitrate", "4M")),
        max_fps=int(s.value("scrcpy/max_fps", 60)),
        wifi_max_fps=int(s.value("scrcpy/wifi_max_fps", 30)),
        wifi_max_size=int(s.value("scrcpy/wifi_max_size", 720)),
        wifi_bitrate=str(s.value("scrcpy/wifi_bitrate", "1M")),
    )


def save_scrcpy_settings(cfg: ScrcpySettings) -> None:
    s = _settings()
    s.setValue("scrcpy/max_size", cfg.max_size)
    s.setValue("scrcpy/bitrate", cfg.bitrate)
    s.setValue("scrcpy/max_fps", cfg.max_fps)
    s.setValue("scrcpy/wifi_max_fps", cfg.wifi_max_fps)
    s.setValue("scrcpy/wifi_max_size", cfg.wifi_max_size)
    s.setValue("scrcpy/wifi_bitrate", cfg.wifi_bitrate)


def load_paired_devices() -> list[SavedDevice]:
    s = _settings()
    raw = s.value("wifi/paired_devices", "[]")
    try:
        items = json.loads(raw)
        return [SavedDevice(**d) for d in items]
    except Exception:
        return []


def save_paired_device(ip: str, port: int, label: str = "") -> None:
    devices = load_paired_devices()
    for d in devices:
        if d.ip == ip:          # match by IP only — update port if it changed
            d.port  = port
            d.label = label or d.label
            break
    else:
        devices.append(SavedDevice(ip=ip, port=port, label=label))
    _settings().setValue("wifi/paired_devices", json.dumps([asdict(d) for d in devices]))


def remove_paired_device(ip: str, port: int) -> None:
    devices = [d for d in load_paired_devices() if not (d.ip == ip and d.port == port)]
    _settings().setValue("wifi/paired_devices", json.dumps([asdict(d) for d in devices]))


def save_window_geometry(geometry: bytes) -> None:
    _settings().setValue("window/geometry", geometry)


def load_window_geometry() -> bytes | None:
    return _settings().value("window/geometry")
