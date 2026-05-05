import os
import re
import subprocess
from typing import Optional

from models.device import Device, DeviceState, Transport
from utils.vendor_paths import adb_exe

# Serial of the currently selected / active device.
# Set this whenever the user picks a device in the UI.
_target_serial: str = ""


def set_target(serial: str) -> None:
    """Set the device serial that all subsequent ADB commands target."""
    global _target_serial
    _target_serial = serial


def get_target() -> str:
    return _target_serial


def _run(*args: str, input: Optional[str] = None, timeout: int = 10) -> tuple[int, str, str]:
    """Run a global ADB command (no -s serial). Use for: devices, connect, pair, start-server, etc."""
    exe = str(adb_exe())
    cmd = [exe] + list(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        input=input,
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return result.returncode, result.stdout, result.stderr


def _run_on_device(*args: str, input: Optional[str] = None, timeout: int = 10) -> tuple[int, str, str]:
    """Run an ADB command targeting the current _target_serial device."""
    exe = str(adb_exe())
    cmd = [exe]
    if _target_serial:
        cmd += ["-s", _target_serial]
    cmd += list(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        input=input,
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return result.returncode, result.stdout, result.stderr


def start_server() -> None:
    _run("start-server")


def kill_server() -> None:
    _run("kill-server")


def list_devices() -> list[Device]:
    rc, stdout, _ = _run("devices", "-l")
    if rc != 0:
        return []

    devices = []
    for line in stdout.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        serial = parts[0]
        raw_state = parts[1]

        state_map = {
            "device": DeviceState.DEVICE,
            "offline": DeviceState.OFFLINE,
            "unauthorized": DeviceState.UNAUTHORIZED,
        }
        state = state_map.get(raw_state, DeviceState.UNKNOWN)

        transport = Transport.TCPIP if re.match(r"^\d+\.\d+\.\d+\.\d+:\d+$", serial) else Transport.USB

        model = ""
        for part in parts[2:]:
            if part.startswith("model:"):
                model = part.split(":", 1)[1].replace("_", " ")
                break

        ip, port = "", 5555
        if transport == Transport.TCPIP:
            ip, _, p = serial.partition(":")
            port = int(p) if p.isdigit() else 5555

        devices.append(Device(serial=serial, state=state, transport=transport, model=model, ip=ip, port=port))

    return devices


def connect(ip: str, port: int) -> tuple[bool, str]:
    rc, stdout, stderr = _run("connect", f"{ip}:{port}")
    output = stdout.strip() or stderr.strip()
    success = "connected" in output.lower() and "unable" not in output.lower()
    return success, output


def disconnect(serial: str) -> None:
    _run("disconnect", serial)


def pair(ip: str, pairing_port: int, code: str) -> tuple[bool, str]:
    # ADB 36+ requires the code as a positional argument, not via stdin
    rc, stdout, stderr = _run("pair", f"{ip}:{pairing_port}", code, timeout=15)
    output = (stdout + stderr).strip()
    success = rc == 0 and "successfully" in output.lower()
    return success, output


# ── Device input / control ────────────────────────────────────────────────────

def keyevent(code: int) -> None:
    """Send an Android key event to the target device (non-blocking)."""
    _run_on_device("shell", "input", "keyevent", str(code))


def wake() -> None:
    """Wake the screen without toggling it off (KEYCODE_WAKEUP = 224)."""
    keyevent(224)


def sleep_screen() -> None:
    """Put the screen to sleep (KEYCODE_SLEEP = 223)."""
    keyevent(223)


def recent_apps() -> None:
    """Open the Recent Apps switcher (KEYCODE_APP_SWITCH = 187)."""
    keyevent(187)


def home() -> None:
    """Press the Home button (KEYCODE_HOME = 3)."""
    keyevent(3)


def back() -> None:
    """Press the Back button (KEYCODE_BACK = 4)."""
    keyevent(4)


def volume_up() -> None:
    keyevent(24)   # KEYCODE_VOLUME_UP


def volume_down() -> None:
    keyevent(25)   # KEYCODE_VOLUME_DOWN


def push_clipboard_text(text: str) -> bool:
    """Push text to the device clipboard via ADB input text (best-effort).

    Works regardless of whether scrcpy is running.  Special characters are
    escaped; long strings may be truncated by the shell.
    Returns True if the shell command exited cleanly.
    """
    # escape single-quotes for the shell
    safe = text.replace("'", "\\'")
    rc, _, _ = _run_on_device(
        "shell",
        f"am broadcast -a clipper.set --es text '{safe}' 2>/dev/null"
        f" || input text '{safe}'",
        timeout=10,
    )
    return rc == 0


# ── URL / activity detection ──────────────────────────────────────────────────

def get_foreground_url() -> str | None:
    """Try to extract a URL from the current foreground activity via dumpsys.

    Looks for https:// / http:// strings in the activity stack dump.
    Most reliable when YouTube, Chrome, or a browser is in the foreground.
    Returns the first URL found, or None.
    """
    rc, out, _ = _run_on_device("shell", "dumpsys", "activity", "activities",
                                 timeout=8)
    if rc != 0 or not out:
        return None
    # Try intent data first — most reliable for YouTube, Chrome, browsers
    # e.g. "dat=https://www.youtube.com/watch?v=abc123"
    m = re.search(r'dat=(https?://[^\s"\'\\>)]+)', out)
    if m:
        return m.group(1).rstrip(").,;")
    # Fallback: any URL in the dump
    m = re.search(r'https?://[^\s"\'\\>]+', out)
    return m.group(0).rstrip(").,;") if m else None
