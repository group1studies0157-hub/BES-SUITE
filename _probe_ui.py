"""Verify hydraulic top-bar layout + dark graphite rendering. Offscreen."""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QComboBox
from PyQt6.QtCore import QTimer

app = QApplication(sys.argv)

from gui.ui_text import install_text_sanitizer
install_text_sanitizer()

from gui.styles import apply_theme, current_theme, COLORS

import gui.main_window as mw
mw.MainWindow._animate_page = lambda self, page: None


def probe(theme_name: str):
    apply_theme(theme_name, app)
    print(f"\n===== THEME: {theme_name} (active={current_theme()}) =====")
    print("bg_primary:", COLORS["bg_primary"], "| text_primary:", COLORS["text_primary"],
          "| input_bg:", COLORS["input_bg"], "| sidebar_bg:", COLORS["sidebar_bg"])

    win = mw.MainWindow()
    win.resize(1440, 900)
    win.show()
    win._switch(6)
    app.processEvents()

    # Sidebar round-trip: pin must stay visible in BOTH states; names must
    # come back after expand. Normalize to expanded first, then collapse.
    if not win._sidebar_pinned:
        win._toggle_pin()
    for _ in range(6):
        app.processEvents()
    names_ok = all(b.isVisible() and b.text() for b in
                   (win.btn_cd, win.btn_gad, win.btn_hydro, win.btn_kb))
    print(f"sidebar expanded: pinned={win._sidebar_pinned} width={win.sidebar.width()} "
          f"pin visible={win.btn_pin.isVisible()} names={names_ok}")
    win._toggle_pin()          # -> collapsed
    for _ in range(6):
        app.processEvents()
    pin_ok = win.btn_pin.isVisible()
    print(f"sidebar collapsed: pinned={win._sidebar_pinned} width={win.sidebar.width()} "
          f"pin visible={pin_ok} text={win.btn_pin.text()!r}")
    win._toggle_pin()          # -> back to expanded for screenshots
    for _ in range(6):
        app.processEvents()
    names_again = all(b.isVisible() and b.text() for b in
                      (win.btn_cd, win.btn_gad, win.btn_hydro, win.btn_kb))
    print(f"sidebar re-expanded: names restored={names_again}")

    tb = win.top_bar_extra_container
    print(f"topbar h={win.top_bar.height()}  extra container={tb.width()}x{tb.height()}")
    extra = win.hydraulic_panel.top_bar_extra_widget()
    lay = extra.layout()
    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if w is not None:
            print(f"  extra[{i}] {type(w).__name__}: {w.width()}x{w.height()} "
                  f"(hint {w.sizeHint().width()}x{w.sizeHint().height()})")
    for combo in win.hydraulic_panel.findChildren(QComboBox):
        if combo.width() == 220:
            print(f"  mode combo: {combo.width()}x{combo.height()} "
                  f"(hint {combo.sizeHint().height()})")

    px = win.grab()
    px.save(os.path.join(ROOT, "_mockups", f"_verify_{theme_name}_hydraulic.png"))
    win._switch(0); app.processEvents()
    win.grab().save(os.path.join(ROOT, "_mockups", f"_verify_{theme_name}_home.png"))
    win._switch(10); app.processEvents()
    win.grab().save(os.path.join(ROOT, "_mockups", f"_verify_{theme_name}_settings.png"))
    print("screenshots saved for", theme_name)
    win.close()
    win.deleteLater()
    app.processEvents()


def run():
    probe("graphite")
    probe("studio")
    # Round-trip: live theme switch must re-ink panels proportionally.
    apply_theme("graphite", app)
    win = mw.MainWindow()
    win.resize(1440, 900)
    win.show()
    win._switch(6)
    app.processEvents()
    old_panel = win.hydraulic_panel
    win.settings_panel._set_theme("studio")
    for _ in range(8):
        app.processEvents()
    rebuilt = win.hydraulic_panel is not old_panel
    theme_now = current_theme()
    print(f"\n== live switch graphite->studio: panel rebuilt={rebuilt}, active={theme_now}")
    px = win.grab()
    px.save(os.path.join(ROOT, "_mockups", "_verify_after_switch_hydraulic.png"))
    win._switch(0); app.processEvents()
    win.grab().save(os.path.join(ROOT, "_mockups", "_verify_after_switch_home.png"))
    # Small-window scaling check: hydraulic form must stay usable (scrollable) at 1200x720
    win._switch(6)
    win.resize(1200, 720)
    for _ in range(8):
        app.processEvents()
    win.grab().save(os.path.join(ROOT, "_mockups", "_verify_small_window_hydraulic.png"))
    print("small-window hydraulic screenshot saved")
    win.settings_panel._set_theme("graphite")
    for _ in range(8):
        app.processEvents()
    print(f"== switch back: active={current_theme()}, rebuilt again={win.hydraulic_panel is not old_panel}")
    win.close()
    win.deleteLater()
    app.quit()


QTimer.singleShot(400, run)
app.exec()
print("\nVERIFY DONE")
