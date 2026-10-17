"""Controles reutilizáveis do painel lateral."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QFrame, QHBoxLayout, QLabel, QSlider, QToolButton, QVBoxLayout, QWidget,
)


class SliderRow(QWidget):
    """Rótulo em cima, slider com valor ao lado e, opcionalmente, palavras nas pontas
    ("Leve … Forte"). `scale` converte o valor inteiro do slider no valor real."""

    valueChanged = Signal(float)

    def __init__(self, title, lo, hi, value, scale=1.0, fmt="{:.0f}", ends=None, caption=None):
        super().__init__()
        self.scale = scale
        self.fmt = fmt
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.value_label = QLabel()
        self.value_label.setMinimumWidth(48)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 2, 0, 2)
        col.setSpacing(2)
        head = QHBoxLayout()
        head.addWidget(QLabel(title))
        head.addStretch(1)
        head.addWidget(self.value_label)
        col.addLayout(head)
        row = QHBoxLayout()
        if ends:
            row.addWidget(_small(ends[0]))
        row.addWidget(self.slider, 1)
        if ends:
            row.addWidget(_small(ends[1]))
        col.addLayout(row)
        if caption:
            col.addWidget(_caption(caption))
        self.slider.valueChanged.connect(self._changed)
        self.set_value(value)

    def set_value(self, value):
        self.slider.setValue(round(value / self.scale))
        self._show()

    def value(self):
        return self.slider.value() * self.scale

    def _show(self):
        self.value_label.setText(self.fmt.format(self.value()))

    def _changed(self, _):
        self._show()
        self.valueChanged.emit(self.value())


def _small(text):
    label = QLabel(text)
    label.setObjectName("dim")
    return label


def _caption(text):
    label = QLabel(text)
    label.setObjectName("caption")
    label.setWordWrap(True)
    return label


def caption(text):
    return _caption(text)


class Toggle(QWidget):
    """Caixa de seleção com uma explicação curta embaixo."""

    toggled = Signal(bool)

    def __init__(self, text, checked, explanation=None):
        super().__init__()
        self.box = QCheckBox(text)
        self.box.setChecked(checked)
        self.box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.box.toggled.connect(self.toggled)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 2, 0, 2)
        col.setSpacing(0)
        col.addWidget(self.box)
        if explanation:
            cap = _caption(explanation)
            cap.setContentsMargins(24, 0, 0, 0)
            col.addWidget(cap)


class Section(QFrame):
    """Cartão com título; `collapsible` mostra uma setinha para abrir/fechar."""

    def __init__(self, title, collapsible=False, expanded=True):
        super().__init__()
        self.setObjectName("section")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)
        if collapsible:
            self.header = QToolButton(text=title, checkable=True, checked=expanded)
            self.header.setObjectName("sectionHeader")
            self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.header.toggled.connect(self._toggle)
            outer.addWidget(self.header)
        else:
            self.header = QLabel(title)
            self.header.setObjectName("sectionTitle")
            outer.addWidget(self.header)
        self.body = QWidget()
        self.layout_ = QVBoxLayout(self.body)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(6)
        outer.addWidget(self.body)
        if collapsible:
            self._toggle(expanded)

    def add(self, widget):
        self.layout_.addWidget(widget)
        return widget

    def add_layout(self, layout):
        self.layout_.addLayout(layout)
        return layout

    def _toggle(self, on):
        self.body.setVisible(on)
        self.header.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)


class ColorSwatches(QWidget):
    """Bolinhas de cor prontas + botão para escolher outra."""

    colorChanged = Signal(str)
    PRESETS = [("#000000", "Preto"), ("#3a3a3a", "Grafite"), ("#1e5aa8", "Azul"),
               ("#b3261e", "Vermelho"), ("#7a4a1e", "Sépia")]

    def __init__(self, color):
        super().__init__()
        self._color = color
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.buttons = []
        for hex_, name in self.PRESETS:
            b = _SwatchButton(hex_, name)
            b.clicked.connect(lambda _=False, c=hex_: self.set_color(c, emit=True))
            row.addWidget(b)
            self.buttons.append(b)
        self.custom = _SwatchButton(None, "Outra cor…")
        self.custom.clicked.connect(self._pick)
        row.addWidget(self.custom)
        row.addStretch(1)
        self.set_color(color)

    def set_color(self, color, emit=False):
        self._color = color
        preset = any(b.color == color for b in self.buttons)
        for b in self.buttons:
            b.selected = b.color == color
            b.update()
        self.custom.color = None if preset else color
        self.custom.selected = not preset
        self.custom.update()
        if emit:
            self.colorChanged.emit(color)

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._color), self, "Cor da linha")
        if c.isValid():
            self.set_color(c.name(), emit=True)


class _SwatchButton(QToolButton):
    def __init__(self, color, tip):
        super().__init__()
        self.color = color
        self.selected = False
        self.setToolTip(tip)
        self.setFixedSize(QSize(28, 28))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(4, 4, -4, -4)
        text = self.palette().windowText().color()
        if self.selected:
            p.setPen(text)
            p.drawEllipse(self.rect().adjusted(1, 1, -2, -2))
        if self.color:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.color))
            p.drawEllipse(r)
        if self.color is None or (not self.selected and self.toolTip() == "Outra cor…"):
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(text)
            p.drawEllipse(r)
            c = r.center()
            p.drawLine(c.x() - 5, c.y(), c.x() + 5, c.y())
            p.drawLine(c.x(), c.y() - 5, c.x(), c.y() + 5)
        p.end()
