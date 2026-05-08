"""
Side panel: full-featured file browser + photo grid powered by adb_files.

File Browser features
---------------------
* List view  ↔  Grid view toggle
* Sort by Name / Size / Type  (ascending / descending)
* Multi-select (Ctrl+Click, Shift+Click)
* Pull selected files to ~/Downloads  (threaded, with progress bar)
* Drop files from Windows Explorer → push to current phone directory
* Breadcrumb path bar + back button + refresh
* Status line with item count and transfer feedback

Photo Grid
----------
* One-click load thumbnails (threaded, cached)
* Multi-select + batch save to Downloads
* Grid auto-reflows on panel resize
"""

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import (
    QMimeData, QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl,
    Signal,
)
from PySide6.QtGui import QDrag, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core import adb_files


# ─────────────────────────────────────────────────────────────────────────────
# Worker helpers
# ─────────────────────────────────────────────────────────────────────────────

class _Signals(QObject):
    done   = Signal(str, bool, str)   # name, ok, msg
    thumb  = Signal(str, str)         # remote_path, local_path


class _ListDirSignals(QObject):
    done = Signal(object)   # list[FileEntry] — object avoids cross-thread marshal issues


class _ListDirWorker(QRunnable):
    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.signals = _ListDirSignals()
        self.setAutoDelete(False)   # keep alive until signal is delivered

    def run(self):
        entries = adb_files.list_dir(self.path)
        self.signals.done.emit(entries)


class _ScanPhotosSignals(QObject):
    done = Signal(object)   # list[str] — object avoids cross-thread marshal issues


class _ScanPhotosWorker(QRunnable):
    def __init__(self, max_count: int):
        super().__init__()
        self.max_count = max_count
        self.signals = _ScanPhotosSignals()
        self.setAutoDelete(False)   # keep alive until signal is delivered

    def run(self):
        photos = adb_files.list_photos(self.max_count)
        self.signals.done.emit(photos)


class _PullWorker(QRunnable):
    def __init__(self, remote_path: str, local_dir: str):
        super().__init__()
        self.remote_path = remote_path
        self.local_dir   = local_dir
        self.signals     = _Signals()

    def run(self):
        ok, msg = adb_files.pull_file(self.remote_path, self.local_dir)
        self.signals.done.emit(Path(self.remote_path).name, ok, msg)


class _PushWorker(QRunnable):
    def __init__(self, local_path: str, remote_dir: str):
        super().__init__()
        self.local_path = local_path
        self.remote_dir = remote_dir
        self.signals    = _Signals()

    def run(self):
        ok, msg = adb_files.push_file(self.local_path, self.remote_dir)
        self.signals.done.emit(Path(self.local_path).name, ok, msg)


class _ThumbWorker(QRunnable):
    def __init__(self, remote_path: str, cache_dir: str):
        super().__init__()
        self.remote    = remote_path
        self.cache_dir = cache_dir
        self.signals   = _Signals()

    def run(self):
        local = adb_files.pull_thumbnail(self.remote, self.cache_dir)
        if local:
            self.signals.thumb.emit(self.remote, local)


# ─────────────────────────────────────────────────────────────────────────────
# Drop-enabled list widget
# ─────────────────────────────────────────────────────────────────────────────

class _DropList(QListWidget):
    """QListWidget that accepts drops from Windows Explorer and supports drag-out."""
    files_dropped = Signal(list)   # list[str] of local paths

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)                            # enable drag initiation
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)
        self._cache_dir = tempfile.mkdtemp(prefix="sprightly_drag_")
        # Callable set by parent so startDrag can update the status label
        # signature: fn(msg, *, success=False, error=False)
        self.status_fn = None

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = []
            for url in event.mimeData().urls():
                local = url.toLocalFile()
                if local and os.path.isfile(local):
                    paths.append(local)
            if paths:
                self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def startDrag(self, supported_actions):
        """Drag selected files out to Windows Explorer / PC desktop.

        Pulls each selected file from the phone to a local temp directory first,
        then hands a file:// URL list to the OS drag engine.  The pull is
        synchronous (blocks briefly) — a status message is shown during it.
        """
        items = self.selectedItems()
        if not items:
            return

        file_items = [i for i in items
                      if (e := i.data(Qt.UserRole)) and e and not e.is_dir]
        if not file_items:
            return   # can't drag directories

        n = len(file_items)
        if self.status_fn:
            self.status_fn(f"Pulling {n} file{'s' if n > 1 else ''} — please wait…")
            QApplication.processEvents()   # let the label paint before blocking

        local_paths = []
        for item in file_items:
            entry = item.data(Qt.UserRole)
            ok, _ = adb_files.pull_file(entry.path, self._cache_dir)
            if ok:
                local = os.path.join(self._cache_dir, entry.name)
                if os.path.exists(local):
                    local_paths.append(local)

        if not local_paths:
            if self.status_fn:
                self.status_fn("Drag failed — check device connection.", error=True)
            return

        if self.status_fn:
            self.status_fn(f"Drop anywhere on your PC to save {n} file{'s' if n > 1 else ''}…")

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in local_paths])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)

        if self.status_fn:
            self.status_fn(f"{len(self._items_text(file_items))} item(s) saved to PC")

    @staticmethod
    def _items_text(items) -> list[str]:
        return [i.text() for i in items if i]


# ─────────────────────────────────────────────────────────────────────────────
# File Browser Tab
# ─────────────────────────────────────────────────────────────────────────────

_SORT_ICON_ASC  = "↑"
_SORT_ICON_DESC = "↓"

class FileBrowserTab(QWidget):
    ROOT = "/storage/emulated/0"   # real path — avoids top-level /sdcard symlink

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path_stack: list[str]    = [self.ROOT]
        self._entries:    list[adb_files.FileEntry] = []
        self._sort_key    = "name"      # "name" | "size" | "type"
        self._sort_asc    = True
        self._view_mode   = "list"      # "list" | "grid"
        self._pool        = QThreadPool.globalInstance()
        self._pending     = 0           # in-flight transfer count
        self._list_worker: _ListDirWorker | None = None   # keep ref until signal fires
        self._setup_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        # ── Top bar: back + path + refresh ───────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(4)

        self._btn_back = QToolButton()
        self._btn_back.setText("←")
        self._btn_back.setToolTip("Go back")
        self._btn_back.setEnabled(False)
        self._btn_back.clicked.connect(self._go_back)
        top.addWidget(self._btn_back)

        self._path_label = QLabel(self.ROOT)
        self._path_label.setStyleSheet("font-size:11px;")
        self._path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top.addWidget(self._path_label)

        btn_refresh = QToolButton()
        btn_refresh.setText("↻")
        btn_refresh.setToolTip("Refresh")
        btn_refresh.clicked.connect(self._refresh)
        top.addWidget(btn_refresh)

        lay.addLayout(top)

        # ── Sort + view controls ─────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setSpacing(4)

        sort_lbl = QLabel("Sort:")
        sort_lbl.setStyleSheet("font-size:11px;")
        ctrl.addWidget(sort_lbl)

        for key, label in [("name", "Name"), ("size", "Size"), ("type", "Type")]:
            btn = QPushButton(label)
            btn.setProperty("sortKey", key)
            btn.setCheckable(True)
            btn.setChecked(key == self._sort_key)
            btn.setFixedHeight(24)
            btn.setStyleSheet("font-size:11px; padding: 2px 8px;")
            btn.clicked.connect(lambda checked, k=key: self._set_sort(k))
            setattr(self, f"_sort_btn_{key}", btn)
            ctrl.addWidget(btn)

        self._sort_dir_btn = QToolButton()
        self._sort_dir_btn.setText(_SORT_ICON_ASC)
        self._sort_dir_btn.setToolTip("Toggle sort direction")
        self._sort_dir_btn.clicked.connect(self._toggle_sort_dir)
        ctrl.addWidget(self._sort_dir_btn)

        ctrl.addStretch()

        # View mode buttons
        self._btn_list = QToolButton()
        self._btn_list.setText("☰")
        self._btn_list.setToolTip("List view")
        self._btn_list.setCheckable(True)
        self._btn_list.setChecked(True)
        self._btn_list.clicked.connect(lambda: self._set_view("list"))
        ctrl.addWidget(self._btn_list)

        self._btn_grid = QToolButton()
        self._btn_grid.setText("⊞")
        self._btn_grid.setToolTip("Grid view")
        self._btn_grid.setCheckable(True)
        self._btn_grid.clicked.connect(lambda: self._set_view("grid"))
        ctrl.addWidget(self._btn_grid)

        lay.addLayout(ctrl)

        # ── File list ─────────────────────────────────────────────────────────
        self._list = _DropList()
        self._list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._list.setStyleSheet("font-size:12px;")
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.files_dropped.connect(self._on_files_dropped)
        self._list.itemSelectionChanged.connect(self._update_pull_btn)
        # Let startDrag update our status label during the pull phase
        self._list.status_fn = self._set_status
        lay.addWidget(self._list)

        # Drop hint overlay label
        self._drop_hint = QLabel("⬆  Drop files here to push to phone", self._list)
        self._drop_hint.setAlignment(Qt.AlignCenter)
        self._drop_hint.setStyleSheet(
            "color:#555; font-size:12px; background:transparent;"
        )
        self._drop_hint.hide()

        # ── Action bar ───────────────────────────────────────────────────────
        actions = QHBoxLayout()
        actions.setSpacing(6)

        self._btn_pull = QPushButton("⬇  Save to PC")
        self._btn_pull.setEnabled(False)
        self._btn_pull.setToolTip("Pull selected files to ~/Downloads")
        self._btn_pull.clicked.connect(self._pull_selected)
        actions.addWidget(self._btn_pull)

        actions.addStretch()
        lay.addLayout(actions)

        # ── Progress bar ─────────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # indeterminate
        self._progress.setFixedHeight(6)
        self._progress.hide()
        lay.addWidget(self._progress)

        # ── Status ───────────────────────────────────────────────────────────
        self._status = QLabel("Ready")
        self._status.setStyleSheet("font-size:11px;")
        lay.addWidget(self._status)

    # ── Public ───────────────────────────────────────────────────────────────

    def refresh(self):
        self._refresh()

    # ── Sort / view helpers ──────────────────────────────────────────────────

    def _set_sort(self, key: str):
        if self._sort_key == key:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_key = key
            self._sort_asc = True
        for k in ("name", "size", "type"):
            getattr(self, f"_sort_btn_{k}").setChecked(k == self._sort_key)
        self._sort_dir_btn.setText(_SORT_ICON_ASC if self._sort_asc else _SORT_ICON_DESC)
        self._populate(self._entries)

    def _toggle_sort_dir(self):
        self._sort_asc = not self._sort_asc
        self._sort_dir_btn.setText(_SORT_ICON_ASC if self._sort_asc else _SORT_ICON_DESC)
        self._populate(self._entries)

    def _set_view(self, mode: str):
        self._view_mode = mode
        self._btn_list.setChecked(mode == "list")
        self._btn_grid.setChecked(mode == "grid")
        if mode == "list":
            self._list.setViewMode(QListWidget.ListMode)
            self._list.setIconSize(QSize(16, 16))
            self._list.setGridSize(QSize())
            self._list.setSpacing(0)
        else:
            self._list.setViewMode(QListWidget.IconMode)
            self._list.setIconSize(QSize(64, 64))
            self._list.setGridSize(QSize(90, 100))
            self._list.setResizeMode(QListWidget.Adjust)
            self._list.setSpacing(4)
        self._populate(self._entries)

    def _sort_entries(self, entries: list) -> list:
        def key_fn(e: adb_files.FileEntry):
            if self._sort_key == "size":
                return (not e.is_dir, e.size)
            elif self._sort_key == "type":
                ext = e.name.rsplit(".", 1)[-1].lower() if "." in e.name else ""
                return (not e.is_dir, ext, e.name.lower())
            else:  # name
                return (not e.is_dir, e.name.lower())
        return sorted(entries, key=key_fn, reverse=not self._sort_asc)

    # ── Core refresh / populate ──────────────────────────────────────────────

    def _current_path(self) -> str:
        return self._path_stack[-1]

    def _refresh(self):
        path = self._current_path()
        self._path_label.setText(path)
        self._btn_back.setEnabled(len(self._path_stack) > 1)
        self._list.clear()
        self._set_status("Loading…")
        self._progress.show()
        w = _ListDirWorker(path)
        w.signals.done.connect(self._on_dir_listed)
        self._list_worker = w           # prevent GC before signal fires
        self._pool.start(w)

    def _on_dir_listed(self, entries: list):
        self._progress.hide()
        self._entries = entries
        if not self._entries:
            self._set_status("Empty folder or device not connected.")
            return
        self._populate(self._entries)

    def _populate(self, entries: list):
        self._list.clear()
        sorted_entries = self._sort_entries(entries)

        for e in sorted_entries:
            if self._view_mode == "grid":
                label = e.name
                icon_txt = "📁" if e.is_dir else self._file_icon(e.name)
            else:
                icon_txt = ("📁 " if e.is_dir else self._file_icon(e.name) + " ")
                label = e.name
                if not e.is_dir and e.size:
                    label += f"  {self._fmt_size(e.size)}"
                if e.mtime:
                    label += f"   {e.mtime}"
                label = icon_txt + label

            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, e)
            # Files are draggable to Windows Explorer; directories are not
            base_flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            if not e.is_dir:
                item.setFlags(base_flags | Qt.ItemIsDragEnabled)
            else:
                item.setFlags(base_flags)
            if self._view_mode == "grid":
                item.setSizeHint(QSize(90, 100))
            self._list.addItem(item)

        self._set_status(f"{len(entries)} items   ·   drop files here to push to phone")

    # ── Navigation ───────────────────────────────────────────────────────────

    def _on_double_click(self, item: QListWidgetItem):
        entry: adb_files.FileEntry = item.data(Qt.UserRole)
        if entry.is_dir:
            self._path_stack.append(entry.path)
            self._refresh()

    def _go_back(self):
        if len(self._path_stack) > 1:
            self._path_stack.pop()
            self._refresh()

    # ── Pull (phone → PC) ────────────────────────────────────────────────────

    def _update_pull_btn(self):
        items = self._list.selectedItems()
        n = len(items)
        if n == 0:
            self._btn_pull.setEnabled(False)
            self._btn_pull.setText("⬇  Save to PC")
        else:
            self._btn_pull.setEnabled(True)
            self._btn_pull.setText(f"⬇  Save {n} item{'s' if n > 1 else ''} to PC")

    def _pull_selected(self):
        items = self._list.selectedItems()
        if not items:
            return
        downloads = str(Path.home() / "Downloads")
        entries = [i.data(Qt.UserRole) for i in items]
        self._pending = len(entries)
        self._progress.show()
        self._set_status(f"Pulling {self._pending} item(s)…")
        for e in entries:
            w = _PullWorker(e.path, downloads)
            w.signals.done.connect(self._on_pull_done)
            self._pool.start(w)

    def _on_pull_done(self, name: str, ok: bool, msg: str):
        self._pending = max(0, self._pending - 1)
        if self._pending == 0:
            self._progress.hide()
            if ok:
                self._set_status(f"✓ Saved to Downloads", success=True)
            else:
                self._set_status(f"✗ {msg[:80]}", error=True)

    # ── Push (PC → phone via drag-drop) ──────────────────────────────────────

    def _on_files_dropped(self, local_paths: list[str]):
        remote_dir = self._current_path()
        self._pending = len(local_paths)
        self._progress.show()
        self._set_status(f"Pushing {self._pending} file(s) to {remote_dir}…")
        for lp in local_paths:
            w = _PushWorker(lp, remote_dir)
            w.signals.done.connect(self._on_push_done)
            self._pool.start(w)

    def _on_push_done(self, name: str, ok: bool, msg: str):
        self._pending = max(0, self._pending - 1)
        if self._pending == 0:
            self._progress.hide()
            if ok:
                self._set_status(f"✓ Pushed to phone", success=True)
                QTimer.singleShot(1500, self._refresh)
            else:
                self._set_status(f"✗ Push failed: {msg[:60]}", error=True)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _set_status(self, msg: str, success: bool = False, error: bool = False):
        if success:
            color = "#4caf50"
        elif error:
            color = "#ef5350"
        else:
            color = "#555"
        self._status.setStyleSheet(f"font-size:11px; color:{color};")
        self._status.setText(msg)
        if success or error:
            QTimer.singleShot(4000, lambda: self._set_status(
                f"{len(self._entries)} items   ·   drop files here to push to phone"
            ))

    @staticmethod
    def _file_icon(name: str) -> str:
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        return {
            "jpg": "🖼", "jpeg": "🖼", "png": "🖼", "gif": "🖼", "webp": "🖼", "heic": "🖼",
            "mp4": "🎬", "mkv": "🎬", "avi": "🎬", "mov": "🎬", "3gp": "🎬",
            "mp3": "🎵", "flac": "🎵", "wav": "🎵", "ogg": "🎵", "m4a": "🎵",
            "pdf": "📕", "doc": "📝", "docx": "📝", "xls": "📊", "xlsx": "📊",
            "zip": "🗜", "tar": "🗜", "gz": "🗜", "rar": "🗜",
            "apk": "📦",
        }.get(ext, "📄")

    @staticmethod
    def _fmt_size(b: int) -> str:
        if b < 1024:
            return f"{b} B"
        if b < 1024 ** 2:
            return f"{b/1024:.1f} KB"
        if b < 1024 ** 3:
            return f"{b/1024**2:.1f} MB"
        return f"{b/1024**3:.2f} GB"


# ─────────────────────────────────────────────────────────────────────────────
# Photo Grid Tab
# ─────────────────────────────────────────────────────────────────────────────

class PhotoGridTab(QWidget):
    THUMB_SIZE = 110

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache_dir   = tempfile.mkdtemp(prefix="sprightly_thumbs_")
        self._pool        = QThreadPool.globalInstance()
        self._path_map:   dict[str, QListWidgetItem] = {}
        self._pending     = 0
        self._scan_worker: _ScanPhotosWorker | None = None  # keep ref until signal fires
        self._setup_ui()

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        top = QHBoxLayout()

        btn_load = QPushButton("🔄  Load Photos")
        btn_load.clicked.connect(self._load_photos)
        top.addWidget(btn_load)

        self._btn_pull = QPushButton("⬇  Save Selected")
        self._btn_pull.setEnabled(False)
        self._btn_pull.clicked.connect(self._pull_selected)
        top.addWidget(self._btn_pull)
        lay.addLayout(top)

        self._grid = QListWidget()
        self._grid.setViewMode(QListWidget.IconMode)
        self._grid.setIconSize(QSize(self.THUMB_SIZE, self.THUMB_SIZE))
        self._grid.setGridSize(QSize(self.THUMB_SIZE + 24, self.THUMB_SIZE + 32))
        self._grid.setResizeMode(QListWidget.Adjust)
        self._grid.setSpacing(4)
        self._grid.setMovement(QListWidget.Static)
        self._grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._grid.setStyleSheet("font-size:9px;")
        self._grid.itemSelectionChanged.connect(self._update_pull_btn)
        lay.addWidget(self._grid)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(6)
        self._progress.hide()
        lay.addWidget(self._progress)

        self._status = QLabel("Click 'Load Photos' to scan the device.")
        self._status.setStyleSheet("font-size:11px;")
        lay.addWidget(self._status)

    def _update_pull_btn(self):
        n = len(self._grid.selectedItems())
        self._btn_pull.setEnabled(n > 0)
        if n > 0:
            self._btn_pull.setText(f"⬇  Save {n} photo{'s' if n > 1 else ''}")
        else:
            self._btn_pull.setText("⬇  Save Selected")

    def _load_photos(self):
        self._grid.clear()
        self._path_map.clear()
        self._progress.show()
        self._status.setText("Scanning device for photos…")
        w = _ScanPhotosWorker(200)
        w.signals.done.connect(self._on_photos_listed)
        self._scan_worker = w           # prevent GC before signal fires
        self._pool.start(w)

    def _on_photos_listed(self, photos: list):
        self._progress.hide()
        if not photos:
            self._status.setText("No photos found or device not connected.")
            return
        self._status.setText(f"Found {len(photos)} photos — loading thumbnails…")
        for remote in photos:
            name = Path(remote).name
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, remote)
            item.setSizeHint(QSize(self.THUMB_SIZE + 16, self.THUMB_SIZE + 28))
            self._grid.addItem(item)
            self._path_map[remote] = item
            worker = _ThumbWorker(remote, self._cache_dir)
            worker.signals.thumb.connect(self._on_thumb_loaded)
            self._pool.start(worker)

    def _on_thumb_loaded(self, remote: str, local: str):
        item = self._path_map.get(remote)
        if not item:
            return
        pix = QPixmap(local)
        if not pix.isNull():
            pix = pix.scaled(self.THUMB_SIZE, self.THUMB_SIZE,
                             Qt.KeepAspectRatio, Qt.SmoothTransformation)
            item.setIcon(QIcon(pix))

    def _pull_selected(self):
        items = self._grid.selectedItems()
        if not items:
            return
        downloads = str(Path.home() / "Downloads")
        self._pending = len(items)
        self._progress.show()
        self._status.setText(f"Saving {self._pending} photo(s)…")
        for item in items:
            remote = item.data(Qt.UserRole)
            w = _PullWorker(remote, downloads)
            w.signals.done.connect(self._on_pull_done)
            self._pool.start(w)

    def _on_pull_done(self, name: str, ok: bool, msg: str):
        self._pending = max(0, self._pending - 1)
        if self._pending == 0:
            self._progress.hide()
            if ok:
                self._status.setStyleSheet("font-size:11px; color:#4caf50;")
                self._status.setText("✓ Saved to Downloads")
            else:
                self._status.setStyleSheet("font-size:11px; color:#ef5350;")
                self._status.setText(f"✗ {msg[:60]}")
            QTimer.singleShot(4000, lambda: self._status.setStyleSheet("font-size:11px;"))


# ─────────────────────────────────────────────────────────────────────────────
# Combined side panel
# ─────────────────────────────────────────────────────────────────────────────

class FilePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._tabs = QTabWidget()
        self._files_tab  = FileBrowserTab()
        self._photos_tab = PhotoGridTab()
        self._tabs.addTab(self._files_tab,  "  Files  ")
        self._tabs.addTab(self._photos_tab, "  Photos  ")
        lay.addWidget(self._tabs)

    def refresh_files(self):
        self._files_tab.refresh()
