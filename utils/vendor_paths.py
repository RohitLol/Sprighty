from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def scrcpy_dir() -> Path:
    return _project_root() / "vendor" / "scrcpy"


def scrcpy_exe() -> Path:
    return scrcpy_dir() / "scrcpy.exe"


def adb_exe() -> Path:
    return scrcpy_dir() / "adb.exe"


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
