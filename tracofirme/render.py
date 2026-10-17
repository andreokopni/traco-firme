"""Conversão de traços em QPainterPath e exportação PNG/SVG."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPolygonF

from . import geometry as geo
from .curvefit import fit_closed

SVG_TOLERANCE = 0.15  # px do documento; o contorno vira curvas Bézier dentro disso


def polygons_path(polys):
    """Um caminho com todos os pedaços do contorno; a regra 'winding' (nonzero) une
    as partes sobrepostas, já que todas têm a mesma orientação."""
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    for poly in polys:
        if len(poly) >= 3:
            path.addPolygon(QPolygonF([QPointF(x, y) for x, y in poly]))
            path.closeSubpath()
    return path


def stroke_path(stroke):
    if stroke.qpath is None:
        stroke.qpath = polygons_path(stroke.outline)
    return stroke.qpath


def points_path(pts):
    return polygons_path(geo.outline(pts))


def export_png(doc, path):
    """Lineart com fundo transparente no tamanho do documento, com DPI gravado."""
    img = QImage(doc.width, doc.height, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    dpm = round(doc.dpi / 0.0254)
    img.setDotsPerMeterX(dpm)
    img.setDotsPerMeterY(dpm)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    for s in doc.strokes:
        p.fillPath(stroke_path(s), QColor(s.color))
    p.end()
    if not img.save(path, "PNG"):
        raise OSError(f"Não foi possível gravar {path}")


def _svg_subpath(poly):
    curves = fit_closed(geo.simplify(poly, SVG_TOLERANCE / 4), SVG_TOLERANCE)
    if not curves:
        return ""
    parts = [f"M{curves[0][0][0]:.2f} {curves[0][0][1]:.2f}"]
    for b in curves:
        parts.append(
            f"C{b[1][0]:.2f} {b[1][1]:.2f} {b[2][0]:.2f} {b[2][1]:.2f} {b[3][0]:.2f} {b[3][1]:.2f}"
        )
    parts.append("Z")
    return "".join(parts)


def export_svg(doc, path):
    """Cada traço vira um caminho preenchido feito de curvas Bézier. O tamanho físico
    (polegadas) usa o DPI do documento, para o Krita encaixar o vetor sobre o PNG."""
    w_in = doc.width / doc.dpi
    h_in = doc.height / doc.dpi
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w_in:.4f}in" height="{h_in:.4f}in" '
        f'viewBox="0 0 {doc.width} {doc.height}">',
        '<g id="lineart" fill-rule="nonzero" stroke="none">',
    ]
    for s in doc.strokes:
        d = "".join(_svg_subpath(poly) for poly in s.outline if len(poly) >= 3)
        if d:
            out.append(f'<path fill="{s.color}" d="{d}"/>')
    out.append("</g>")
    out.append("</svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
