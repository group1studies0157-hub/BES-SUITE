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
        _warn_missing_anthropic(window)

    intro = IntroScreen()
    state["intro"] = intro
    intro.finished.connect(show_main_window)
    intro.start()

    return app.exec()


def _warn_missing_anthropic(window) -> None:
    """Startup guard: a stored Claude key with no 'anthropic' package means
    the dual-key fallback silently has no Claude to fall back to. Warn once,
    only when that combination is actually present."""
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QMessageBox

    settings = QSettings("BES", "BridgeEngineeringSuite")
    key = (settings.value("anthropic_api_key", "")
           or settings.value("api_key", "") or "").strip()
    if not key:
        return
    try:
        import anthropic  # noqa: F401
        return
    except ImportError:
        pass
    QMessageBox.warning(
        window,
        "Claude fallback unavailable",
        "An Anthropic (Claude) API key is configured, but the 'anthropic' "
        "package is not installed in this Python environment.\n\n"
        "AI features will run on Gemini only — there is no fallback if "
        "Gemini fails or truncates.\n\n"
        "To fix, run:   pip install anthropic",
    )


if __name__ == "__main__":
    raise SystemExit(main())
