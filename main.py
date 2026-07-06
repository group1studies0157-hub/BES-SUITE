"""
Bridge Engineering Suite  —  main.py
Entry point: initialises QApplication, primes the saved theme (Fusion + QPalette + QSS),
then opens MainWindow.
"""

import sys
print(sys.executable)
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui     import QFont


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Bridge Engineering Suite")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("BES")

    # Global font baseline
    app.setFont(QFont("Segoe UI", 10))

    # ── Apply saved theme BEFORE creating any widgets ────────────────────
    # This sets Fusion style + full QPalette + QSS in one call so every
    # widget — including those created inside MainWindow.__init__ — inherits
    # the correct dark/light colours from birth, not after a repaint.
    from gui.styles import apply_theme, _saved_theme
    apply_theme(_saved_theme(), app)

    from gui.main_window import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
