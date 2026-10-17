"""Janela principal: barra de ferramentas, painel de ajustes, menus e arquivos."""
from __future__ import annotations

import os
import platform

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import QSettings, QSize, Qt, QTimer, qVersion
from PySide6.QtGui import QAction, QActionGroup, QImage, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QRadioButton, QScrollArea, QSizePolicy, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from . import __version__, diag
from .canvas import Canvas
from .dialogs import GuideDialog, NewDocumentDialog, TabletDialog
from .document import Document
from .icons import icon
from .render import export_png, export_svg
from .settings import Settings
from .widgets import ColorSwatches, Section, SliderRow, Toggle, caption
from .winink import disable_pen_feedback
from .wintab import WinTabInput

PROJECT_FILTER = "Projeto Traço Firme (*.traco)"
APP_NAME = "Traço Firme"

STYLE = """
QFrame#section { border: 1px solid palette(midlight); border-radius: 8px; }
QLabel#sectionTitle { font-weight: 600; font-size: 10.5pt; }
QToolButton#sectionHeader { font-weight: 600; font-size: 10.5pt; border: none; padding: 0; }
QLabel#caption, QLabel#dim { color: palette(placeholder-text); font-size: 8.5pt; }
QToolButton#primary { background: #2878e6; color: white; border-radius: 6px; padding: 4px 12px;
                      font-weight: 600; }
QToolButton#primary:hover { background: #3a88f0; }
QToolBar { spacing: 2px; padding: 4px; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.doc = Document()
        self.project_path = None
        self.canvas = Canvas(self.doc, self.settings)
        self.setCentralWidget(self.canvas)
        self.wintab = WinTabInput(self, self.canvas)
        self._first_show = True
        self._tablet_dialog = None
        self.setStyleSheet(STYLE)

        self._build_actions()
        self._build_toolbar()
        self._build_menus()
        self._build_panel()
        self._build_status()

        self.canvas.statusMessage.connect(lambda m: self.statusBar().showMessage(m, 4000))
        self.canvas.inputChanged.connect(self._on_input)
        self.canvas.viewChanged.connect(self._on_view)
        self.canvas.documentChanged.connect(self._on_document_changed)
        self.set_tool(self.settings.tool)
        self._on_document_changed()
        self.resize(1400, 900)

    # --- Ações, barra de ferramentas e menus ----------------------------------------

    def _act(self, text, slot, shortcut=None, icon_name=None, tip=None, checkable=False):
        a = QAction(text, self)
        if icon_name:
            a.setIcon(icon(icon_name))
        if shortcut is not None:
            a.setShortcuts(shortcut if isinstance(shortcut, list) else [shortcut])
        if tip:
            a.setToolTip(tip)
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        self.addAction(a)  # atalhos funcionam mesmo se a ação não estiver num menu
        return a

    def _build_actions(self):
        K = QKeySequence
        self.a_new = self._act("Novo", self.new_document, K(K.StandardKey.New), "new", "Novo desenho (Ctrl+N)")
        self.a_open = self._act("Abrir", lambda: self.open_project(), K(K.StandardKey.Open), "open",
                                "Abrir projeto (Ctrl+O)")
        self.a_save = self._act("Salvar", lambda: self.save_project(), K(K.StandardKey.Save), "save",
                                "Salvar projeto (Ctrl+S)")
        self.a_save_as = self._act("Salvar como…", lambda: self.save_project(as_new=True), K("Ctrl+Shift+S"))
        self.a_brush = self._act("Pincel", lambda: self.set_tool("brush"), K("B"), "brush", "Pincel (B)", True)
        self.a_eraser = self._act("Borracha", lambda: self.set_tool("eraser"), K("E"), "eraser",
                                  "Borracha (E) — a ponta de borracha da caneta também apaga", True)
        group = QActionGroup(self)
        group.addAction(self.a_brush)
        group.addAction(self.a_eraser)
        self.a_undo = self._act("Desfazer", self.undo, K(K.StandardKey.Undo), "undo", "Desfazer (Ctrl+Z)")
        self.a_redo = self._act("Refazer", self.redo, [K("Ctrl+Y"), K("Ctrl+Shift+Z")], "redo", "Refazer (Ctrl+Y)")
        self.a_clear = self._act("Limpar", lambda: self.clear_all(), None, "clear", "Apagar o desenho todo")
        self.a_sheet = self._act("Folha", self.resize_sheet, K("Ctrl+Alt+C"), "sheet", "Tamanho da folha")
        self.a_sketch = self._act("Esboço", self.load_sketch, None, "sketch",
                                  "Carregar um esboço para desenhar por cima")
        self.a_export = self._act("Exportar para o Krita", self.export_both, K("Ctrl+E"), "export",
                                  "Salvar PNG + SVG para colorir no Krita (Ctrl+E)")
        self.a_help = self._act("Ajuda", self.show_guide, K("F1"), "help", "Guia rápido (F1)")
        self.a_tablet = self._act("Mesa digitalizadora…", self.show_tablet_dialog, None, "pen")
        self._act("Diminuir ferramenta", lambda: self._resize_tool(1 / 1.15), K("["))
        self._act("Aumentar ferramenta", lambda: self._resize_tool(1.15), K("]"))

    def _build_toolbar(self):
        tb = QToolBar("Ferramentas")
        tb.setObjectName("ferramentas")
        tb.setMovable(False)
        tb.setIconSize(QSize(22, 22))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        for a in (self.a_new, self.a_open, self.a_save):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.a_brush)
        tb.addAction(self.a_eraser)
        tb.addSeparator()
        for a in (self.a_undo, self.a_redo, self.a_clear):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.a_sheet)
        tb.addAction(self.a_sketch)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        tb.addAction(self.a_help)
        export = QToolButton()
        export.setDefaultAction(self.a_export)
        export.setObjectName("primary")
        export.setIcon(icon("export", color=Qt.GlobalColor.white))
        export.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        export.setIconSize(QSize(20, 20))
        tb.addWidget(export)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&Arquivo")
        m.addActions([self.a_new, self.a_open, self.a_save, self.a_save_as])
        m.addSeparator()
        sheet = QAction("Tamanho da folha…", self)
        sheet.triggered.connect(self.resize_sheet)
        m.addAction(sheet)
        sketch = QAction("Carregar esboço de fundo…", self)
        sketch.triggered.connect(self.load_sketch)
        m.addAction(sketch)
        m.addSeparator()
        m.addAction(self.a_export)
        other = m.addMenu("Exportar em outro formato")
        other.addAction("Só PNG (imagem)…", lambda: self.export_one("png"))
        other.addAction("Só SVG (vetor)…", lambda: self.export_one("svg"))
        m.addSeparator()
        m.addAction("Sair", self.close)

        m = mb.addMenu("&Editar")
        m.addActions([self.a_undo, self.a_redo])
        m.addSeparator()
        m.addAction("Limpar desenho…", lambda: self.clear_all())

        K = QKeySequence
        m = mb.addMenu("E&xibir")
        m.addAction(self._act("Enquadrar a folha", self.canvas.fit_view, K("Ctrl+0")))
        m.addAction(self._act("Aproximar", lambda: self.canvas.zoom_by(1.25), [K("Ctrl+="), K("+")]))
        m.addAction(self._act("Afastar", lambda: self.canvas.zoom_by(1 / 1.25), [K("Ctrl+-"), K("-")]))
        m.addSeparator()
        m.addAction(self._act("Girar para a esquerda", lambda: self.canvas.rotate_by(-15), K("4")))
        m.addAction(self._act("Girar para a direita", lambda: self.canvas.rotate_by(15), K("6")))
        m.addAction(self._act("Desfazer o giro", self.canvas.reset_rotation, K("5")))

        m = mb.addMenu("Aj&uda")
        m.addAction(self.a_help)
        m.addAction(self.a_tablet)
        m.addSeparator()
        m.addAction("Sobre o Traço Firme", self._about)

    def _build_panel(self):
        s = self.settings
        panel = QWidget()
        col = QVBoxLayout(panel)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(10)

        # Pincel
        self.brush_section = Section("Pincel")
        self.size_row = SliderRow("Tamanho", 1, 120, s.size, fmt="{:.0f} px")
        self.size_row.valueChanged.connect(lambda v: self._set("size", v))
        self.brush_section.add(self.size_row)
        self.brush_section.add(QLabel("Cor"))
        self.swatches = ColorSwatches(s.color)
        self.swatches.colorChanged.connect(lambda c: self._set("color", c))
        self.brush_section.add(self.swatches)
        col.addWidget(self.brush_section)

        # Borracha (aparece no lugar do pincel)
        self.eraser_section = Section("Borracha")
        self.eraser_row = SliderRow("Tamanho", 2, 300, s.eraser_size, fmt="{:.0f} px")
        self.eraser_row.valueChanged.connect(lambda v: self._set("eraser_size", v))
        self.eraser_section.add(self.eraser_row)
        self.eraser_section.add(QLabel("O que apagar"))
        partial = QRadioButton("Só o pedaço que a borracha toca")
        whole = QRadioButton("O traço inteiro")
        (partial if s.eraser_mode == "partial" else whole).setChecked(True)
        partial.toggled.connect(lambda on: self._set("eraser_mode", "partial" if on else "stroke"))
        self.eraser_section.add(partial)
        self.eraser_section.add(whole)
        col.addWidget(self.eraser_section)

        # Ajuda no traço
        assist = Section("Ajuda no traço")
        row = SliderRow("Estabilização", 0, 100, s.stab_level, ends=("Leve", "Forte"),
                        caption="Segura o tremor enquanto você desenha. Mais forte deixa a linha mais "
                                "firme, mas ela segue a caneta com um pouco de atraso.")
        row.valueChanged.connect(lambda v: self._set("stab_level", v))
        assist.add(row)
        row = SliderRow("Suavidade", 0, 60, s.smoothing, ends=("Pouca", "Muita"),
                        caption="Alisa a linha quando você solta a caneta. Mexer aqui também ajusta "
                                "o último traço.")
        row.valueChanged.connect(lambda v: self._set("smoothing", v, resmooth=True))
        assist.add(row)
        t = Toggle("Endireitar ao segurar a caneta parada", s.hold_snap,
                   "No fim do traço, segure parado: vira reta, arco, círculo, quadrado…")
        t.toggled.connect(lambda v: self._set("hold_snap", v))
        assist.add(t)
        t = Toggle("Fechar falhas entre linhas", s.close_gaps,
                   "Emenda a ponta do traço numa linha próxima, para o balde do Krita não vazar.")
        t.toggled.connect(lambda v: self._set("close_gaps", v, resmooth=True))
        assist.add(t)
        t = Toggle("Pontas finas", s.taper, "Afina o começo e o fim de cada traço.")
        t.toggled.connect(lambda v: self._set("taper", v, resmooth=True))
        assist.add(t)
        col.addWidget(assist)

        # Esboço de fundo
        sketch = Section("Esboço de fundo")
        sketch.add(caption("Uma imagem para desenhar por cima. Ela não vai junto na exportação."))
        self.sketch_opacity = SliderRow("Visibilidade", 5, 100, s.sketch_opacity * 100, fmt="{:.0f}%")
        self.sketch_opacity.valueChanged.connect(self._sketch_opacity)
        sketch.add(self.sketch_opacity)
        buttons = QHBoxLayout()
        self.sketch_load = QPushButton("Carregar imagem…")
        self.sketch_load.clicked.connect(self.load_sketch)
        self.sketch_remove = QPushButton("Remover")
        self.sketch_remove.clicked.connect(self.remove_sketch)
        buttons.addWidget(self.sketch_load)
        buttons.addWidget(self.sketch_remove)
        sketch.add_layout(buttons)
        col.addWidget(sketch)

        # Mais opções
        adv = Section("Mais opções", collapsible=True, expanded=False)
        row = SliderRow("Espessura com pouca pressão", 0, 100, s.min_ratio * 100, fmt="{:.0f}%",
                        caption="Quão fina a linha fica quando você encosta de leve.")
        row.valueChanged.connect(lambda v: self._set("min_ratio", v / 100))
        adv.add(row)
        row = SliderRow("Resposta da pressão", 20, 300, s.gamma, scale=0.01, fmt="{:.2f}", ends=("Macia", "Firme"),
                        caption="Macia engrossa com pouca força; firme pede mais força.")
        row.valueChanged.connect(lambda v: self._set("gamma", v))
        adv.add(row)
        row = SliderRow("Tempo segurando para endireitar", 4, 30, s.hold_ms, scale=50, fmt="{:.0f} ms")
        row.valueChanged.connect(lambda v: self._set("hold_ms", int(v)))
        adv.add(row)
        row = SliderRow("Distância para fechar falhas", 4, 40, s.gap_px, fmt="{:.0f} px")
        row.valueChanged.connect(lambda v: self._set("gap_px", v, resmooth=True))
        adv.add(row)
        t = Toggle("Preservar cantos vivos", s.keep_corners, "A suavidade não arredonda as quinas.")
        t.toggled.connect(lambda v: self._set("keep_corners", v, resmooth=True))
        adv.add(t)
        t = Toggle("Completar até a ponta da caneta", s.finish_to_tip,
                   "A linha vai até onde a caneta saiu, mesmo com estabilização forte.")
        t.toggled.connect(lambda v: self._set("finish_to_tip", v))
        adv.add(t)
        col.addWidget(adv)
        col.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(320)
        from PySide6.QtWidgets import QDockWidget
        dock = QDockWidget("Ajustes", self)
        dock.setObjectName("ajustes")
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        dock.setTitleBarWidget(QWidget())
        dock.setWidget(scroll)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self._update_sketch_controls()

    def _build_status(self):
        sb = self.statusBar()
        self.pen_label = QLabel()
        self.pressure_bar = QProgressBar()
        self.pressure_bar.setRange(0, 100)
        self.pressure_bar.setTextVisible(False)
        self.pressure_bar.setFixedSize(70, 10)
        self.pressure_bar.setToolTip("Pressão da caneta")
        self.sheet_label = QLabel()
        self.zoom_label = QLabel()
        for w in (self.pen_label, self.pressure_bar, self.sheet_label, self.zoom_label):
            sb.addPermanentWidget(w)
        self._show_backend(self.settings.input_backend)
        self._on_view()

    def showEvent(self, e):
        super().showEvent(e)
        if self._first_show:
            self._first_show = False
            disable_pen_feedback(int(self.winId()))
            if self.settings.input_backend == "wintab":
                self.set_backend("wintab", quiet=True)
            if not QSettings().value("guide_seen", False, type=bool):
                QTimer.singleShot(400, self._first_run_guide)

    def _first_run_guide(self):
        QSettings().setValue("guide_seen", True)
        self.show_guide()

    # --- Ajustes -------------------------------------------------------------------

    def _set(self, name, value, resmooth=False):
        setattr(self.settings, name, value)
        if resmooth:
            self.canvas.schedule_resmooth()
        self.canvas.update()

    def set_tool(self, tool):
        self.settings.tool = tool
        self.a_brush.setChecked(tool == "brush")
        self.a_eraser.setChecked(tool == "eraser")
        self.brush_section.setVisible(tool == "brush")
        self.eraser_section.setVisible(tool == "eraser")
        self.canvas.update()

    def _resize_tool(self, factor):
        if self.settings.tool == "eraser":
            self.eraser_row.set_value(max(2, min(300, self.settings.eraser_size * factor)))
        else:
            self.size_row.set_value(max(1, min(120, self.settings.size * factor)))

    def _sketch_opacity(self, v):
        self.settings.sketch_opacity = v / 100
        self.canvas.invalidate()

    def _update_sketch_controls(self):
        loaded = self.canvas.sketch is not None
        self.sketch_opacity.setVisible(loaded)
        self.sketch_remove.setVisible(loaded)
        self.sketch_load.setText("Trocar imagem…" if loaded else "Carregar imagem…")

    # --- Mesa digitalizadora ----------------------------------------------------------

    def set_backend(self, backend, quiet=False):
        """Liga o modo da mesa; devolve o modo que ficou ativo."""
        self.wintab.stop()
        if backend == "wintab":
            ok, msg = self.wintab.start()
            if not ok:
                if not quiet:
                    QMessageBox.warning(self, "WinTab", msg)
                backend = "ink"
            self.statusBar().showMessage(msg, 5000)
        self.settings.input_backend = backend
        diag.log.event("backend", backend=backend)
        self._show_backend(backend)
        return backend

    def _show_backend(self, backend):
        self.pen_label.setText(f"Caneta: {'WinTab' if backend == 'wintab' else 'Windows Ink'}")

    def show_tablet_dialog(self):
        if self._tablet_dialog is None:
            self._tablet_dialog = TabletDialog(self)
        self._tablet_dialog.show()
        self._tablet_dialog.raise_()

    def set_diag_log(self, on):
        diag.log.set_enabled(on)
        if on:
            self._log_session()
            self.statusBar().showMessage(f"Gravando diagnóstico em {diag.log.path}", 6000)

    def _log_session(self):
        screens = [
            {"name": s.name(), "geo": [s.geometry().x(), s.geometry().y(), s.geometry().width(), s.geometry().height()],
             "dpr": s.devicePixelRatio()}
            for s in self.screen().virtualSiblings()
        ] if self.screen() else []
        diag.log.event("session", app=__version__, os=platform.platform(), python=platform.python_version(),
                       qt=qVersion(), pyside=PYSIDE_VERSION, backend=self.settings.input_backend,
                       screens=screens, window_dpr=self.devicePixelRatioF())
        diag.log.flush()

    def _on_input(self, source, pressure):
        if source in ("Windows Ink", "WinTab"):
            self.pen_label.setText(f"Caneta: {source}")
        elif source == "Mouse":
            self.pen_label.setText("Mouse (sem pressão)")
        self.pressure_bar.setValue(round(pressure * 100))

    def _on_view(self):
        d = self.doc
        name = NewDocumentDialog.preset_name(d)
        self.sheet_label.setText(f"Folha {name + ' · ' if name else ''}{d.width} × {d.height} px")
        self.zoom_label.setText(f"Zoom {self.canvas.zoom * 100:.0f}%")

    def show_guide(self):
        GuideDialog(self).exec()

    def _about(self):
        QMessageBox.about(
            self, "Sobre o Traço Firme",
            f"<b>Traço Firme {__version__}</b><br>Lineart estabilizada para mesa digitalizadora, "
            "com exportação para o Krita.",
        )

    # --- Documento -----------------------------------------------------------------

    def _on_document_changed(self):
        self.a_undo.setEnabled(self.doc.can_undo())
        self.a_redo.setEnabled(self.doc.can_redo())
        self.a_clear.setEnabled(bool(self.doc.strokes))
        self._update_title()

    def _update_title(self):
        name = os.path.basename(self.project_path) if self.project_path else "Sem título"
        mark = "*" if self.doc.modified else ""
        self.setWindowTitle(f"{name}{mark} — {APP_NAME}")

    def undo(self):
        if not self.canvas.is_busy() and self.doc.undo():
            self._after_history_change()

    def redo(self):
        if not self.canvas.is_busy() and self.doc.redo():
            self._after_history_change()

    def _after_history_change(self):
        self.canvas.invalidate()
        self._on_view()
        self._on_document_changed()

    def resize_sheet(self):
        if self.canvas.is_busy():
            return
        dlg = NewDocumentDialog(self, self.doc, resize=True)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        w, h, d = dlg.w.value(), dlg.h.value(), self.doc
        if (w, h, dlg.dpi.value()) == (d.width, d.height, d.dpi):
            return
        k = dlg.anchor_factor()
        d.resize(w, h, (w - d.width) * k, (h - d.height) * k)
        d.dpi = dlg.dpi.value()
        self.canvas.fit_view()
        self._after_history_change()
        self.statusBar().showMessage(f"Folha agora com {w} × {h} px (Ctrl+Z desfaz)", 5000)

    def clear_all(self, confirm=True):
        if self.canvas.is_busy() or not self.doc.strokes:
            return
        if confirm:
            r = QMessageBox.question(
                self, APP_NAME, "Apagar todos os traços da folha?\n(Dá para desfazer com Ctrl+Z.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                return
        self.doc.clear()
        self.canvas.invalidate()
        self._on_document_changed()
        self.statusBar().showMessage("Desenho limpo (Ctrl+Z desfaz)", 4000)

    def _maybe_save(self):
        if not (self.doc.modified and self.doc.strokes):
            return True
        r = QMessageBox.question(
            self, APP_NAME, "Salvar as alterações no projeto?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        if r == QMessageBox.StandardButton.Save:
            return self.save_project()
        return r == QMessageBox.StandardButton.Discard

    def _set_document(self, doc, path):
        self.doc = doc
        self.project_path = path
        self.canvas.set_document(doc)
        img = None
        if doc.sketch_path and os.path.exists(doc.sketch_path):
            img = QImage(doc.sketch_path)
        self.canvas.set_sketch(img if img is not None and not img.isNull() else None)
        self._update_sketch_controls()
        self._on_view()
        self._on_document_changed()

    def new_document(self):
        if not self._maybe_save():
            return
        dlg = NewDocumentDialog(self, self.doc)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._set_document(Document(dlg.w.value(), dlg.h.value(), dlg.dpi.value()), None)

    def _last_dir(self):
        return QSettings().value("last_dir", os.path.expanduser("~"))

    def _remember_dir(self, path):
        QSettings().setValue("last_dir", os.path.dirname(path))

    def open_project(self, path=None):
        if not self._maybe_save():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Abrir projeto", self._last_dir(), PROJECT_FILTER)
            if not path:
                return
        try:
            doc = Document.load(path)
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.critical(self, APP_NAME, f"Não foi possível abrir o projeto:\n{e}")
            return
        self._remember_dir(path)
        self._set_document(doc, path)

    def save_project(self, as_new=False):
        path = self.project_path
        if as_new or not path:
            path, _ = QFileDialog.getSaveFileName(self, "Salvar projeto", self._last_dir(), PROJECT_FILTER)
            if not path:
                return False
            if not path.lower().endswith(".traco"):
                path += ".traco"
        try:
            self.doc.save(path)
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f"Não foi possível salvar:\n{e}")
            return False
        self._remember_dir(path)
        self.project_path = path
        self._update_title()
        self.statusBar().showMessage(f"Projeto salvo em {path}", 4000)
        return True

    def load_sketch(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Carregar esboço", self._last_dir(), "Imagens (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)"
        )
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, APP_NAME, "Não foi possível abrir essa imagem.")
            return
        self._remember_dir(path)
        self.doc.sketch_path = path
        if not self.doc.strokes and (img.width(), img.height()) != (self.doc.width, self.doc.height):
            self.doc.width, self.doc.height = img.width(), img.height()
            self.canvas.fit_view()
            self.statusBar().showMessage(
                f"Folha ajustada ao tamanho do esboço: {img.width()} × {img.height()} px", 5000
            )
        self.canvas.set_sketch(img)
        self._update_sketch_controls()

    def remove_sketch(self):
        self.doc.sketch_path = None
        self.canvas.set_sketch(None)
        self._update_sketch_controls()

    def _ask_export_path(self, title, filt, ext):
        base = os.path.splitext(self.project_path)[0] if self.project_path else os.path.join(self._last_dir(), "lineart")
        path, _ = QFileDialog.getSaveFileName(self, title, base + ext, filt)
        if path:
            self._remember_dir(path)
        return path

    def export_both(self):
        if not self.doc.strokes:
            QMessageBox.information(self, APP_NAME, "A folha está vazia: desenhe algo antes de exportar.")
            return
        path = self._ask_export_path("Exportar para o Krita", "PNG (*.png)", ".png")
        if not path:
            return
        base = os.path.splitext(path)[0]
        try:
            export_png(self.doc, base + ".png")
            export_svg(self.doc, base + ".svg")
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f"Falha ao exportar:\n{e}")
            return
        self.canvas.show_toast("Exportado para o Krita")
        self.statusBar().showMessage(f"Exportado: {base}.png e {base}.svg", 8000)

    def export_one(self, kind):
        if kind == "png":
            path = self._ask_export_path("Exportar PNG", "PNG (*.png)", ".png")
        else:
            path = self._ask_export_path("Exportar SVG", "SVG (*.svg)", ".svg")
        if not path:
            return
        try:
            (export_png if kind == "png" else export_svg)(self.doc, path)
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f"Falha ao exportar:\n{e}")
            return
        self.canvas.show_toast("Exportado")
        self.statusBar().showMessage(f"Exportado: {path}", 8000)

    def closeEvent(self, e):
        if not self._maybe_save():
            e.ignore()
            return
        self.wintab.stop()
        self.settings.save()
        diag.log.close()
        e.accept()
