"""Bridge Engineering Suite entry point."""

from __future__ import annotations

import os
import sys

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication


ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Bridge Engineering Suite")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("BES")
    app.setFont(QFont("Segoe UI", 10))

    from gui.ui_text import install_text_sanitizer

    install_text_sanitizer()

    from gui.intro_screen import IntroScreen
    from gui.main_window import MainWindow
    from gui.styles import _saved_theme, apply_theme

    apply_theme(_saved_theme(), app)

    state = {"window": None, "intro": None}

    def show_main_window():
        window = MainWindow()
        state["window"] = window
        window.show()

    intro = IntroScreen()
    state["intro"] = intro
    intro.finished.connect(show_main_window)
    intro.start()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
