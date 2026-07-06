"""
Main application window - sidebar layout with CD Processing, CAD Process and Knowledge Base panels
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QIcon, QColor

from gui.styles import STYLESHEET, COLORS
from gui.cd_panel import CDPanel
from gui.cad_panel import CADPanel
from gui.knowledge_panel import KnowledgePanel


class SidebarButton(QPushButton):
    def __init__(self, text, icon_text="", parent=None):
        super().__init__(parent)
        self.setText(f"  {icon_text}  {text}")
        self.setCheckable(True)
        self.setMinimumHeight(48)
        self.setFont(QFont("Segoe UI", 10))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("sidebarButton")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bridge Engineering Suite  v2.0")
        self.setMinimumSize(1000, 680)
        self.resize(1200, 800)
        self.setStyleSheet(STYLESHEET)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(12, 20, 12, 20)
        sb_layout.setSpacing(4)

        logo_label = QLabel("⬡  BES")
        logo_label.setObjectName("logoLabel")
        logo_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        sb_layout.addWidget(logo_label)

        sub_label = QLabel("Bridge Engineering Suite")
        sub_label.setObjectName("subLabel")
        sub_label.setFont(QFont("Segoe UI", 8))
        sb_layout.addWidget(sub_label)

        sb_layout.addSpacing(24)

        nav_label = QLabel("PROCESSES")
        nav_label.setObjectName("navLabel")
        nav_label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        sb_layout.addWidget(nav_label)
        sb_layout.addSpacing(4)

        self.btn_cd  = SidebarButton("CD Processing",  "⚙")
        self.btn_cad = SidebarButton("CAD Process",    "✏")
        self.btn_cd.setChecked(True)

        self.btn_cd.clicked.connect(lambda:  self._switch(0))
        self.btn_cad.clicked.connect(lambda: self._switch(1))

        sb_layout.addWidget(self.btn_cd)
        sb_layout.addWidget(self.btn_cad)

        # ── Knowledge Base button (3rd tab) ───────────────────────
        sb_layout.addSpacing(16)
        kb_label = QLabel("STUDY TOOLS")
        kb_label.setObjectName("navLabel")
        kb_label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        sb_layout.addWidget(kb_label)
        sb_layout.addSpacing(4)

        self.btn_kb = SidebarButton("Knowledge Base", "📚")
        self.btn_kb.clicked.connect(lambda: self._switch(2))
        sb_layout.addWidget(self.btn_kb)

        sb_layout.addStretch()

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setObjectName("divider")
        sb_layout.addWidget(divider)
        sb_layout.addSpacing(8)

        version_label = QLabel("v2.0  •  Local Build")
        version_label.setObjectName("versionLabel")
        version_label.setFont(QFont("Segoe UI", 8))
        sb_layout.addWidget(version_label)

        # ── Content area ─────────────────────────────────────────
        self.stack = QStackedWidget()
        self.stack.setObjectName("contentArea")

        self.cd_panel        = CDPanel()
        self.cad_panel       = CADPanel()
        self.knowledge_panel = KnowledgePanel()

        self.stack.addWidget(self.cd_panel)
        self.stack.addWidget(self.cad_panel)
        self.stack.addWidget(self.knowledge_panel)

        root.addWidget(sidebar)

        # thin separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setObjectName("separator")
        root.addWidget(sep)

        root.addWidget(self.stack)

    def _switch(self, index):
        self.stack.setCurrentIndex(index)
        self.btn_cd.setChecked(index  == 0)
        self.btn_cad.setChecked(index == 1)
        self.btn_kb.setChecked(index  == 2)
