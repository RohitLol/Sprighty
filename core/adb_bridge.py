import ipaddress
import re
import shlex
import subprocess
from typing import Optional

from models.device import Device, DeviceState, Transport
from utils.vendor_paths import adb_exe

# Serial of the currently selected / active device.
# Set this whenever the user picks a device in the UI.
_target_serial: str = ""
_last_swipe_time = 0.0


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


def _validate_ip_port(ip: str, port: int) -> None:
    """Raise ValueError if ip or port are not valid."""
    ipaddress.ip_address(ip)  # raises ValueError on invalid input
    if not (1 <= port <= 65535):
        raise ValueError(f"Port {port} is out of range 1-65535")


def connect(ip: str, port: int) -> tuple[bool, str]:
    _validate_ip_port(ip, port)
    rc, stdout, stderr = _run("connect", f"{ip}:{port}")
    output = stdout.strip() or stderr.strip()
    success = "connected" in output.lower() and "unable" not in output.lower()
    return success, output


def disconnect(serial: str) -> None:
    _run("disconnect", serial)


def pair(ip: str, pairing_port: int, code: str) -> tuple[bool, str]:
    _validate_ip_port(ip, pairing_port)
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


def swipe_h(direction: int) -> None:
    """Horizontal swipe gesture on the device.

    Parameters
    ----------
    direction : +1 = swipe right (previous item / scroll back)
               -1 = swipe left  (next item / scroll forward)
    """
    global _last_swipe_time
    import time
    now = time.time()
    if now - _last_swipe_time < 0.2: # 200ms debounce
        return
    _last_swipe_time = now

    # Query actual display size so coordinates work on any resolution.
    rc, out, _ = _run_on_device("shell", "wm", "size", timeout=3)
    w, h = 1080, 2400   # safe fallback
    if rc == 0:
        m = re.search(r'(\d+)x(\d+)', out)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
    cx, cy = w // 2, h // 2
    offset = w // 3     # swipe ≈ 33 % of screen width
    if direction > 0:   # swipe right → previous item
        x1, x2 = cx - offset, cx + offset
    else:               # swipe left → next item
        x1, x2 = cx + offset, cx - offset
    _run_on_device("shell", "input", "swipe",
                   str(x1), str(cy), str(x2), str(cy), "200")


def push_clipboard_text(text: str) -> bool:
    """Push text to the device clipboard via ADB input text (best-effort).

    Works regardless of whether scrcpy is running.  Special characters are
    escaped; long strings may be truncated by the shell.
    Returns True if the shell command exited cleanly.
    """
    safe = shlex.quote(text)
    rc, _, _ = _run_on_device(
        "shell",
        f"am broadcast -a clipper.set --es text {safe} 2>/dev/null"
        f" || input text {safe}",
        timeout=10,
    )
    return rc == 0


# ── URL / media detection ─────────────────────────────────────────────────────

def _extract_title_artist(dump: str) -> tuple[str, str]:
    """Pull TITLE and ARTIST out of a dumpsys media_session blob."""
    title = artist = ""
    m = re.search(r'android\.media\.metadata\.TITLE\s*=\s*(.+)', dump)
    if m:
        title = m.group(1).strip().strip('"\'')
    else:
        m = re.search(r'(?m)^\s*TITLE\s*=\s*(.+)', dump)
        if m:
            title = m.group(1).strip().strip('"\'')

    m = re.search(r'android\.media\.metadata\.ARTIST\s*=\s*(.+)', dump)
    if m:
        artist = m.group(1).strip().strip('"\'')
    else:
        m = re.search(r'(?m)^\s*ARTIST\s*=\s*(.+)', dump)
        if m:
            artist = m.group(1).strip().strip('"\'')

    return title, artist


def _get_pixel_now_playing() -> tuple[str, str] | None:
    """Query Pixel Now Playing history (ambient music recognition).

    Returns (title, artist) of the most recently detected song, or None if
    unavailable (non-Pixel device, no song detected, or provider missing).
    """
    try:
        rc, output, _ = _run_on_device(
            "shell",
            "content query"
            " --uri content://com.google.android.as.shared/nowplaying/history"
            " --projection title:artist"
            " | head -5",
            timeout=5,
        )
        if rc != 0 or not output.strip():
            return None
        title_m  = re.search(r'title=([^,\n}]+)', output)
        artist_m = re.search(r'artist=([^,\n}]+)', output)
        if title_m:
            title  = title_m.group(1).strip().strip('"\'')
            artist = artist_m.group(1).strip().strip('"\'') if artist_m else ""
            return (title, artist)
    except Exception:
        pass
    return None


def get_foreground_url() -> str | None:
    """Return the URL of whatever media/page is active in the foreground app.

    Detection strategy
    ------------------
    Both ADB calls use on-device grep/head so only a handful of lines are
    transferred over WiFi — the full ``dumpsys`` output can be megabytes and
    causes silent TimeoutExpired exceptions that the worker swallows as None.

    1. ``dumpsys media_session | grep …`` — grabs artUri / mediaId lines for
       YouTube (i.ytimg.com thumbnail URL is always present when playing) and
       Spotify/Netflix URIs.
    2. ``dumpsys activity top | grep …`` — grabs TASK/ACTIVITY/URL lines to
       identify the foreground package and browser tab URLs.

    Supported apps
    --------------
    YouTube / YT Music  — video ID from media session ART_URI or MEDIA_ID
    Spotify             — spotify:…:ID URI  →  open.spotify.com URL
    Browser             — intent dat= URL from the current task
    Any other app       — falls back to any https URL in the activity dump
    """
    # ── Step 1: three parallel on-device greps ───────────────────────────────
    # All three run concurrently via separate _run_on_device calls; each uses
    # on-device grep/head to keep WiFi transfer tiny.

    # 1a. mCurrentFocus — most reliable foreground package across Android 12-15
    rc_w, win_lines, _ = _run_on_device(
        "shell",
        "dumpsys window windows | grep mCurrentFocus | head -3",
        timeout=5,
    )
    win_dump = win_lines if rc_w == 0 else ""

    # 1b. Media session — enriched grep captures TITLE/ARTIST for fallback
    rc_m, ms_lines, _ = _run_on_device(
        "shell",
        "dumpsys media_session"
        " | grep -iE"
        " 'ytimg|yt:video|spotify:|netflix|artUri|mediaId|ART_URI|MEDIA_ID"
        "|packageName|Package name|TITLE=|ARTIST=|android\\.media\\.metadata'"
        " | head -50",
        timeout=8,
    )
    ms_dump = ms_lines if rc_m == 0 else ""

    # 1c. Activity top — URL lines for browsers
    rc_t, top_lines, _ = _run_on_device(
        "shell",
        "dumpsys activity top"
        " | grep -E 'TASK |ACTIVITY |dat=|https://|youtube|spotify|netflix|chrome|firefox'"
        " | head -30",
        timeout=8,
    )
    out_t = top_lines if rc_t == 0 else ""

    # ── Step 2: Detect foreground package ────────────────────────────────────
    pkg = ""

    # Primary: mCurrentFocus  →  "Window{… com.google.android.youtube/…Activity}"
    if win_dump:
        m = re.search(r'mCurrentFocus=Window\{[^}]+ ([a-z][a-zA-Z0-9_.]+)/\S+\}',
                      win_dump)
        if m:
            pkg = m.group(1).lower()

    # Fallback: TASK / ACTIVITY lines from activity top
    if not pkg and out_t:
        m = re.search(r'^\s*TASK\s+(\S+)', out_t, re.MULTILINE)
        if m:
            pkg = m.group(1).lower()
        else:
            m = re.search(r'ACTIVITY\s+([a-z][a-zA-Z0-9_.]+)/', out_t)
            if m:
                pkg = m.group(1).lower()

    # Fallback: packageName= field in media session
    if not pkg and ms_dump:
        m = re.search(r'[Pp]ackage[Nn]ame\s*=\s*["\']?([a-z][a-z0-9_.]+)["\']?',
                      ms_dump)
        if m:
            pkg = m.group(1).lower()

    # Last resort: substring scan
    if not pkg:
        combined = (out_t + ms_dump + win_dump).lower()
        for candidate in ("youtube", "spotify", "netflix", "chrome", "firefox"):
            if candidate in combined:
                pkg = candidate
                break

    # ── YouTube / YouTube Music ───────────────────────────────────────────────
    if "youtube" in pkg:
        # Check media_session FIRST — ART_URI thumbnail is the most reliable
        # signal; it's present even when the activity dump parsing is flaky.
        for dump in (ms_dump, out_t):
            # ① ART_URI: "https://i.ytimg.com/vi/VIDEO_ID/hqdefault.jpg"
            m = re.search(r'i\.ytimg\.com/vi/([a-zA-Z0-9_-]{11})', dump)
            if m:
                return f"https://www.youtube.com/watch?v={m.group(1)}"
            # ② MEDIA_ID: "yt:video:VIDEO_ID"
            m = re.search(r'yt:video:([a-zA-Z0-9_-]{11})', dump)
            if m:
                return f"https://www.youtube.com/watch?v={m.group(1)}"
            # ③ videoId=XXXXXXXXXX in fragment arguments
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

        # ⑦ Title search fallback — YouTube Music or any YouTube app where the
        #    video ID isn't in the media session (e.g. Shorts feed, Home screen).
        title, _ = _extract_title_artist(ms_dump)
        if title:
            from urllib.parse import quote_plus
            return f"https://www.youtube.com/results?search_query={quote_plus(title)}"

        # YouTube is open but nothing identifiable — stop here to avoid
        # returning a stale URL from a background session.
        return None

    # ── Spotify ───────────────────────────────────────────────────────────────
    if "spotify" in pkg:
        m = re.search(r'spotify:(track|episode|album|playlist|show):([a-zA-Z0-9]+)',
                      ms_dump + out_t)
        if m:
            return f"https://open.spotify.com/{m.group(1)}/{m.group(2)}"
        return None

    # ── Netflix ───────────────────────────────────────────────────────────────
    if "netflix" in pkg:
        m = re.search(r'netflix\.com/(?:watch|title)/(\d+)', out_t + ms_dump)
        if m:
            return f"https://www.netflix.com/watch/{m.group(1)}"
        return None

    # ── Browser (Chrome, Firefox, Edge, Samsung Internet …) ──────────────────
    _BROWSERS = ("chrome", "firefox", "edge", "samsung", "brave", "opera",
                 "vivaldi", "browser")
    if any(b in pkg for b in _BROWSERS):
        m = re.search(r'dat=(https?://[^\s"\'\\>)]+)', out_t)
        if m:
            return m.group(1).rstrip(").,;")
        m = re.search(r'https?://(?!localhost)[^\s"\'\\>)]+', out_t)
        if m:
            return m.group(0).rstrip(").,;")
        return None

    # ── Generic fallback ──────────────────────────────────────────────────────
    m = re.search(r'dat=(https?://[^\s"\'\\>)]+)', out_t)
    if m:
        return m.group(1).rstrip(").,;")
    m = re.search(r'https?://(?!localhost)[^\s"\'\\>)]+', out_t)
    if m:
        return m.group(0).rstrip(").,;")

    # ── Pixel Now Playing (last resort) ───────────────────────────────────────
    # Ambient music recognition history — Pixel-only, silent on other devices.
    now_playing = _get_pixel_now_playing()
    if now_playing:
        from urllib.parse import quote_plus
        title, artist = now_playing
        query = f"{title} {artist}".strip()
        return f"https://www.youtube.com/results?search_query={quote_plus(query)}"

    return None
