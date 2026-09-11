"""Render the redesigned pages to PNG for review. Skips the page-fade animation
(it crashes offscreen grabs on this box) by patching _animate_page to a no-op."""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

app = QApplication(sys.argv)

from gui.ui_text import install_text_sanitizer
install_text_sanitizer()

from gui.styles import apply_theme
apply_theme("graphite", app)

import gui.main_window as mw

mw.MainWindow._animate_page = lambda self, page: None  # avoid fade crash in headless grab

win = mw.MainWindow()
win.resize(1440, 900)
win.show()
win._set_sidebar_width(176, animate=False)
for b in win.findChildren(mw.SidebarButton):
    b.setCollapsed(False)

PAGES = [
    (0, "redesign_home"),
    (10, "redesign_settings"),
    (6, "redesign_hydraulic"),
]


def capture():
    for idx, name in PAGES:
        win._switch(idx)
        app.processEvents()
        app.processEvents()
        px = win.grab()
        px.save(os.path.join(ROOT, "_mockups", f"{name}.png"))
        print("saved", name, flush=True)
    app.quit()


QTimer.singleShot(700, capture)
app.exec()
print("DONE")
