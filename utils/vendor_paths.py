import hashlib
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def scrcpy_dir() -> Path:
    return _project_root() / "vendor" / "scrcpy"


def scrcpy_exe() -> Path:
    return scrcpy_dir() / "scrcpy.exe"


def adb_exe() -> Path:
    return scrcpy_dir() / "adb.exe"


def _verify_checksums() -> list[str]:
    """Return a list of tampered/missing file names based on checksums.txt."""
    checksum_file = scrcpy_dir() / "checksums.txt"
    if not checksum_file.exists():
        return []
    failures: list[str] = []
    for line in checksum_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        expected_hash, filename = line.split(None, 1)
        path = scrcpy_dir() / filename
        if not path.exists():
            failures.append(f"{filename} (missing)")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        if actual != expected_hash.upper():
            failures.append(f"{filename} (checksum mismatch)")
    return failures


def validate() -> None:
    missing = []
    for p in (scrcpy_exe(), adb_exe(), scrcpy_dir() / "scrcpy-server"):
        if not p.exists():
            missing.append(str(p))
    if missing:
        raise FileNotFoundError(
            "scrcpy vendor files not found. Download scrcpy v3.3.x Windows release "
            "and extract it to vendor/scrcpy/.\n"
            "Missing:\n" + "\n".join(f"  {m}" for m in missing)
        )
    tampered = _verify_checksums()
    if tampered:
        raise RuntimeError(
            "Vendor binary integrity check failed. The following files may have been "
            "tampered with:\n" + "\n".join(f"  {t}" for t in tampered)
        )
