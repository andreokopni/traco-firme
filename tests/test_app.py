"""Teste de ponta a ponta: desenha pelo Canvas como a caneta faria e exporta."""
import math
import os
import random
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from tracofirme.document import Document
from tracofirme.render import export_png, export_svg
from tracofirme.window import MainWindow


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setOrganizationName("TracoFirmeTeste")  # não mexe nas preferências reais
    QSettings().clear()
    QSettings().setValue("guide_seen", True)  # o guia de boas-vindas esperaria um clique
    yield a
    QSettings().clear()


@pytest.fixture
def win(app):
    w = MainWindow()
    w.resize(1200, 900)
    w.show()
    app.processEvents()
    w.canvas.fit_view()
    yield w
    w.doc.modified = False
    w.close()


def draw(canvas, pts, pressure=0.8, hold=False, modifiers=Qt.KeyboardModifier.NoModifier):
    canvas.pen_press(QPointF(*pts[0]), pressure, source="Teste", modifiers=modifiers)
    for p in pts[1:]:
        canvas.pen_move(QPointF(*p), pressure, source="Teste", modifiers=modifiers)
    if hold:
        canvas._on_hold()  # o mesmo que o timer chamaria com a caneta parada
    canvas.pen_release(QPointF(*pts[-1]))


def shaky_line(seed=3):
    rnd = random.Random(seed)
    return [(200 + i * 2 + rnd.uniform(-2, 2), 300 + i * 0.5 + rnd.uniform(-2, 2)) for i in range(200)]


def test_stroke_is_smoothed(win):
    draw(win.canvas, shaky_line())
    assert len(win.doc.strokes) == 1
    pts = win.doc.strokes[0].pts
    # Desvio em relação à reta ideal (em px de tela) deve cair bem abaixo do tremor de ±2 px.
    c = win.canvas
    worst = 0
    for x, y, _ in pts[len(pts) // 5: -len(pts) // 5]:
        sp = c.view().map(QPointF(x, y))
        worst = max(worst, abs((sp.y() - 300) - (sp.x() - 200) * 0.25) / math.hypot(1, 0.25))
    assert worst < 1.0


def test_hold_snaps_to_straight_line(win):
    draw(win.canvas, shaky_line(), hold=True)
    pts = win.doc.strokes[-1].pts
    (ax, ay, _), (bx, by, _) = pts[0], pts[-1]
    for x, y, _ in pts:
        d = abs((bx - ax) * (ay - y) - (ax - x) * (by - ay)) / math.hypot(bx - ax, by - ay)
        assert d < 1e-6


def test_shift_line_and_undo_redo(win):
    draw(win.canvas, [(100, 100), (150, 160), (400, 120)], modifiers=Qt.KeyboardModifier.ShiftModifier)
    assert len(win.doc.strokes) == 1
    win.undo()
    assert win.doc.strokes == []
    win.redo()
    assert len(win.doc.strokes) == 1


def test_partial_eraser_splits(win):
    draw(win.canvas, [(100 + i, 400) for i in range(0, 400, 2)])
    win.settings.tool = "eraser"
    draw(win.canvas, [(300, 380), (300, 420)])
    win.settings.tool = "brush"
    assert len(win.doc.strokes) == 2
    win.undo()
    assert len(win.doc.strokes) == 1


def test_export_and_project_roundtrip(win, tmp_path):
    draw(win.canvas, shaky_line())
    draw(win.canvas, [(300, 200), (300, 260)], pressure=0.3)
    png, svg, proj = tmp_path / "a.png", tmp_path / "a.svg", tmp_path / "a.traco"
    export_png(win.doc, str(png))
    export_svg(win.doc, str(svg))
    img = QImage(str(png))
    assert (img.width(), img.height()) == (win.doc.width, win.doc.height)
    assert img.hasAlphaChannel() and img.pixelColor(0, 0).alpha() == 0
    root = ET.parse(svg).getroot()
    assert root.get("viewBox") == f"0 0 {win.doc.width} {win.doc.height}"
    assert len(root.findall(".//{http://www.w3.org/2000/svg}path")) == 2
    win.doc.save(str(proj))
    doc = Document.load(str(proj))
    assert len(doc.strokes) == 2 and doc.width == win.doc.width


def test_resize_sheet_keeps_drawing_centered_and_undoes(win):
    draw(win.canvas, [(300, 300), (400, 300)])
    doc = win.doc
    w0, h0 = doc.width, doc.height
    x0 = doc.strokes[0].pts[0][0]
    doc.resize(w0 + 200, h0 + 100, 100, 50)
    assert (doc.width, doc.height) == (w0 + 200, h0 + 100)
    assert math.isclose(doc.strokes[0].pts[0][0], x0 + 100)
    win.undo()
    assert (doc.width, doc.height) == (w0, h0)
    assert math.isclose(doc.strokes[0].pts[0][0], x0)
    win.redo()
    assert doc.width == w0 + 200


def test_clear_drawing_is_undoable(win):
    draw(win.canvas, [(300, 300), (400, 300)])
    win.clear_all(confirm=False)
    assert win.doc.strokes == []
    win.undo()
    assert len(win.doc.strokes) == 1


def test_gap_is_closed_when_stroke_ends_near_a_line(win):
    from tracofirme import geometry as geo

    c = win.canvas
    draw(c, [(200 + i * 2, 400) for i in range(150)])        # linha horizontal em y=400
    draw(c, [(300, 250 + i * 2) for i in range(73)])         # vertical que para em y=394 (6 px antes)
    a, b = win.doc.strokes
    ex, ey, er = b.pts[-1]
    dist, i = geo.nearest_point(a.pts, ex, ey)
    assert dist <= (er + a.pts[i][2]) * 0.5 + 1e-6


def test_smoothing_slider_adjusts_last_stroke_and_undo_still_works(win):
    c = win.canvas
    draw(c, shaky_line())
    before = win.doc.strokes[-1]
    win.settings.smoothing = 40
    assert c.resmooth_last()
    after = win.doc.strokes[-1]
    assert after is not before and len(win.doc.strokes) == 1
    win.undo()
    assert win.doc.strokes == []
    assert not c.resmooth_last()  # nada para ajustar depois de desfazer


def test_hold_turns_crooked_square_into_square(win):
    c = win.canvas
    rnd = random.Random(5)
    verts = [(200, 200), (402, 196), (406, 400), (198, 404), (200, 200)]
    pts = []
    for (ax, ay), (bx, by) in zip(verts, verts[1:]):
        pts += [(ax + (bx - ax) * k / 60 + rnd.uniform(-1.5, 1.5), ay + (by - ay) * k / 60 + rnd.uniform(-1.5, 1.5))
                for k in range(60)]
    draw(c, pts, hold=True)
    stroke = win.doc.strokes[-1]
    from tracofirme import geometry as geo
    assert len(geo.outline(stroke.pts)) == 4  # quatro lados com quinas vivas
