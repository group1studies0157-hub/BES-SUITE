import sys, time, faulthandler
sys.path.insert(0, '.')
faulthandler.enable()

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from gui.styles import apply_theme

app = QApplication(sys.argv)
apply_theme('graphite', app)
print('S1 theme', flush=True)

import gui.main_window as mw
mw.MainWindow._animate_page = lambda self, page: None

from gui.main_window import MainWindow, SidebarButton
print('S2 imports', flush=True)

win = MainWindow()
win.resize(1440, 900)
print('S3 built', flush=True)

win._set_sidebar_width(176, animate=False)
for b in win.findChildren(SidebarButton):
    b.setCollapsed(False)
print('S4 sidebar expanded', flush=True)

win.show()
print('S5 shown', flush=True)


def capture():
    print('S6 capture fired', flush=True)
    px = win.grab()
    print('S7 grabbed', px.width(), px.height(), flush=True)
    px.save('_mockups/redesign_home.png')
    print('S8 saved', flush=True)
    app.quit()


QTimer.singleShot(800, capture)
print('S5b timer armed', flush=True)
app.exec()
print('DONE', flush=True)
