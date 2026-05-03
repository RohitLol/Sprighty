"""Minimal SVG icon loader for Sprightly.

Icons live in  resources/icons/<name>.svg  relative to the project root.
Call  icon("name")  to get a QIcon ready for QAction / QToolButton.
"""

from pathlib import Path

from PySide6.QtGui import QIcon

_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"


def icon(name: str) -> QIcon:
    """Return a QIcon for the SVG file at resources/icons/<name>.svg.

    Falls back to an empty QIcon if the file does not exist so the app
    never crashes because of a missing icon.
    """
    path = _ICON_DIR / f"{name}.svg"
    if path.exists():
        return QIcon(str(path))
    return QIcon()
