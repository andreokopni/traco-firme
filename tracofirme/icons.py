"""Ícones desenhados a partir da fonte de ícones do Windows (Segoe Fluent Icons no
Windows 11, Segoe MDL2 Assets no 10). Sem arquivos de imagem para manter."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

GLYPHS = {
    "new": 0xE8A5,
    "open": 0xE838,
    "save": 0xE74E,
    "brush": 0xE70F,
    "eraser": 0xE75C,
    "undo": 0xE7A7,
    "redo": 0xE7A6,
    "clear": 0xE74D,
    "sheet": 0xE9A6,
    "sketch": 0xE8B9,
    "export": 0xEDE1,
    "help": 0xE897,
    "pen": 0xEDC6,
    "rotate": 0xE7AD,
}

_FONT_FAMILY = None


def _family():
    global _FONT_FAMILY
    if _FONT_FAMILY is None:
        families = set(QFontDatabase.families())
        _FONT_FAMILY = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in families), "")
    return _FONT_FAMILY


def icon(name, color: QColor | None = None, size=32):
    """QIcon do glifo `name`, na cor do texto do tema (ou `color`)."""
    family = _family()
    if not family:
        return QIcon()
    pal = QApplication.palette()
    normal = color or pal.windowText().color()
    disabled = QColor(normal)
    disabled.setAlphaF(0.35)
    result = QIcon()
    for mode, c in ((QIcon.Mode.Normal, normal), (QIcon.Mode.Disabled, disabled)):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = QFont(family)
        font.setPixelSize(int(size * 0.72))
        p.setFont(font)
        p.setPen(c)
        p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, chr(GLYPHS[name]))
        p.end()
        result.addPixmap(pix, mode)
    return result
