"""Cinematic startup screen for Bridge Engineering Suite."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QAbstractAnimation, QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.styles import COLORS


class IntroScreen(QWidget):
    """A native-widget intro that avoids custom painting and keeps launch stable."""

    finished = pyqtSignal()

    _WORDS = ("IMPOSSIBLE", "PRECISION", "STRUCTURE", "FLOW")
    _STATUSES = (
        "loading design intelligence...",
        "syncing CAD and drawing workflows...",
        "warming hydraulic calculation modules...",
        "indexing bridge knowledge systems...",
        "preparing workspace...",
    )
    _MODULES = ("CAD Vision", "GAD Check", "Hydraulics", "Knowledge")

    def __init__(self, duration_ms: int = 2800, parent=None):
        super().__init__(parent)
        self._duration_ms = max(900, duration_ms)
        self._tick_ms = 34
        self._elapsed_ms = 0
        self._word_index = 0
        self._finished = False
        self._module_cards: list[QFrame] = []
        self._module_labels: list[QLabel] = []

        self.setObjectName("introWindow")
        self.setWindowTitle("Bridge Engineering Suite")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFixedSize(980, 580)
        self.setStyleSheet(self._stylesheet())

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(self._tick_ms)
        self._timer.timeout.connect(self._tick)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        stage = QFrame()
        stage.setObjectName("introStage")
        outer.addWidget(stage)

        layout = QVBoxLayout(stage)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(18)

        layout.addLayout(self._top_bar())
        layout.addLayout(self._hero_row(), 1)
        layout.addLayout(self._bottom_bar())

    def _top_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        brand = QLabel("BES / BRIDGE ENGINEERING SUITE")
        brand.setObjectName("introBrand")
        row.addWidget(brand)

        for text in ("CAD", "GAD", "HYD", "AI"):
            chip = QLabel(text)
            chip.setObjectName("introChip")
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(chip)

        row.addStretch(1)

        self.clock_label = QLabel()
        self.clock_label.setObjectName("introClock")
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.clock_label)

        skip = QPushButton("Skip")
        skip.setObjectName("introSkip")
        skip.setCursor(Qt.CursorShape.PointingHandCursor)
        skip.setFixedSize(66, 32)
        skip.clicked.connect(self._finish)
        row.addWidget(skip)

        self._sync_clock()
        return row

    def _hero_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(28)

        left = QVBoxLayout()
        left.setSpacing(14)

        kicker = QLabel("EXPERIENCE THE")
        kicker.setObjectName("introKicker")
        left.addWidget(kicker)

        self.hero_word = QLabel(self._WORDS[0])
        self.hero_word.setObjectName("introHero")
        self.hero_word.setWordWrap(True)
        self.hero_word.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        left.addWidget(self.hero_word)

        subtitle = QLabel(
            "A sharper, more immersive launch for bridge drawings, checks, hydraulics, and knowledge work."
        )
        subtitle.setObjectName("introSubtitle")
        subtitle.setWordWrap(True)
        left.addWidget(subtitle)

        left.addSpacing(10)
        left.addWidget(self._loading_card())
        left.addStretch(1)

        row.addLayout(left, 3)
        row.addWidget(self._control_room(), 2)
        return row

    def _loading_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("introLoadingCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        label = QLabel("BOOT SEQUENCE / LOCAL BUILD")
        label.setObjectName("introTiny")
        layout.addWidget(label)

        self.status_label = QLabel(self._STATUSES[0])
        self.status_label.setObjectName("introStatus")
        layout.addWidget(self.status_label)

        meter_row = QHBoxLayout()
        meter_row.setSpacing(12)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(10)
        meter_row.addWidget(self.progress, 1)

        self.percent_label = QLabel("00%")
        self.percent_label.setObjectName("introPercent")
        self.percent_label.setFixedWidth(46)
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        meter_row.addWidget(self.percent_label)
        layout.addLayout(meter_row)

        return card

    def _control_room(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("introControlRoom")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("DIGITAL CONTROL ROOM")
        title.setObjectName("introTiny")
        layout.addWidget(title)

        for i, module in enumerate(self._MODULES):
            card = QFrame()
            card.setObjectName("introMetricActive" if i == 0 else "introMetric")
            card_lay = QHBoxLayout(card)
            card_lay.setContentsMargins(13, 10, 13, 10)
            card_lay.setSpacing(10)

            name = QLabel(module)
            name.setObjectName("introMetricName")
            card_lay.addWidget(name, 1)

            state = QLabel("LIVE" if i == 0 else "READY")
            state.setObjectName("introMetricState")
            state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            card_lay.addWidget(state)

            layout.addWidget(card)
            self._module_cards.append(card)
            self._module_labels.append(state)

        signal = QFrame()
        signal.setObjectName("introSignal")
        signal_lay = QVBoxLayout(signal)
        signal_lay.setContentsMargins(13, 12, 13, 12)
        signal_lay.setSpacing(7)

        self.signal_title = QLabel("STRUCTURAL SIGNAL")
        self.signal_title.setObjectName("introTiny")
        signal_lay.addWidget(self.signal_title)

        for text in ("load path analysis", "span geometry scan", "document context map"):
            bar = QLabel(text.upper())
            bar.setObjectName("introSignalLine")
            signal_lay.addWidget(bar)

        layout.addWidget(signal)
        layout.addStretch(1)
        return panel

    def _bottom_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        line = QLabel("CAD -> GAD -> HYDRAULICS -> KNOWLEDGE")
        line.setObjectName("introFooter")
        row.addWidget(line)

        row.addStretch(1)

        build = QLabel("v2.0 / LOCAL ENGINEERING WORKSPACE")
        build.setObjectName("introFooter")
        row.addWidget(build)
        return row

    def start(self) -> None:
        self._center_on_screen()
        self._fade_in()
        self.show()
        self.raise_()
        self.activateWindow()
        self._timer.start()

    def _center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.move(
            available.x() + (available.width() - self.width()) // 2,
            available.y() + (available.height() - self.height()) // 2,
        )

    def _fade_in(self) -> None:
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)

        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(260)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim = anim
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _tick(self) -> None:
        self._elapsed_ms += self._tick_ms
        ratio = min(1.0, self._elapsed_ms / self._duration_ms)
        eased = 1.0 - pow(1.0 - ratio, 2.2)
        progress = int(eased * 100)
        self.progress.setValue(progress)
        self.percent_label.setText(f"{progress:02d}%")

        phase = int(self._elapsed_ms / 520)
        if phase != self._word_index:
            self._word_index = phase
            self._sync_motion()

        self._sync_clock()
        if ratio >= 1.0:
            self._finish()

    def _sync_motion(self) -> None:
        word = self._WORDS[self._word_index % len(self._WORDS)]
        self.hero_word.setText(word)
        self.status_label.setText(self._STATUSES[self._word_index % len(self._STATUSES)])

        active = self._word_index % len(self._module_cards)
        for i, card in enumerate(self._module_cards):
            card.setObjectName("introMetricActive" if i == active else "introMetric")
            self._module_labels[i].setText("LIVE" if i == active else "READY")
            card.style().unpolish(card)
            card.style().polish(card)

    def _sync_clock(self) -> None:
        now = datetime.now()
        self.clock_label.setText(now.strftime("%d %b %Y  %H:%M:%S").upper())

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._timer.stop()
        self.finished.emit()
        self.close()

    def keyPressEvent(self, event) -> None:
        self._finish()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        self._finish()
        event.accept()

    def _stylesheet(self) -> str:
        # Neutrals (dark stage background, borders, footer text) stay intro-native
        # so the cinematic panel still reads correctly even when the active app
        # theme is a light one (e.g. Studio). Only accent hues are swapped in via
        # token replacement below, so the boot screen's highlight colors always
        # match whichever theme the user has selected in Settings.
        css = """
QWidget#introWindow {
    background-color: #05050A;
}

QFrame#introStage {
    background-color: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                      stop:0 #07070C,
                                      stop:0.42 #161124,
                                      stop:0.70 #0B2330,
                                      stop:1 #05050A);
    border: 1px solid #2A2740;
}

QLabel {
    background-color: transparent;
    color: #F8FAFC;
    font-family: 'Segoe UI', Arial, sans-serif;
}

QLabel#introBrand {
    color: #FFFFFF;
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 0px;
}

QLabel#introChip {
    min-width: 44px;
    min-height: 26px;
    color: #BDE7FF;
    background-color: rgba(255,255,255,0.07);
    border: 1px solid rgba(255,255,255,0.13);
    border-radius: 7px;
    font-size: 10px;
    font-weight: 900;
}

QLabel#introClock {
    color: __ACCENT_3__;
    font-size: 11px;
    font-weight: 800;
}

QPushButton#introSkip {
    color: #FFFFFF;
    background-color: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 7px;
    font-size: 12px;
    font-weight: 800;
}

QPushButton#introSkip:hover {
    background-color: __ACCENT__;
    color: __ACCENT_TEXT__;
    border-color: __ACCENT__;
}

QLabel#introKicker {
    color: __ACCENT__;
    font-size: 13px;
    font-weight: 900;
}

QLabel#introHero {
    color: #FFFFFF;
    font-size: 68px;
    font-weight: 900;
}

QLabel#introSubtitle {
    color: #D9E5F5;
    font-size: 18px;
    line-height: 130%;
}

QFrame#introLoadingCard,
QFrame#introControlRoom,
QFrame#introSignal {
    background-color: rgba(6, 10, 22, 0.72);
    border: 1px solid rgba(255,255,255,0.14);
    border-radius: 8px;
}

QLabel#introTiny {
    color: #94A3B8;
    font-size: 10px;
    font-weight: 900;
}

QLabel#introStatus {
    color: #FFFFFF;
    font-size: 14px;
    font-weight: 800;
}

QLabel#introPercent {
    color: #A7F3D0;
    font-size: 12px;
    font-weight: 900;
}

QProgressBar {
    background-color: rgba(255,255,255,0.10);
    border: none;
    border-radius: 5px;
}

QProgressBar::chunk {
    background-color: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                      stop:0 __ACCENT__,
                                      stop:0.55 __ACCENT_2__,
                                      stop:1 __ACCENT_3__);
    border-radius: 5px;
}

QFrame#introMetric,
QFrame#introMetricActive {
    background-color: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px;
}

QFrame#introMetricActive {
    background-color: __ACCENT_GLOW__;
    border-color: __ACCENT__;
}

QLabel#introMetricName {
    color: #F8FAFC;
    font-size: 13px;
    font-weight: 850;
}

QLabel#introMetricState {
    color: #A7F3D0;
    font-size: 10px;
    font-weight: 900;
}

QLabel#introSignalLine {
    color: #D9E5F5;
    background-color: rgba(255,255,255,0.06);
    border-left: 3px solid __ACCENT_2__;
    border-radius: 6px;
    padding: 7px 10px;
    font-size: 10px;
    font-weight: 800;
}

QLabel#introFooter {
    color: #9FB3C8;
    font-size: 11px;
    font-weight: 850;
}
"""
        replacements = {
            "__ACCENT__": COLORS.get("accent", "#22D3EE"),
            "__ACCENT_2__": COLORS.get("accent_2", "#A78BFA"),
            "__ACCENT_3__": COLORS.get("accent_3", "#38BDF8"),
            "__ACCENT_GLOW__": COLORS.get("accent_glow", "rgba(34,211,238,0.16)"),
            "__ACCENT_TEXT__": COLORS.get("accent_text", "#061018"),
        }
        for token, value in replacements.items():
            css = css.replace(token, value)
        return css
