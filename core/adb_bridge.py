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

        # Match both  192.168.x.x:port  and  adb-XXXX._adb-tls-connect._tcp.local:port
        _is_ip_port  = bool(re.match(r"^\d+\.\d+\.\d+\.\d+:\d+$", serial))
        _is_mdns     = bool(re.search(r"_tcp.*:\d+$", serial))
        transport = Transport.TCPIP if (_is_ip_port or _is_mdns) else Transport.USB

        model = ""
        for part in parts[2:]:
            if part.startswith("model:"):
                model = part.split(":", 1)[1].replace("_", " ")
                break

        ip, port = "", 5555
        if transport == Transport.TCPIP:
            if _is_ip_port:
                ip, _, p = serial.partition(":")
                port = int(p) if p.isdigit() else 5555
            else:
                # mDNS serial — extract port from the trailing :PORT
                m = re.search(r":(\d+)$", serial)
                if m:
                    port = int(m.group(1))

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


# ── URL / media detection ─────────────────────────────────────────────────────

def get_foreground_url() -> str | None:
    """Return the URL of whatever media/page is active in the foreground app.

    Unlike a generic URL search, this is foreground-aware:
    • detects which app is visible via ``dumpsys activity top``
    • runs app-specific extraction so a background Reddit tab never
      contaminates a YouTube result (the old bug)

    Supported apps
    --------------
    YouTube / YT Music  — video ID from activity arguments or media session
    Spotify             — spotify:…:ID URI  →  open.spotify.com URL
    Browser             — intent dat= URL from the current task
    Any other app       — falls back to any https URL in the activity dump
    """
    # ── Step 1: foreground activity dump ─────────────────────────────────────
    # ``dumpsys activity top`` shows ONLY the currently visible task/activity.
    # The first TASK line tells us the package; the rest may contain the URL.
    rc_t, out_t, _ = _run_on_device("shell", "dumpsys", "activity", "top",
                                     timeout=8)
    out_t = out_t if rc_t == 0 else ""

    pkg = ""
    if out_t:
        # Android 14 indents the TASK line with leading spaces — use \s* not ^
        m = re.search(r'^\s*TASK\s+(\S+)', out_t, re.MULTILINE)
        if m:
            pkg = m.group(1).lower()
        else:
            # Fallback: grab package from the ACTIVITY line  e.g.
            # "  ACTIVITY com.google.android.youtube/.HomeActivity …"
            m = re.search(r'ACTIVITY\s+([a-z][a-zA-Z0-9_.]+)/', out_t)
            if m:
                pkg = m.group(1).lower()

    # If pkg detection still failed, peek at the media session to infer the app
    ms_dump = ""
    def _media_session() -> str:
        nonlocal ms_dump
        if not ms_dump:
            rc, out, _ = _run_on_device("shell", "dumpsys", "media_session", timeout=8)
            ms_dump = out if rc == 0 else ""
        return ms_dump

    # Infer package from media session when TASK/ACTIVITY parsing failed
    if not pkg:
        ms = _media_session()
        for candidate in ("youtube", "spotify", "netflix", "chrome", "firefox"):
            if candidate in ms.lower():
                pkg = candidate
                break

    # ── YouTube / YouTube Music ───────────────────────────────────────────────
    if "youtube" in pkg:
        for dump in (out_t, _media_session()):
            # ① Best signal: thumbnail ART_URI always contains the video ID.
            #   e.g. "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
            m = re.search(r'i\.ytimg\.com/vi/([a-zA-Z0-9_-]{11})/', dump)
            if m:
                return f"https://www.youtube.com/watch?v={m.group(1)}"
            # ② MEDIA_ID field: "yt:video:VIDEO_ID" or just the raw 11-char ID
            m = re.search(r'yt:video:([a-zA-Z0-9_-]{11})', dump)
            if m:
                return f"https://www.youtube.com/watch?v={m.group(1)}"
            # ③ videoId=XXXXXXXXXXX in fragment arguments (internally-navigated)
            m = re.search(r'[Vv]ideo[Ii]d[":\s=]+([a-zA-Z0-9_-]{11})', dump)
            if m:
                return f"https://www.youtube.com/watch?v={m.group(1)}"
            # ④ Explicit watch URL
            m = re.search(r'watch\?v=([a-zA-Z0-9_-]{11})', dump)
            if m:
                return f"https://www.youtube.com/watch?v={m.group(1)}"
            # ⑤ Shorts
            m = re.search(r'/shorts/([a-zA-Z0-9_-]{11})', dump)
            if m:
                return f"https://www.youtube.com/shorts/{m.group(1)}"
            # ⑥ Live streams
            m = re.search(r'youtube\.com/live/([a-zA-Z0-9_-]{11})', dump)
            if m:
                return f"https://www.youtube.com/live/{m.group(1)}"
        # YouTube is open but we couldn't identify the video — stop here.
        # Do NOT fall through: we'd return a stale URL from a background app.
        return None

    # ── Spotify ───────────────────────────────────────────────────────────────
    if "spotify" in pkg:
        ms = _media_session()
        m = re.search(r'spotify:(track|episode|album|playlist|show):([a-zA-Z0-9]+)',
                      ms)
        if m:
            return f"https://open.spotify.com/{m.group(1)}/{m.group(2)}"
        return None

    # ── Netflix ───────────────────────────────────────────────────────────────
    if "netflix" in pkg:
        ms = _media_session()
        # Netflix activity top usually has the content ID in the intent URI
        m = re.search(r'netflix\.com/(?:watch|title)/(\d+)', out_t + ms)
        if m:
            return f"https://www.netflix.com/watch/{m.group(1)}"
        return None

    # ── Browser (Chrome, Firefox, Edge, Samsung Internet …) ──────────────────
    _BROWSERS = ("chrome", "firefox", "edge", "samsung", "brave", "opera",
                 "vivaldi", "browser")
    if any(b in pkg for b in _BROWSERS):
        # dat= is the reliable source for browser current-tab URLs
        m = re.search(r'dat=(https?://[^\s"\'\\>)]+)', out_t)
        if m:
            return m.group(1).rstrip(").,;")
        # Broader scan of the top-activity dump (some browsers store URL differently)
        m = re.search(r'https?://(?!localhost)[^\s"\'\\>)]+', out_t)
        if m:
            return m.group(0).rstrip(").,;")
        return None

    # ── Generic fallback (unknown app) ────────────────────────────────────────
    # Only the TOP activity is searched — avoids picking up stale background URLs.
    m = re.search(r'dat=(https?://[^\s"\'\\>)]+)', out_t)
    if m:
        return m.group(1).rstrip(").,;")
    m = re.search(r'https?://(?!localhost)[^\s"\'\\>)]+', out_t)
    if m:
        return m.group(0).rstrip(").,;")

    return None
