"""
Bridge Engineering Suite — Calculated Notes
════════════════════════════════════════════════════════════════════
Main-interface feature pairing a scientific calculator with a live
notes display (portrait layout: calculator left, notes right).

Every result produced by the "=" key is appended, in sequence, to the
notes display. Two actions close the loop:

  • Save  — exports the recorded calculations to a formatted .xlsx
            workbook (No / Date / Time / Expression / Result) via a
            save dialog, so the sheet is immediately available for
            download / sharing.
  • Clear — wipes the notes after a confirmation.

Everything is local: expressions are evaluated through the `ast`
module with a whitelisted node set and a fixed math namespace, so no
arbitrary code can run. Requires openpyxl (already a project
dependency) for the Excel export.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QKeyEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.styles import COLORS
from gui.icons import icon, pixmap

try:  # openpyxl ships with the suite (see requirements.txt)
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    _HAS_OPENPYXL = True
except Exception:  # pragma: no cover - graceful degradation
    _HAS_OPENPYXL = False


# ── Safe expression evaluation ──────────────────────────────────────

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.Pow: operator.pow,
}

_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name,
    ast.Call, ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
    ast.FloorDiv, ast.Pow, ast.USub, ast.UAdd,
)

_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "phi": (1.0 + math.sqrt(5.0)) / 2.0,
}

_FUNC_NAMES = frozenset(
    {"sin", "cos", "tan", "asin", "acos", "atan", "log", "ln", "sqrt", "fact"})


def _convert_factorials(expr: str) -> str:
    """Rewrite `X!` (number or (...) groups) as `fact(X)` before parsing."""
    result = expr
    while "!" in result:
        idx = result.index("!")
        j = idx - 1
        if j < 0:
            raise ValueError("misplaced !")
        if result[j] == ")":
            depth = 0
            start = j
            while start >= 0:
                if result[start] == ")":
                    depth += 1
                elif result[start] == "(":
                    depth -= 1
                    if depth == 0:
                        break
                start -= 1
            if start < 0:
                raise ValueError("unbalanced parentheses")
        else:
            start = j
            while start > 0 and (result[start - 1].isdigit() or result[start - 1] == "."):
                start -= 1
        result = result[:start] + "fact(" + result[start:idx] + ")" + result[idx + 1:]
    return result


class _Evaluator:
    """Evaluates display expressions against a whitelisted math namespace."""

    def __init__(self, degrees_provider):
        self._degrees = degrees_provider

    @staticmethod
    def _prepare(expr: str, last_result: float | None) -> str:
        if last_result is not None:
            expr = expr.replace("Ans", f"({last_result!r})")
        expr = expr.replace("×", "*").replace("÷", "/").replace("−", "-")
        expr = expr.replace("°", "").replace("√", "sqrt").replace("π", "pi")
        # 5% → (5/100); also matches "(2+3)%"-style tails after the rewrite
        expr = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", expr)
        expr = _convert_factorials(expr)
        expr = expr.replace("^", "**")
        return expr

    def _namespace(self) -> dict:
        deg = bool(self._degrees())

        def trig(fn):
            def inner(x: float) -> float:
                return fn(math.radians(x)) if deg else fn(x)
            return inner

        def inv(fn):
            def inner(x: float) -> float:
                return math.degrees(fn(x)) if deg else fn(x)
            return inner

        ns = dict(_CONSTANTS)
        ns.update({
            "sin": trig(math.sin), "cos": trig(math.cos), "tan": trig(math.tan),
            "asin": inv(math.asin), "acos": inv(math.acos), "atan": inv(math.atan),
            "log": math.log10, "ln": math.log, "sqrt": math.sqrt,
            "fact": math.factorial,
        })
        return ns

    def evaluate(self, raw: str, last_result: float | None) -> float:
        expr = self._prepare(raw.strip(), last_result)
        if not expr:
            raise ValueError("empty expression")
        tree = ast.parse(expr, mode="eval")
        for node in ast.walk(tree):
            if not isinstance(node, _ALLOWED_NODES):
                raise ValueError(f"disallowed: {type(node).__name__}")
            if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
                raise ValueError("constants must be numeric")
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.keywords:
                    raise ValueError("invalid call")
                if node.func.id not in _FUNC_NAMES:
                    raise ValueError(f"unknown function {node.func.id}")
            if isinstance(node, ast.Name) and node.id not in _CONSTANTS \
                    and node.id not in _FUNC_NAMES:
                raise ValueError(f"unknown name {node.id}")
            if isinstance(node, ast.BinOp):
                if type(node.op) not in _BIN_OPS:
                    raise ValueError("unknown operator")
        code = compile(tree, "<calculator>", "eval")
        result = eval(code, {"__builtins__": {}}, self._namespace())  # noqa: S307
        if isinstance(result, bool) or not isinstance(result, (int, float)):
            raise ValueError("non-numeric result")
        return float(result)


def _format_number(value: float) -> str:
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    text = f"{value:.10g}"
    return text


def _is_operator(ch: str) -> bool:
    """Characters that mean 'continue from the previous answer' (Windows
    calculator style: after '=', typing an operator chains the result)."""
    return ch in "+-×÷*−/^%"


class _ResultDisplay(QLineEdit):
    """Calculator display that captures ESC (clear calc, never the notes)
    and Windows-style operator chaining right after '='.

    Windows behaviour reproduced:
      * after a result is shown, typing a DIGIT starts a fresh number
        (display is replaced, not appended to the answer),
      * typing an OPERATOR continues from the previous answer at full
        precision, even though the display shows the rounded text,
      * ESC clears the calculator only — notes are untouched.
    """

    def __init__(self, panel: "CalculatedNotesPanel"):
        super().__init__()
        self._panel = panel

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._panel.clear_calculator()
            return
        text = event.text()
        if self._panel and self._panel._just_answered:
            if text and _is_operator(text):
                # continue from the previous answer: seed with full-precision Ans
                self._panel._just_answered = False
                self._panel._seed_ans_operator(text)
                return
            if text and (text.isdigit() or text == "."):
                # fresh number replaces the answer, like Windows calculator
                self._panel._just_answered = False
                self.clear()
            # any other key (letters, navigation...) falls through normally
        super().keyPressEvent(event)


# ── Panel ───────────────────────────────────────────────────────────

class CalculatedNotesPanel(QWidget):
    """Scientific calculator + sequential calculation notes (portrait)."""

    def __init__(self):
        super().__init__()
        self._degrees = True
        self._last_result: float | None = None
        self._entries: list[dict] = []   # {expr, result, time, date}
        self._evaluator = _Evaluator(lambda: self._degrees)
        self._just_answered = False      # display currently shows an answer

        self._build_ui()

    # -- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        scroll = QFrame(self)
        scroll.setObjectName("panelRoot")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 28, 32, 32)
        outer.setSpacing(0)

        header = QLabel("Calculated Notes")
        header.setObjectName("panelTitle")
        outer.addWidget(header)
        sub = QLabel("Scientific calculator — every result is recorded "
                     "sequentially in the notes beside it. Save to Excel or clear anytime.")
        sub.setObjectName("panelSubtitle")
        sub.setWordWrap(True)
        outer.addWidget(sub)
        outer.addSpacing(20)

        # Portrait layout: calculator (fixed) | notes (stretch)
        row = QHBoxLayout()
        row.setSpacing(20)
        row.addWidget(self._build_calculator_card(), 0)
        row.addWidget(self._build_notes_card(), 1)
        outer.addLayout(row, 1)

        # ESC clears the calculator no matter which widget inside the panel
        # holds focus (Windows-calculator behaviour); notes are never touched.
        from PyQt6.QtGui import QKeySequence, QShortcut
        self._esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._esc_shortcut.activated.connect(self.clear_calculator)

    def _card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(
            f"QFrame#card{{background:{COLORS['card_bg']};"
            f"border:1px solid {COLORS['card_border']};border-radius:12px;}}")
        return card

    def _build_calculator_card(self) -> QFrame:
        card = self._card()
        card.setFixedWidth(400)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 18, 20, 18)
        cl.setSpacing(12)

        title_row = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(pixmap("chart", COLORS.get("accent", "#22D3EE"), 20))
        icon_lbl.setFixedSize(20, 20)
        icon_lbl.setScaledContents(True)
        title_row.addWidget(icon_lbl)
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        t1 = QLabel("Scientific Calculator")
        t1.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        t1.setStyleSheet(f"color:{COLORS['text_primary']};")
        t2 = QLabel("Type or tap — press = to record into notes")
        t2.setFont(QFont("Segoe UI", 9))
        t2.setStyleSheet(f"color:{COLORS['text_muted']};")
        title_col.addWidget(t1)
        title_col.addWidget(t2)
        title_row.addLayout(title_col)
        title_row.addStretch()
        cl.addLayout(title_row)

        # Expression line (small, above) — shows the expression just evaluated
        self._expr_line = QLabel("")
        self._expr_line.setFont(QFont("Cascadia Mono", 9))
        self._expr_line.setAlignment(Qt.AlignmentFlag.AlignRight |
                                     Qt.AlignmentFlag.AlignVCenter)
        self._expr_line.setStyleSheet(f"color:{COLORS['text_muted']};padding:0 12px;")
        self._expr_line.setFixedHeight(18)
        cl.addWidget(self._expr_line)

        # Result display — shows the ANSWER after '=' (Windows-calculator style)
        self._calc_display = _ResultDisplay(self)
        self._calc_display.setPlaceholderText("e.g. 45 × sin(30) + √(16)")
        self._calc_display.setFixedHeight(46)
        self._calc_display.setFont(QFont("Cascadia Mono", 13))
        self._calc_display.setStyleSheet(
            f"QLineEdit{{background:{COLORS['input_bg']};"
            f"border:1px solid {COLORS['input_border']};border-radius:8px;"
            f"padding:0 12px;color:{COLORS['text_primary']};}}")
        self._calc_display.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._calc_display.returnPressed.connect(self._on_equals)
        self._calc_display.textChanged.connect(self._on_text_changed)
        cl.addWidget(self._calc_display)

        # Result / live preview strip
        res_row = QHBoxLayout()
        self._mode_lbl = QPushButton("DEG")
        self._mode_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_lbl.setFixedSize(52, 24)
        self._mode_lbl.setToolTip("Toggle Degree / Radian for trig functions")
        self._mode_lbl.setStyleSheet(
            f"QPushButton{{background:{COLORS['active_bg']};color:{COLORS['text_primary']};"
            f"border:1px solid {COLORS['border']};border-radius:5px;"
            f"font-size:10px;font-weight:bold;}}")
        self._mode_lbl.clicked.connect(self._toggle_mode)
        res_row.addWidget(self._mode_lbl)
        res_row.addStretch()
        self._preview_lbl = QLabel("")
        self._preview_lbl.setFont(QFont("Cascadia Mono", 11))
        self._preview_lbl.setStyleSheet(f"color:{COLORS['text_muted']};")
        res_row.addWidget(self._preview_lbl)
        cl.addLayout(res_row)

        # Button grid
        grid_host = QFrame()
        grid_host.setStyleSheet("background: transparent;")
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(7)

        # (label, row, col, kind, insert_text)
        spec = [
            ("x²",  0, 1, "fn", "^2"), ("x³",  0, 2, "fn", "^3"),
            ("xʸ",  0, 3, "fn", "^"),  ("√",   0, 4, "fn", "√("),
            ("sin", 1, 0, "fn", "sin("), ("cos", 1, 1, "fn", "cos("),
            ("tan", 1, 2, "fn", "tan("), ("log", 1, 3, "fn", "log("),
            ("ln",  1, 4, "fn", "ln("),
            ("(",   2, 0, "fn", "("),  (")",  2, 1, "fn", ")"),
            ("π",   2, 2, "fn", "π"),  ("e",  2, 3, "fn", "e"),
            ("x!",  2, 4, "fn", "!"),
            ("7",   3, 0, "digit", "7"), ("8", 3, 1, "digit", "8"),
            ("9",   3, 2, "digit", "9"), ("÷",  3, 3, "op", "÷"),
            ("C",   3, 4, "clr", "C"),
            ("4",   4, 0, "digit", "4"), ("5", 4, 1, "digit", "5"),
            ("6",   4, 2, "digit", "6"), ("×",  4, 3, "op", "×"),
            ("⌫",   4, 4, "clr", "BS"),
            ("1",   5, 0, "digit", "1"), ("2", 5, 1, "digit", "2"),
            ("3",   5, 2, "digit", "3"), ("−",  5, 3, "op", "−"),
            ("%",   5, 4, "op", "%"),
            ("0",   6, 0, "digit", "0"), (".", 6, 1, "digit", "."),
            ("Ans", 6, 2, "fn", "Ans"), ("+", 6, 3, "op", "+"),
        ]

        styles = {
            "digit": (f"background:{COLORS['input_bg']};color:{COLORS['text_primary']};"
                      f"border:1px solid {COLORS['input_border']};", 13),
            "fn":    (f"background:{COLORS['bg_secondary']};color:{COLORS['accent']};"
                      f"border:1px solid {COLORS['border_subtle']};", 11),
            "op":    (f"background:{COLORS.get('accent_bg', 'rgba(34,211,238,0.14)')};"
                      f"color:{COLORS['accent_light']};"
                      f"border:1px solid {COLORS.get('accent_dim', '#0E9BBE')};", 14),
            "clr":   (f"background:{COLORS.get('error_bg', 'rgba(248,113,113,0.12)')};"
                      f"color:{COLORS.get('error', '#F87171')};"
                      f"border:1px solid {COLORS['border_subtle']};", 13),
        }

        for label, r, c, kind, ins in spec:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setFixedSize(64, 40)
            qss, fsize = styles[kind]
            btn.setStyleSheet(
                f"QPushButton{{{qss}border-radius:8px;font-size:{fsize}px;}}"
                f"QPushButton:hover{{border-color:{COLORS['accent']};}}"
                f"QPushButton:pressed{{background:{COLORS['active_bg']};}}")
            btn.clicked.connect(lambda _=False, t=ins: self._on_key(t))
            grid.addWidget(btn, r, c)

        # DEG/RAD toggle occupies r0c0; = spans the last row tail
        deg_btn = QPushButton("DEG")
        deg_btn.setObjectName("calcDegBtn")
        deg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        deg_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        deg_btn.setFixedSize(64, 40)
        deg_btn.setStyleSheet(
            f"QPushButton{{background:{COLORS['active_bg']};color:{COLORS['text_primary']};"
            f"border:1px solid {COLORS['border']};border-radius:8px;"
            f"font-size:11px;font-weight:bold;}}")
        deg_btn.clicked.connect(self._toggle_mode)
        self._grid_deg_btn = deg_btn
        grid.addWidget(deg_btn, 0, 0)

        eq_btn = QPushButton("=")
        eq_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        eq_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        eq_btn.setFixedSize(64, 40)
        eq_btn.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {COLORS['accent']},stop:1 {COLORS.get('accent_2', '#8B5CF6')});"
            f"color:{COLORS.get('text_inverted', '#0B1120')};border:none;"
            f"border-radius:8px;font-size:18px;font-weight:bold;}}")
        eq_btn.clicked.connect(self._on_equals)
        grid.addWidget(eq_btn, 6, 4)

        cl.addWidget(grid_host)
        cl.addStretch()
        return card

    def _build_notes_card(self) -> QFrame:
        card = self._card()
        nl = QVBoxLayout(card)
        nl.setContentsMargins(20, 18, 20, 18)
        nl.setSpacing(12)

        title_row = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(pixmap("file-text", COLORS.get("accent", "#22D3EE"), 20))
        icon_lbl.setFixedSize(20, 20)
        icon_lbl.setScaledContents(True)
        title_row.addWidget(icon_lbl)
        t1 = QLabel("Notes")
        t1.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        t1.setStyleSheet(f"color:{COLORS['text_primary']};")
        title_row.addWidget(t1)
        title_row.addStretch()
        self._count_lbl = QLabel("0 calculations")
        self._count_lbl.setFont(QFont("Segoe UI", 9))
        self._count_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']};background:{COLORS['bg_secondary']};"
            f"border:1px solid {COLORS['border_subtle']};border-radius:9px;"
            f"padding:2px 10px;")
        title_row.addWidget(self._count_lbl)
        nl.addLayout(title_row)

        self._notes_view = QTextEdit()
        self._notes_view.setReadOnly(True)
        self._notes_view.setFont(QFont("Cascadia Mono", 10))
        self._notes_view.setStyleSheet(
            f"QTextEdit{{background:{COLORS['input_bg']};"
            f"border:1px solid {COLORS['input_border']};border-radius:8px;"
            f"padding:10px;color:{COLORS['text_primary']};}}")
        self._notes_view.setPlaceholderText(
            "Recorded calculations will appear here, in order…")
        nl.addWidget(self._notes_view, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._save_btn = QPushButton("  Save to Excel")
        self._save_btn.setIcon(icon("save", COLORS.get("text_inverted", "#0B1120"), 16))
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setFixedHeight(36)
        self._save_btn.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {COLORS['accent']},stop:1 {COLORS.get('accent_dim', '#0E9BBE')});"
            f"color:{COLORS.get('text_inverted', '#0B1120')};border:none;"
            f"border-radius:8px;padding:0 18px;font-size:12px;font-weight:bold;}}")
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)

        self._clear_btn = QPushButton("  Clear")
        self._clear_btn.setIcon(icon("trash", COLORS.get("error", "#F87171"), 16))
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setFixedHeight(36)
        self._clear_btn.setStyleSheet(
            f"QPushButton{{background:{COLORS.get('error_bg', 'rgba(248,113,113,0.12)')};"
            f"color:{COLORS.get('error', '#F87171')};"
            f"border:1px solid {COLORS.get('error', '#F87171')};"
            f"border-radius:8px;padding:0 18px;font-size:12px;font-weight:bold;}}")
        self._clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(self._clear_btn)

        nl.addLayout(btn_row)
        return card

    # -- Calculator behaviour -------------------------------------------

    def _toggle_mode(self) -> None:
        self._degrees = not self._degrees
        label = "DEG" if self._degrees else "RAD"
        self._mode_lbl.setText(label)
        self._grid_deg_btn.setText(label)

    def _on_key(self, token: str) -> None:
        if token == "C":
            self.clear_calculator()          # ESC/C: clear calc, never the notes
            return
        if token == "BS":
            self._just_answered = False
            text = self._calc_display.text()
            self._calc_display.setText(text[:-1])
            return
        if self._just_answered:
            if _is_operator(token):
                self._seed_ans_operator(token)
                return
            if token[0:1].isdigit() or token == "." or token in ("(", "√("):
                # fresh value replaces the answer (Windows calculator style)
                self._just_answered = False
                self._calc_display.clear()
            elif token == "Ans":
                self._just_answered = False
            # function tokens (sin(, log(, ^…) fall through and chain on Ans
        self._calc_display.insert(token)

    def _on_text_changed(self, text: str) -> None:
        """Live preview of the result while typing (muted, not recorded).
        While the display is showing a settled answer, the preview is left
        alone so the result stays readable."""
        if self._just_answered:
            return
        if not text.strip():
            self._preview_lbl.setText("")
            return
        try:
            value = self._evaluator.evaluate(text, self._last_result)
            self._preview_lbl.setText(f"= {_format_number(value)}")
            self._preview_lbl.setStyleSheet(f"color:{COLORS['text_muted']};")
        except Exception:
            self._preview_lbl.setText("")

    def _seed_ans_operator(self, op: str) -> None:
        """Continue from the previous answer at FULL precision: display
        'Ans<op>' so the expression reads naturally (the evaluator replaces
        Ans with the unrounded last result)."""
        self._calc_display.setText(f"Ans{op}")
        self._calc_display.setFocus()
        # move the cursor to the end so typing continues the expression
        self._calc_display.setCursorPosition(len(self._calc_display.text()))

    def clear_calculator(self) -> None:
        """ESC / C behaviour — Windows style: clear the calculator display,
        expression line and preview; the NOTES are never touched."""
        self._calc_display.clear()
        self._preview_lbl.setText("")
        self._expr_line.setText("")
        self._just_answered = False
        self._calc_display.setFocus()

    def _on_equals(self) -> None:
        raw = self._calc_display.text().strip()
        if not raw:
            return
        # = pressed while the answer is already on screen: nothing new to
        # evaluate — never record a duplicate entry
        if self._just_answered and raw == _format_number(self._last_result or 0.0):
            return
        try:
            value = self._evaluator.evaluate(raw, self._last_result)
        except Exception:
            self._preview_lbl.setText("Error — check expression")
            self._preview_lbl.setStyleSheet(f"color:{COLORS.get('error', '#F87171')};")
            return

        result_text = _format_number(value)
        self._last_result = value
        now = datetime.now()
        self._entries.append({
            "expr": raw,
            "result": result_text,
            "time": now.strftime("%H:%M:%S"),
            "date": now.strftime("%d-%b-%Y"),
        })
        # Windows-calculator style: the ANSWER fills the display, the
        # evaluated expression moves to the small line above — and the same
        # result is recorded into the notes simultaneously (carry-forward).
        self._expr_line.setText(raw)
        self._calc_display.setText(result_text)
        self._just_answered = True
        self._preview_lbl.setText("")
        self._render_notes()

    # -- Notes display ---------------------------------------------------

    def _render_notes(self) -> None:
        if not self._entries:
            self._notes_view.clear()
            self._count_lbl.setText("0 calculations")
            return
        rows = []
        accent = COLORS.get("accent", "#22D3EE")
        muted = COLORS.get("text_muted", "#7C8CA8")
        primary = COLORS.get("text_primary", "#E8EEF9")
        for i, entry in enumerate(self._entries, start=1):
            rows.append(
                f"<div style='margin-bottom:10px;'>"
                f"<span style='color:{muted};font-size:9px;'>"
                f"#{i} &nbsp;·&nbsp; {entry['time']} &nbsp;·&nbsp; {entry['date']}"
                f"</span><br>"
                f"<span style='color:{primary};'>{entry['expr']}</span><br>"
                f"<span style='color:{accent};font-weight:bold;'>"
                f"= {entry['result']}</span></div>")
        self._notes_view.setHtml("".join(rows))
        self._count_lbl.setText(f"{len(self._entries)} "
                                f"{'calculation' if len(self._entries) == 1 else 'calculations'}")
        bar = self._notes_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    # -- Save / Clear -----------------------------------------------------

    def _on_save(self) -> None:
        if not self._entries:
            QMessageBox.information(self, "Calculated Notes",
                                    "No calculations recorded yet.\n"
                                    "Use the calculator and press = to add entries.")
            return
        if not _HAS_OPENPYXL:
            QMessageBox.warning(self, "Calculated Notes",
                                "openpyxl is required for Excel export.\n"
                                "Install it with:  pip install openpyxl")
            return

        default_name = f"Calculated_Notes_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Calculated Notes", default_name,
            "Excel Workbook (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        try:
            self._export_xlsx(path)
        except Exception as exc:  # pragma: no cover - surfaced to the user
            QMessageBox.critical(self, "Calculated Notes",
                                 f"Could not save the Excel file:\n{exc}")
            return
        QMessageBox.information(
            self, "Calculated Notes",
            f"Saved {len(self._entries)} calculation(s) to:\n{path}")

    def _export_xlsx(self, path: str) -> None:
        wb = Workbook()
        ws = wb.active
        ws.title = "Calculated Notes"

        accent = COLORS.get("accent", "#22D3EE").lstrip("#")
        title_font = Font(name="Segoe UI", size=13, bold=True, color="FFFFFF")
        title_fill = PatternFill("solid", fgColor=accent)
        head_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
        head_fill = PatternFill("solid", fgColor="1F2937")
        body_font = Font(name="Consolas", size=10)
        thin = Side(style="thin", color="D1D5DB")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        center = Alignment(horizontal="center", vertical="center")

        ws.merge_cells("A1:E1")
        ws["A1"] = ("Bridge Engineering Suite — Calculated Notes  "
                    f"(exported {datetime.now():%d-%b-%Y %H:%M})")
        ws["A1"].font = title_font
        ws["A1"].fill = title_fill
        ws["A1"].alignment = center
        ws.row_dimensions[1].height = 24

        headers = ["Sr. No", "Date", "Time", "Expression", "Result"]
        for col, name in enumerate(headers, start=1):
            cell = ws.cell(row=2, column=col, value=name)
            cell.font = head_font
            cell.fill = head_fill
            cell.alignment = center
            cell.border = border

        for idx, entry in enumerate(self._entries, start=1):
            row = idx + 2
            values = [idx, entry["date"], entry["time"], entry["expr"], entry["result"]]
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=row, column=col, value=value)
                cell.font = body_font
                cell.border = border
            ws.cell(row=row, column=1).alignment = center
            ws.cell(row=row, column=5).font = Font(name="Consolas", size=10, bold=True)

        widths = {"A": 8, "B": 13, "C": 11, "D": 46, "E": 20}
        for col_letter, width in widths.items():
            ws.column_dimensions[col_letter].width = width
        ws.freeze_panes = "A3"

        wb.save(path)

    def _on_clear(self) -> None:
        if not self._entries:
            self._calc_display.clear()
            self._preview_lbl.setText("")
            return
        confirm = QMessageBox.question(
            self, "Clear Notes",
            f"Clear all {len(self._entries)} recorded calculation(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._entries.clear()
        self._last_result = None
        self._just_answered = False
        self._calc_display.clear()
        self._preview_lbl.setText("")
        self._expr_line.setText("")
        self._render_notes()

    # -- Session state (preserved across theme rebuilds) ------------------

    def export_entries(self) -> list[dict]:
        """Snapshot of recorded calculations for cross-rebuild restoration."""
        return [dict(entry) for entry in self._entries]

    def restore_entries(self, entries: list[dict]) -> None:
        self._entries = [dict(entry) for entry in entries]
        self._render_notes()
