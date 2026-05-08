import ctypes
import ctypes.wintypes

import psutil
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import (
    QColor, QCursor, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

user32 = ctypes.windll.user32

GWL_STYLE         = -16
GWL_EXSTYLE       = -20
WS_CHILD          = 0x40000000
WS_VISIBLE        = 0x10000000
WS_CLIPSIBLINGS   = 0x04000000
WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE  = 0x08000000

# Windows hook constants
WH_MOUSE_LL    = 14
WH_KEYBOARD_LL = 13
WM_MBUTTONDOWN = 0x0207
WM_MOUSEWHEEL  = 0x020A
WM_KEYDOWN     = 0x0100
WM_SYSKEYDOWN  = 0x0104
VK_LEFT        = 0x25
VK_RIGHT       = 0x26
VK_SHIFT       = 0x10

# ── 64-bit–safe ctypes aliases ─────────────────────────────────────────────────
_LRESULT = ctypes.c_ssize_t
_WPARAM  = ctypes.c_size_t
_LPARAM  = ctypes.c_ssize_t

user32.SetWindowsHookExW.restype  = ctypes.wintypes.HHOOK
user32.CallNextHookEx.restype     = _LRESULT
user32.CallNextHookEx.argtypes    = [ctypes.wintypes.HHOOK,
                                     ctypes.c_int, _WPARAM, _LPARAM]
user32.UnhookWindowsHookEx.argtypes = [ctypes.wintypes.HHOOK]

# ── Windows low-level mouse hook ───────────────────────────────────────────────

class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt",          ctypes.wintypes.POINT),
        ("mouseData",   ctypes.wintypes.DWORD),
        ("flags",       ctypes.wintypes.DWORD),
        ("time",        ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      ctypes.wintypes.DWORD),
        ("scanCode",    ctypes.wintypes.DWORD),
        ("flags",       ctypes.wintypes.DWORD),
        ("time",        ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


_HookProc = ctypes.WINFUNCTYPE(_LRESULT, ctypes.c_int, _WPARAM, _LPARAM)


class _MiddleClickHook:
    """System-wide WH_MOUSE_LL hook.

    Handles:
    • Middle-click inside mirror     → fires ``_middle_cb``
    • Shift + scroll inside mirror   → fires ``_swipe_left_cb`` / ``_swipe_right_cb``
    """

    def __init__(self):
        self._hook_id       = None
        self._middle_cb     = None
        self._swipe_left_cb = None    # scroll-up  / next item
        self._swipe_right_cb= None    # scroll-down / prev item
        self._mirror_rect: QRect | None = None
        self._proc_ref = None

    def set_mirror_rect(self, rect: QRect | None) -> None:
        self._mirror_rect = rect

    def set_callback(self, cb) -> None:
        self._middle_cb = cb

    def set_swipe_callbacks(self, left_cb, right_cb) -> None:
        self._swipe_left_cb  = left_cb
        self._swipe_right_cb = right_cb

    def install(self) -> None:
        if self._hook_id:
            return

        def _proc(nCode: int, wParam: int, lParam: int) -> int:
            if nCode >= 0:
                rect = self._mirror_rect
                if wParam == WM_MBUTTONDOWN:
                    cb = self._middle_cb
                    if rect and cb:
                        try:
                            info = ctypes.cast(
                                lParam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                            if rect.contains(info.pt.x, info.pt.y):
                                cb()
                        except Exception:
                            pass
                elif wParam == WM_MOUSEWHEEL:
                    if rect:
                        try:
                            info = ctypes.cast(
                                lParam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                            if rect.contains(info.pt.x, info.pt.y):
                                shift = bool(
                                    user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
                                if shift:
                                    # High word of mouseData = signed wheel delta
                                    delta = ctypes.c_int16(
                                        info.mouseData >> 16).value
                                    if delta > 0 and self._swipe_left_cb:
                                        self._swipe_left_cb()   # up = next
                                    elif delta < 0 and self._swipe_right_cb:
                                        self._swipe_right_cb()  # down = prev
                                    return 1   # block from reaching scrcpy
                        except Exception:
                            pass
            return user32.CallNextHookEx(self._hook_id, nCode, wParam, lParam)

        self._proc_ref = _HookProc(_proc)
        self._hook_id  = user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._proc_ref, None, 0
        )

    def uninstall(self) -> None:
        if self._hook_id:
            user32.UnhookWindowsHookEx(self._hook_id)
            self._hook_id = None


class _KeyboardSwipeHook:
    """System-wide WH_KEYBOARD_LL hook.

    Intercepts Shift + Left / Shift + Right **when the cursor is inside the
    mirror rectangle** and converts them to horizontal swipe callbacks.
    All other keystrokes pass through unchanged.

    Cursor-in-rect guard prevents accidental interception while the user is
    working in another application.
    """

    def __init__(self):
        self._hook_id        = None
        self._proc_ref       = None
        self._mirror_rect: QRect | None = None
        self._swipe_left_cb  = None   # Shift+Right → next item
        self._swipe_right_cb = None   # Shift+Left  → prev item

    def set_mirror_rect(self, rect: QRect | None) -> None:
        self._mirror_rect = rect

    def set_callbacks(self, left_cb, right_cb) -> None:
        self._swipe_left_cb  = left_cb
        self._swipe_right_cb = right_cb

    def install(self) -> None:
        if self._hook_id:
            return

        def _proc(nCode: int, wParam: int, lParam: int) -> int:
            if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                rect = self._mirror_rect
                if rect:
                    try:
                        info = ctypes.cast(
                            lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                        vk = info.vkCode
                        if vk in (VK_LEFT, VK_RIGHT):
                            # Only intercept when cursor is over the mirror
                            pt = ctypes.wintypes.POINT()
                            user32.GetCursorPos(ctypes.byref(pt))
                            if rect.contains(pt.x, pt.y):
                                shift = bool(
                                    user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
                                if shift:
                                    if vk == VK_RIGHT and self._swipe_left_cb:
                                        self._swipe_left_cb()   # → next item
                                    elif vk == VK_LEFT and self._swipe_right_cb:
                                        self._swipe_right_cb()  # ← prev item
                                    return 1   # block keystroke from scrcpy
                    except Exception:
                        pass
            return user32.CallNextHookEx(self._hook_id, nCode, wParam, lParam)

        self._proc_ref = _HookProc(_proc)
        self._hook_id  = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._proc_ref, None, 0
        )

    def uninstall(self) -> None:
        if self._hook_id:
            user32.UnhookWindowsHookEx(self._hook_id)
            self._hook_id = None


_middle_click_hook   = _MiddleClickHook()
_keyboard_swipe_hook = _KeyboardSwipeHook()

# ── Screen dimensions (Pixel 8a 9:20 portrait) ────────────────────────────────
MIRROR_W = 360
MIRROR_H = 800

# ── Phone-frame bezel sizes ────────────────────────────────────────────────────
FRAME_T = 30   # top bezel  (camera punch-hole area)
FRAME_B = 35   # bottom bezel (chin)
FRAME_S = 14   # side bezels (each side)

PHONE_W = MIRROR_W + 2 * FRAME_S   # 388
PHONE_H = MIRROR_H + FRAME_T + FRAME_B  # 865


def _find_hwnd(title: str) -> int:
    return user32.FindWindowW(None, title)


def _embed(child_hwnd: int, parent_hwnd: int, w: int, h: int) -> None:
    user32.SetParent(child_hwnd, parent_hwnd)
    user32.SetWindowLongW(child_hwnd, GWL_STYLE,
                          WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS)
    # Do NOT set WS_EX_NOACTIVATE — it blocks SDL's SetCapture() during mouse
    # drags, which breaks swipe gestures.  Keyboard focus is managed via
    # explicit SetFocus() calls (Escape key + bezel click) instead.
    user32.MoveWindow(child_hwnd, 0, 0, w, h, True)


# ── Floating cursor dot ────────────────────────────────────────────────────────

class CursorDot(QWidget):
    """Frameless always-on-top dot that follows the cursor, fully click-through."""

    DOT_R = 6

    def __init__(self):
        super().__init__(None,
                         Qt.FramelessWindowHint |
                         Qt.WindowStaysOnTopHint |
                         Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(self.DOT_R * 2 + 4, self.DOT_R * 2 + 4)
        self._make_click_through()

        self._mirror_rect: QRect | None = None
        self._scrcpy_hwnd: int = 0
        self._visible = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def set_mirror_rect(self, rect: QRect | None):
        self._mirror_rect = rect

    def set_scrcpy_hwnd(self, hwnd: int):
        """Track the scrcpy SDL window handle so we can hide the dot when
        another window is layered on top of the mirror area."""
        self._scrcpy_hwnd = hwnd

    def _make_click_through(self):
        hwnd = int(self.winId())
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              ex | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)

    def _tick(self):
        if not self._mirror_rect or not self._scrcpy_hwnd:
            self._hide_dot()
            return
        gp = QCursor.pos()
        if not self._mirror_rect.contains(gp):
            self._hide_dot()
            return
        # Only show the dot when the cursor is actually over the scrcpy window —
        # not when another window (e.g. the Sprightly toolbar itself) happens to
        # cover the same screen region.  WindowFromPoint returns the topmost
        # visible window under the cursor, ignoring our own WS_EX_TRANSPARENT dot.
        pt = ctypes.wintypes.POINT(gp.x(), gp.y())
        hwnd_under = user32.WindowFromPoint(pt)
        if hwnd_under != self._scrcpy_hwnd:
            self._hide_dot()
            return
        self.move(gp.x() - self.DOT_R - 2, gp.y() - self.DOT_R - 2)
        if not self._visible:
            self.show()
            self._visible = True
        self.update()

    def _hide_dot(self):
        if self._visible:
            self.hide()
            self._visible = False

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 200), 1.5))
        p.setBrush(QColor(255, 255, 255, 90))
        r = self.DOT_R
        p.drawEllipse(2, 2, r * 2, r * 2)


# ── Mirror container ───────────────────────────────────────────────────────────

class MirrorContainer(QWidget):
    """
    Fixed-size (MIRROR_W × MIRROR_H) host for the embedded scrcpy SDL window.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(MIRROR_W, MIRROR_H)
        self.setStyleSheet("background:#06060A;")

        # ── Styled empty-state placeholder ────────────────────────────────────
        self._placeholder = QWidget(self)
        self._placeholder.resize(MIRROR_W, MIRROR_H)
        self._placeholder.setStyleSheet("background:transparent;")

        ph_lay = QVBoxLayout(self._placeholder)
        ph_lay.setAlignment(Qt.AlignCenter)
        ph_lay.setSpacing(8)

        _icon = QLabel("📱")
        _icon.setAlignment(Qt.AlignCenter)
        _icon.setStyleSheet(
            "font-size:52px; background:transparent; color:#1C1C2E;"
        )
        ph_lay.addWidget(_icon)

        _title = QLabel("No mirror active")
        _title.setAlignment(Qt.AlignCenter)
        _title.setStyleSheet(
            "color:#2A2A44; font-size:13px; font-weight:600;"
            "background:transparent; letter-spacing:0.5px;"
        )
        ph_lay.addWidget(_title)

        _hint = QLabel("Pick a device and press  Start Mirror")
        _hint.setAlignment(Qt.AlignCenter)
        _hint.setWordWrap(True)
        _hint.setStyleSheet(
            "color:#1A1A2E; font-size:11px; background:transparent;"
        )
        ph_lay.addWidget(_hint)

        self._scrcpy_hwnd: int = 0
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_for_hwnd)
        self._poll_attempts = 0
        self._search_title = ""

        self._dot = CursorDot()

        _middle_click_hook.install()
        _keyboard_swipe_hook.install()

    # ── public ────────────────────────────────────────────────────────────────

    @property
    def scrcpy_hwnd(self) -> int:
        return self._scrcpy_hwnd

    def request_scrcpy_focus(self) -> bool:
        """Give keyboard focus to the embedded scrcpy window.

        Call this after any UI interaction that may have stolen Win32 focus
        (toolbar clicks, file-panel, etc.) so keyboard input flows to scrcpy again.
        Returns True if the HWND was found and focused.
        """
        if self._scrcpy_hwnd:
            user32.SetFocus(self._scrcpy_hwnd)
            return True
        return False

    def set_middle_click_callback(self, cb) -> None:
        _middle_click_hook.set_callback(cb)

    def set_swipe_callbacks(self, left_cb, right_cb) -> None:
        """Register callbacks for horizontal swipe gestures.

        ``left_cb``  is called to swipe left  (next carousel item / scroll right).
        ``right_cb`` is called to swipe right (prev carousel item / scroll left).

        Triggered by:
        • Shift + Right Arrow   (cursor over mirror) → left_cb
        • Shift + Left Arrow    (cursor over mirror) → right_cb
        • Shift + Scroll Up     (cursor over mirror) → left_cb
        • Shift + Scroll Down   (cursor over mirror) → right_cb
        """
        _middle_click_hook.set_swipe_callbacks(left_cb, right_cb)
        _keyboard_swipe_hook.set_callbacks(left_cb, right_cb)

    def start_embedding(self, window_title: str):
        self._search_title = window_title
        self._scrcpy_hwnd = 0
        self._poll_attempts = 0
        self._placeholder.show()
        self._poll_timer.start(300)

    def stop_embedding(self):
        self._poll_timer.stop()
        self._scrcpy_hwnd = 0
        self._dot.set_mirror_rect(None)
        self._dot.set_scrcpy_hwnd(0)
        _middle_click_hook.set_mirror_rect(None)
        _keyboard_swipe_hook.set_mirror_rect(None)
        self._placeholder.show()

    def cleanup(self):
        """Uninstall global hooks and close the cursor dot overlay."""
        _middle_click_hook.uninstall()
        _keyboard_swipe_hook.uninstall()
        self._dot.close()

    # ── internal ──────────────────────────────────────────────────────────────

    def _poll_for_hwnd(self):
        self._poll_attempts += 1
        if self._poll_attempts > 40:
            self._poll_timer.stop()
            return

        hwnd = _find_hwnd(self._search_title)
        if not hwnd:
            return

        self._poll_timer.stop()
        self._scrcpy_hwnd = hwnd
        self._do_embed()

    def mousePressEvent(self, event):
        """Give keyboard focus to the embedded scrcpy window on click."""
        if self._scrcpy_hwnd:
            user32.SetFocus(self._scrcpy_hwnd)
        super().mousePressEvent(event)

    def _do_embed(self):
        parent_hwnd = int(self.winId())
        _embed(self._scrcpy_hwnd, parent_hwnd, MIRROR_W, MIRROR_H)
        self._placeholder.hide()
        self._dot.set_scrcpy_hwnd(self._scrcpy_hwnd)
        self._update_dot_rect()

    def _update_dot_rect(self):
        tl = self.mapToGlobal(QPoint(0, 0))
        rect = QRect(tl.x(), tl.y(), MIRROR_W, MIRROR_H)
        self._dot.set_mirror_rect(rect)
        _middle_click_hook.set_mirror_rect(rect)
        _keyboard_swipe_hook.set_mirror_rect(rect)

    def moveEvent(self, event):
        super().moveEvent(event)
        self._update_dot_rect()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._dot.set_mirror_rect(None)
        _middle_click_hook.set_mirror_rect(None)
        _keyboard_swipe_hook.set_mirror_rect(None)


# ── Phone body frame ───────────────────────────────────────────────────────────

# Outer corner radius of the phone body
_BODY_RADIUS = 26.0
# Inner screen corner radius (slight rounding on the screen edges)
_SCREEN_RADIUS = 4.0

# Body colour — near-black with a cool undertone
_BODY_COLOR   = QColor(0x16, 0x16, 0x1C)
_BODY_EDGE    = QColor(0x32, 0x32, 0x42)   # rim highlight
_SCREEN_EDGE  = QColor(0x24, 0x24, 0x34)   # screen bezel edge
_CAMERA_COLOR = QColor(0x0E, 0x0E, 0x14)
_BTN_COLOR    = QColor(0x12, 0x12, 0x18)
_BTN_EDGE     = QColor(0x2C, 0x2C, 0x3A)


class PhoneFrame(QWidget):
    """Decorative Pixel 8a–style body drawn around the MirrorContainer.

    Provides the same public API as MirrorContainer so MainWindow can treat
    it as a drop-in replacement.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(PHONE_W, PHONE_H)

        # Place the real mirror widget at (FRAME_S, FRAME_T)
        self._mirror = MirrorContainer(self)
        self._mirror.move(FRAME_S, FRAME_T)

    # ── Proxy API ─────────────────────────────────────────────────────────────

    @property
    def scrcpy_hwnd(self) -> int:
        return self._mirror.scrcpy_hwnd

    def request_scrcpy_focus(self) -> bool:
        return self._mirror.request_scrcpy_focus()

    def set_middle_click_callback(self, cb) -> None:
        self._mirror.set_middle_click_callback(cb)

    def set_swipe_callbacks(self, left_cb, right_cb) -> None:
        self._mirror.set_swipe_callbacks(left_cb, right_cb)

    def start_embedding(self, window_title: str) -> None:
        self._mirror.start_embedding(window_title)

    def stop_embedding(self) -> None:
        self._mirror.stop_embedding()

    def cleanup(self) -> None:
        self._mirror.cleanup()

    def mousePressEvent(self, event):
        """Clicking anywhere on the phone body (bezels included) refocuses scrcpy."""
        self._mirror.request_scrcpy_focus()
        super().mousePressEvent(event)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        w = float(self.width())
        h = float(self.height())
        sx = float(FRAME_S)
        sy = float(FRAME_T)
        sw = float(MIRROR_W)
        sh = float(MIRROR_H)

        # ── Full phone body ────────────────────────────────────────────────────
        body = QPainterPath()
        body.addRoundedRect(0.0, 0.0, w, h, _BODY_RADIUS, _BODY_RADIUS)

        # ── Screen cutout (leave child widget visible through the frame) ───────
        screen_hole = QPainterPath()
        screen_hole.addRoundedRect(sx, sy, sw, sh, _SCREEN_RADIUS, _SCREEN_RADIUS)

        frame_path = body.subtracted(screen_hole)

        # Draw frame body
        p.setBrush(_BODY_COLOR)
        p.setPen(QPen(_BODY_EDGE, 1.5))
        p.drawPath(frame_path)

        # Inner screen edge (subtle bezel line)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_SCREEN_EDGE, 1.2))
        inner = QPainterPath()
        inner.addRoundedRect(sx, sy, sw, sh, _SCREEN_RADIUS, _SCREEN_RADIUS)
        p.drawPath(inner)

        # ── Camera punch-hole ──────────────────────────────────────────────────
        cx = w / 2.0
        cy = sy / 2.0
        cam_r = 5.0
        p.setBrush(_CAMERA_COLOR)
        p.setPen(QPen(_BTN_EDGE, 1.0))
        p.drawEllipse(cx - cam_r, cy - cam_r, cam_r * 2, cam_r * 2)

        # ── Side buttons ───────────────────────────────────────────────────────
        p.setBrush(_BTN_COLOR)
        p.setPen(QPen(_BTN_EDGE, 1.0))

        # Volume Up / Down — left side
        vol_x    = -3.0
        vol_w    = 5.0
        vol_up_y = h * 0.27
        vol_dn_y = h * 0.38
        vol_h    = h * 0.09
        p.drawRoundedRect(vol_x, vol_up_y, vol_w, vol_h, 2.0, 2.0)
        p.drawRoundedRect(vol_x, vol_dn_y, vol_w, vol_h, 2.0, 2.0)

        # Power — right side
        pwr_x = w - 2.0
        pwr_y = h * 0.31
        pwr_h = h * 0.11
        p.drawRoundedRect(pwr_x, pwr_y, vol_w, pwr_h, 2.0, 2.0)
