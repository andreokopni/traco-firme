"""Diálogos: tamanho da folha, mesa digitalizadora e guia rápido."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QProgressBar, QPushButton,
    QRadioButton, QTextBrowser, QVBoxLayout,
)

from . import diag
from .widgets import caption


class NewDocumentDialog(QDialog):
    PRESETS = [
        ("A4 retrato, 300 dpi", 2480, 3508, 300),
        ("A4 paisagem, 300 dpi", 3508, 2480, 300),
        ("A5 retrato, 300 dpi", 1748, 2480, 300),
        ("Quadrado 3000 × 3000", 3000, 3000, 300),
        ("Personalizado", None, None, None),
    ]
    ANCHORS = [("Centralizado", 0.5), ("Preso ao canto superior esquerdo", 0.0)]

    def __init__(self, parent, doc, resize=False):
        from PySide6.QtWidgets import QSpinBox

        super().__init__(parent)
        self.setWindowTitle("Tamanho da folha" if resize else "Novo desenho")
        self.preset = QComboBox()
        for name, *_ in self.PRESETS:
            self.preset.addItem(name)
        self.w = QSpinBox(minimum=64, maximum=20000, value=doc.width, suffix=" px")
        self.h = QSpinBox(minimum=64, maximum=20000, value=doc.height, suffix=" px")
        self.dpi = QSpinBox(minimum=72, maximum=1200, value=doc.dpi, suffix=" dpi")
        self.cm = QLabel()
        form = QFormLayout(self)
        form.addRow("Modelo", self.preset)
        form.addRow("Largura", self.w)
        form.addRow("Altura", self.h)
        form.addRow("Resolução", self.dpi)
        form.addRow("Tamanho impresso", self.cm)
        self.anchor = None
        if resize:
            self.anchor = QComboBox()
            for name, _ in self.ANCHORS:
                self.anchor.addItem(name)
            form.addRow("Desenho na folha", self.anchor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.preset.setCurrentIndex(self._matching_preset())
        self.preset.currentIndexChanged.connect(self._preset)
        for spin in (self.w, self.h, self.dpi):
            spin.valueChanged.connect(self._edited)
        self._show_cm()

    def _matching_preset(self):
        current = (self.w.value(), self.h.value(), self.dpi.value())
        for i, (_, w, h, dpi) in enumerate(self.PRESETS):
            if (w, h, dpi) == current:
                return i
        return len(self.PRESETS) - 1

    def _preset(self, i):
        _, w, h, dpi = self.PRESETS[i]
        if w:
            for spin, v in ((self.w, w), (self.h, h), (self.dpi, dpi)):
                spin.blockSignals(True)
                spin.setValue(v)
                spin.blockSignals(False)
        self._show_cm()

    def _edited(self):
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(self._matching_preset())
        self.preset.blockSignals(False)
        self._show_cm()

    def _show_cm(self):
        k = 2.54 / self.dpi.value()
        self.cm.setText(f"{self.w.value() * k:.1f} × {self.h.value() * k:.1f} cm".replace(".", ","))

    def anchor_factor(self):
        return self.ANCHORS[self.anchor.currentIndex()][1] if self.anchor else 0.5

    @classmethod
    def preset_name(cls, doc):
        for name, w, h, dpi in cls.PRESETS:
            if (w, h, dpi) == (doc.width, doc.height, doc.dpi):
                return name.split(",")[0]
        return None


class TabletDialog(QDialog):
    """Escolha do modo da mesa com um medidor de pressão ao vivo. Não é modal: dá para
    testar a caneta na área de desenho com ele aberto."""

    def __init__(self, window):
        super().__init__(window)
        self.window_ = window
        self.setWindowTitle("Mesa digitalizadora")
        self.setMinimumWidth(420)
        col = QVBoxLayout(self)

        title = QLabel("Teste a caneta")
        title.setObjectName("sectionTitle")
        col.addWidget(title)
        col.addWidget(caption("Com esta janela aberta, encoste a caneta na folha: primeiro de leve, "
                              "depois com força. A barra precisa acompanhar a força."))
        self.source = QLabel("Aguardando a caneta…")
        col.addWidget(self.source)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setFormat("Pressão: %p%")
        col.addWidget(self.meter)

        title = QLabel("Modo da mesa")
        title.setObjectName("sectionTitle")
        col.addSpacing(8)
        col.addWidget(title)
        self.ink = QRadioButton("Windows Ink (recomendado)")
        self.wintab = QRadioButton("WinTab")
        col.addWidget(self.ink)
        col.addWidget(caption("Funciona com quase todas as mesas atuais. Se o driver da mesa tiver a "
                              "opção \"Usar Windows Ink\", deixe-a ligada."))
        col.addWidget(self.wintab)
        col.addWidget(caption("Use se a barra de pressão não se mexe no modo Windows Ink."))
        (self.wintab if window.settings.input_backend == "wintab" else self.ink).setChecked(True)
        self.ink.toggled.connect(lambda on: on and self._backend("ink"))
        self.wintab.toggled.connect(lambda on: on and self._backend("wintab"))

        title = QLabel("Diagnóstico")
        title.setObjectName("sectionTitle")
        col.addSpacing(8)
        col.addWidget(title)
        self.log_box = QCheckBox("Gravar log de diagnóstico (só até fechar o programa)")
        self.log_box.setChecked(diag.log.enabled)
        self.log_box.toggled.connect(window.set_diag_log)
        col.addWidget(self.log_box)
        col.addWidget(caption("Registra o que a mesa envia, para investigar problemas. Fica desligado "
                              "a menos que você ligue aqui."))
        open_logs = QPushButton("Abrir pasta dos logs")
        open_logs.clicked.connect(self._open_logs)
        col.addWidget(open_logs, alignment=Qt.AlignmentFlag.AlignLeft)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        col.addWidget(buttons)
        window.canvas.inputChanged.connect(self._on_input)

    def _on_input(self, source, pressure):
        self.source.setText(f"Recebendo: {source}")
        self.meter.setValue(round(pressure * 100))

    def _backend(self, backend):
        actual = self.window_.set_backend(backend)
        if actual != backend:
            self.ink.setChecked(True)

    def _open_logs(self):
        os.makedirs(diag.LOG_DIR, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(diag.LOG_DIR))

    def closeEvent(self, e):
        try:
            self.window_.canvas.inputChanged.disconnect(self._on_input)
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(e)


GUIDE_HTML = """
<h2>Bem-vindo ao Traço Firme</h2>
<p>Um caderno de lineart que segura o tremor da mão e endireita as formas para você.</p>

<h3>✏️ Desenhar</h3>
<p>Desenhe normalmente com a caneta. Enquanto você desenha, uma linha vermelha curta aparece
entre a caneta e o traço: é o <b>estabilizador</b> segurando o tremor. Ao soltar, a linha é
<b>alisada</b>. Os dois ajustes ficam no painel à direita, em <i>Ajuda no traço</i>.</p>
<p>Achou o último traço mole ou duro demais? Mexa em <b>Suavidade</b>: o último traço muda junto.</p>

<h3>📐 Endireitar formas</h3>
<p>No fim do traço, <b>segure a caneta parada sem levantar</b>. Um anel azul enche em volta da
ponta e o traço vira a forma perfeita: <b>reta, arco, círculo, elipse, triângulo, retângulo,
quadrado</b>… Um quadrado torto vira quadrado. Antes de soltar você ainda pode mover a ponta
de retas e arcos.</p>
<p>Se o anel ficar vermelho, a forma não foi reconhecida; é só soltar e o traço fica como está.</p>
<p>Para uma reta direta: segure <b>Shift</b> enquanto desenha (com <b>Ctrl+Shift</b> o ângulo trava
de 15 em 15°).</p>

<h3>🖐️ Mover, aproximar e girar</h3>
<p><b>Espaço</b> + arrastar (ou o botão lateral da caneta) move a folha. A <b>roda do mouse</b>
aproxima. As teclas <b>4</b> e <b>6</b> giram a folha, e <b>5</b> volta ao normal: gire até o
traço ficar confortável para o seu pulso.</p>

<h3>🧽 Apagar</h3>
<p>Use a <b>Borracha</b> (tecla <b>E</b>) ou vire a caneta. <b>Ctrl+Z</b> desfaz qualquer coisa.</p>

<h3>🎨 Levar para o Krita</h3>
<p>Clique em <b>Exportar para o Krita</b>. Saem dois arquivos: um <b>PNG</b> com fundo transparente
(abra no Krita e pinte por baixo) e um <b>SVG</b> com as linhas em vetor. Se arrastar o PNG para
um desenho já aberto, escolha <b>Inserir como nova camada</b>: uma <i>camada de arquivo</i> não aceita
pintura. Com <i>Fechar falhas entre
linhas</i> ligado, o balde de tinta do Krita não vaza pelas emendas.</p>

<h3>⌨️ Atalhos</h3>
<p><b>B</b> pincel · <b>E</b> borracha · <b>[ ]</b> tamanho · <b>Ctrl+Z / Ctrl+Y</b> desfazer/refazer ·
<b>Ctrl+S</b> salvar · <b>Ctrl+E</b> exportar · <b>Ctrl+0</b> enquadrar a folha</p>
"""


class GuideDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Guia rápido")
        self.resize(560, 640)
        col = QVBoxLayout(self)
        text = QTextBrowser()
        text.setHtml(GUIDE_HTML)
        text.setOpenExternalLinks(True)
        col.addWidget(text)
        buttons = QDialogButtonBox()
        ok = buttons.addButton("Começar a desenhar", QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setDefault(True)
        buttons.accepted.connect(self.accept)
        col.addWidget(buttons)
