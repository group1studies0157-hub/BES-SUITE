"""UI text cleanup helpers.

The app has accumulated a mix of emoji and mojibake text in visible labels.
This module keeps the visual layer clean without touching business logic.
"""

from __future__ import annotations

import re
import unicodedata


_REPLACEMENTS = {
    "\ufeff": "",
    "\ufffd": "",
    "\u00a0": " ",
    "\u00b7": " - ",
    "\u2022": " - ",
    "\u2013": "-",
    "\u2014": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u2212": "-",
    "\u2153": "1/3",
    "\u00bd": "1/2",
    "\u2190": "<-",
    "\u2192": "->",
    "\u21d2": "=>",
    "\u2713": "",
    "\u2714": "",
    "\u2717": "",
    "\u2718": "",
    "\u26a0": "Warning",
}

_EMOJI_RE = re.compile(
    "["
    "\U0001f1e6-\U0001f1ff"
    "\U0001f300-\U0001f5ff"
    "\U0001f600-\U0001f64f"
    "\U0001f680-\U0001f6ff"
    "\U0001f700-\U0001f77f"
    "\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001faff"
    "\u2600-\u27bf"
    "]+",
    flags=re.UNICODE,
)

_MOJIBAKE_MARKERS = ("\u00c2", "\u00c3", "\u00e2", "\u00f0", "\u00ef", "\ufffd")
_MOJIBAKE_FRAGMENT_RE = re.compile(r"(?:\u00f0\S*|\u00ef\S*|\u00e2[^\w\s]*|\u00c2|\u00c3|\ufffd)")
_SPACES_RE = re.compile(r"[ \t]{2,}")


def _badness(text: str) -> int:
    score = sum(text.count(marker) * 3 for marker in _MOJIBAKE_MARKERS)
    score += sum(1 for char in text if unicodedata.category(char) == "So")
    return score


def _repair_mojibake(text: str) -> str:
    """Best-effort repair for UTF-8 text that was decoded as Windows text."""
    best = text
    best_score = _badness(text)

    for codec in ("cp1252", "latin1"):
        try:
            candidate = text.encode(codec).decode("utf-8")
        except UnicodeError:
            continue
        score = _badness(candidate)
        if score < best_score:
            best = candidate
            best_score = score

    return best


def clean_text(value) -> str:
    """Return display-safe text for labels, buttons, placeholders and status lines."""
    if value is None:
        return ""

    text = str(value)
    for _ in range(3):
        repaired = _repair_mojibake(text)
        if repaired == text:
            break
        text = repaired

    for bad, good in _REPLACEMENTS.items():
        text = text.replace(bad, good)

    text = _EMOJI_RE.sub("", text)
    text = _MOJIBAKE_FRAGMENT_RE.sub("", text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = _SPACES_RE.sub(" ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text.strip()


def _clean_arg(args: tuple, index: int) -> tuple:
    if len(args) <= index or not isinstance(args[index], str):
        return args
    mutable = list(args)
    mutable[index] = clean_text(mutable[index])
    return tuple(mutable)


def install_text_sanitizer() -> None:
    """Patch common Qt text setters once so late status messages stay clean."""
    from PyQt6.QtGui import QAction
    from PyQt6.QtWidgets import (
        QLabel,
        QPushButton,
        QLineEdit,
        QComboBox,
        QTabWidget,
        QCheckBox,
        QRadioButton,
        QListWidgetItem,
        QTableWidgetItem,
        QTextEdit,
        QPlainTextEdit,
        QWidget,
    )

    if getattr(QLabel, "_bes_text_sanitized", False):
        return

    def patch(cls, method_name):
        original = getattr(cls, method_name)

        def wrapped(self, text, *args, **kwargs):
            return original(self, clean_text(text), *args, **kwargs)

        setattr(cls, f"_bes_original_{method_name}", original)
        setattr(cls, method_name, wrapped)

    def patch_init(cls):
        original = cls.__init__

        def wrapped(self, *args, **kwargs):
            args = _clean_arg(args, 0)
            args = _clean_arg(args, 1)
            return original(self, *args, **kwargs)

        setattr(cls, "_bes_original_init", original)
        setattr(cls, "__init__", wrapped)

    for widget_cls in (
        QLabel,
        QPushButton,
        QCheckBox,
        QRadioButton,
        QListWidgetItem,
        QTableWidgetItem,
        QAction,
    ):
        patch_init(widget_cls)

    patch(QLabel, "setText")
    patch(QPushButton, "setText")
    patch(QLineEdit, "setPlaceholderText")
    patch(QAction, "setText")
    patch(QWidget, "setWindowTitle")
    patch(QTextEdit, "setPlainText")
    patch(QTextEdit, "append")
    patch(QPlainTextEdit, "setPlainText")
    patch(QPlainTextEdit, "appendPlainText")
    patch(QPlainTextEdit, "insertPlainText")

    combo_add_item = QComboBox.addItem
    combo_add_items = QComboBox.addItems
    combo_insert_item = QComboBox.insertItem
    combo_set_item_text = QComboBox.setItemText

    def add_item(self, *args, **kwargs):
        args = _clean_arg(args, 0)
        args = _clean_arg(args, 1)
        return combo_add_item(self, *args, **kwargs)

    def add_items(self, texts, **kwargs):
        return combo_add_items(self, [clean_text(t) for t in texts], **kwargs)

    def insert_item(self, *args, **kwargs):
        args = _clean_arg(args, 1)
        args = _clean_arg(args, 2)
        return combo_insert_item(self, *args, **kwargs)

    def set_item_text(self, index, text, **kwargs):
        return combo_set_item_text(self, index, clean_text(text), **kwargs)

    QComboBox.addItem = add_item
    QComboBox.addItems = add_items
    QComboBox.insertItem = insert_item
    QComboBox.setItemText = set_item_text

    tab_add_tab = QTabWidget.addTab
    tab_insert_tab = QTabWidget.insertTab

    def add_tab(self, widget, *args):
        args = _clean_arg(args, 0)
        args = _clean_arg(args, 1)
        return tab_add_tab(self, widget, *args)

    def insert_tab(self, index, widget, *args):
        args = _clean_arg(args, 0)
        args = _clean_arg(args, 1)
        return tab_insert_tab(self, index, widget, *args)

    QTabWidget.addTab = add_tab
    QTabWidget.insertTab = insert_tab

    QLabel._bes_text_sanitized = True
