import sys

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.style import DARK_THEME


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Sprightly")
    app.setOrganizationName("Sprightly")
    app.setQuitOnLastWindowClosed(False)  # keep alive in tray
    app.setStyleSheet(DARK_THEME)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
