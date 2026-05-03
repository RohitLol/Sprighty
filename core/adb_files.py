"""ADB file system helpers: listing, pulling, pushing, photo discovery."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core import adb_bridge


def _run_shell(*args: str, timeout: int = 15) -> tuple[int, str, str]:
    return adb_bridge._run_on_device(*args, timeout=timeout)


@dataclass
class FileEntry:
    name: str
    path: str
    is_dir: bool
    size: int = 0
    mtime: str = ""    # raw mtime string from ls -la


def list_dir(remote_path: str) -> list[FileEntry]:
    """List files in a remote directory via adb shell ls -la.

    Correctly handles symlink lines of the form:
        lrwxrwxrwx … name -> /target/path
    by extracting the link *name* (not the target) as the entry name.
    """
    rc, stdout, _ = _run_shell("shell", "ls", "-la", remote_path)
    if rc != 0:
        return []

    entries: list[FileEntry] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("total") or line.startswith("//"):
            continue
        parts = line.split()
        if len(parts) < 7:
            continue

        perms = parts[0]
        is_symlink = perms.startswith("l")
        is_dir = perms.startswith("d") or is_symlink

        try:
            size = int(parts[4]) if not is_dir else 0
        except (IndexError, ValueError):
            size = 0

        mtime = f"{parts[5]} {parts[6]}" if len(parts) > 6 else ""

        # Symlink lines: "lrwxrwxrwx … name -> /target"
        # Regular lines: "drwxr-xr-x … name"
        if is_symlink and "->" in parts:
            arrow_idx = parts.index("->")
            name = parts[arrow_idx - 1]
        else:
            name = parts[-1]

        if name in (".", ".."):
            continue

        full_path = remote_path.rstrip("/") + "/" + name
        entries.append(FileEntry(name=name, path=full_path, is_dir=is_dir,
                                 size=size, mtime=mtime))

    return entries


def pull_file(remote_path: str, local_dir: str) -> tuple[bool, str]:
    """Pull a single file (or directory) from device to local_dir."""
    rc, stdout, stderr = _run_shell("pull", remote_path, local_dir, timeout=120)
    ok = rc == 0
    msg = stdout.strip() or stderr.strip()
    return ok, msg


def push_file(local_path: str, remote_dir: str) -> tuple[bool, str]:
    """Push a local file to remote_dir on the device."""
    rc, stdout, stderr = _run_shell("push", local_path, remote_dir, timeout=120)
    ok = rc == 0
    msg = stdout.strip() or stderr.strip()
    return ok, msg


# ── Photo discovery ───────────────────────────────────────────────────────────

# Directories to search for photos/images (ordered by priority)
_PHOTO_SEARCH_DIRS = [
    "/sdcard/DCIM/Camera",
    "/sdcard/DCIM",
    "/sdcard/Pictures",
    "/sdcard/Pictures/Screenshots",
    "/sdcard/Movies",
    "/sdcard/Download",
    "/sdcard/WhatsApp/Media/WhatsApp Images",
    "/sdcard/WhatsApp/Media/WhatsApp Video",
    "/sdcard/Telegram",
    "/sdcard/Instagram",
    "/sdcard/Snapchat",
]

# Extensions to look for (covers modern Android formats)
_IMG_EXTENSIONS = [
    "*.jpg", "*.jpeg", "*.png", "*.webp",
    "*.heic", "*.heif", "*.gif", "*.bmp",
]


def list_photos(max_count: int = 200) -> list[str]:
    """Return a list of remote photo/image paths from common directories.

    Searches across DCIM, Pictures, Screenshots, WhatsApp, Downloads and more.
    Supports: .jpg .jpeg .png .webp .heic .heif .gif .bmp
    """
    photos: list[str] = []

    # Build find arguments for all extensions combined
    ext_args: list[str] = []
    for i, ext in enumerate(_IMG_EXTENSIONS):
        if i > 0:
            ext_args.append("-o")
        ext_args += ["-iname", ext]

    for d in _PHOTO_SEARCH_DIRS:
        if len(photos) >= max_count:
            break
        rc, stdout, _ = _run_shell(
            "shell", "find", d,
            "-maxdepth", "4",
            "-type", "f",
            "(", *ext_args, ")",
            timeout=15,
        )
        if rc == 0:
            for line in stdout.splitlines():
                p = line.strip()
                if p and p not in photos:
                    photos.append(p)

    return photos[:max_count]


def pull_thumbnail(remote_path: str, cache_dir: str) -> Optional[str]:
    """Pull a photo and return local path, or None on failure (cached)."""
    name = Path(remote_path).name
    local = Path(cache_dir) / name
    if local.exists():
        return str(local)
    ok, _ = pull_file(remote_path, cache_dir)
    return str(local) if ok and local.exists() else None
