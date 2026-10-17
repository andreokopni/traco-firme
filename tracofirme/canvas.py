"""Área de desenho: entrada da caneta, estabilização, formas, borracha e vista."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPointingDevice, QTransform
from PySide6.QtWidgets import QWidget

from . import geometry as geo
from . import shapes
from .diag import log
from .document import Stroke
from .filters import for_strength
from .render import points_path, stroke_path

BG = QColor("#3a3a3a")
PAPER = QColor("#ffffff")
HOLD_MOVE_TOL = 8.0       # px de tela que ainda contam como "caneta parada"
HOLD_RING_DELAY = 0.15    # s parado antes de mostrar o anel de progresso
HOLD_COLOR = QColor(40, 140, 255)
HOLD_FAIL_COLOR = QColor(230, 80, 60)
TABLET_MOUSE_GUARD = 0.3  # s em que eventos de mouse são ignorados após eventos da mesa
PRESSURE_EMA = 0.35
MIN_ZOOM, MAX_ZOOM = 0.05, 32.0
CORNER_SCALE_PX = 10.0    # janela (px de tela) para achar cantos vivos
TAPER_SIZES = 4.0         # comprimento das pontas finas, em múltiplos do tamanho do pincel
TOAST_SECONDS = 1.4


class _Live:
    """Estado do traço em andamento (coordenadas de tela para o estabilizador)."""

    def __init__(self, pos: QPointF, pressure: float, filt):
        self.raw = pos
        self.anchor = (pos.x(), pos.y())
        self.last_emit = self.anchor
        self.hold_pos = pos
        self.hold_t = time.monotonic()
        self.hold_failed = False
        self.pressure = pressure
        self.filt = filt
        self.pts = []        # (x, y, r) estabilizados, no documento: o traço que aparece
        self.raw_pts = []    # (x, y, r) da caneta sem filtro: usados para reconhecer formas
        self.profile = []    # raios usados quando o traço vira forma
        self.shape = None
        self.from_shift = False


class Canvas(QWidget):
    statusMessage = Signal(str)
    inputChanged = Signal(str, float)  # origem, pressão
    viewChanged = Signal()
    documentChanged = Signal()

    def __init__(self, doc, settings, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.settings = settings
        self.sketch: QImage | None = None
        self.wintab_mode = False
        self.zoom = 1.0
        self.angle = 0.0
        self.offset = QPointF(0, 0)
        self._fitted = False

        self._cache: QImage | None = None
        self._cache_view: QTransform | None = None
        self._cache_ok = False
        self._rerender_timer = QTimer(self, singleShot=True, interval=150)
        self._rerender_timer.timeout.connect(self._rerender)

        self._hold_timer = QTimer(self, singleShot=True)
        self._hold_timer.timeout.connect(self._on_hold)
        self._ring_timer = QTimer(self, interval=30)  # anima o anel de "segurar"
        self._ring_timer.timeout.connect(self._ring_tick)
        self._resmooth_timer = QTimer(self, singleShot=True, interval=80)
        self._resmooth_timer.timeout.connect(self.resmooth_last)
        self._toast_timer = QTimer(self, singleShot=True)
        self._toast_timer.timeout.connect(self._hide_toast)

        self._live: _Live | None = None
        self._last_free = None  # último traço à mão livre, para poder alisar de novo
        self._erase = None
        self._pan_last: QPointF | None = None
        self._source: str | None = None
        self._space = False
        self._hover: QPointF | None = None
        self._hover_eraser = False
        self._last_tablet = 0.0
        self._last_info = 0.0
        self._toast: tuple[str, bool] | None = None

        self.setTabletTracking(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # --- Documento e vista ---------------------------------------------------------

    def set_document(self, doc):
        self.doc = doc
        self._live = None
        self._erase = None
        self._last_free = None
        self.fit_view()
        self.invalidate()

    def set_sketch(self, img: QImage | None):
        self.sketch = img
        self.invalidate()

    def invalidate(self):
        self._cache_ok = False
        self.update()

    def view(self) -> QTransform:
        t = QTransform()
        t.translate(self.offset.x(), self.offset.y())
        t.rotate(self.angle)
        t.scale(self.zoom, self.zoom)
        return t

    def to_doc(self, pos: QPointF):
        p = self.view().inverted()[0].map(pos)
        return p.x(), p.y()

    def _keep_point(self, doc_pt, widget_pt: QPointF):
        self.offset += widget_pt - self.view().map(QPointF(*doc_pt))
        self.viewChanged.emit()
        self.update()

    def fit_view(self):
        w, h = max(1, self.width()), max(1, self.height())
        self.angle = 0.0
        self.zoom = max(MIN_ZOOM, min((w - 40) / self.doc.width, (h - 40) / self.doc.height))
        self.offset = QPointF((w - self.doc.width * self.zoom) / 2, (h - self.doc.height * self.zoom) / 2)
        self.viewChanged.emit()
        self.update()

    def zoom_at(self, pos: QPointF, factor: float):
        doc_pt = self.to_doc(pos)
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * factor))
        self._keep_point(doc_pt, pos)

    def zoom_by(self, factor):
        self.zoom_at(QPointF(self.width() / 2, self.height() / 2), factor)

    def rotate_by(self, deg):
        center = QPointF(self.width() / 2, self.height() / 2)
        doc_pt = self.to_doc(center)
        self.angle = (self.angle + deg) % 360
        self._keep_point(doc_pt, center)

    def reset_rotation(self):
        self.rotate_by(-self.angle)

    def show_toast(self, text, ok=True):
        """Aviso curto no rodapé da área de desenho."""
        self._toast = (text, ok)
        self._toast_timer.start(int(TOAST_SECONDS * 1000))
        self.update()

    def _hide_toast(self):
        self._toast = None
        self.update()

    # --- Entrada genérica (Windows Ink, WinTab e mouse chegam aqui) -----------------

    def is_busy(self):
        return self._live is not None or self._erase is not None or self._pan_last is not None

    def _report(self, source, pressure, force=False):
        now = time.monotonic()
        if force or now - self._last_info > 0.05:
            self._last_info = now
            self.inputChanged.emit(source, pressure)

    def pen_press(self, pos, pressure, *, eraser=False, source="Mouse", pan=False, modifiers=None):
        if self.is_busy():
            return
        modifiers = modifiers if modifiers is not None else Qt.KeyboardModifier.NoModifier
        self._source = source
        self._hover = pos
        self._hover_eraser = eraser
        self._report(source, pressure, force=True)
        if pan or self._space:
            self._pan_last = pos
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif eraser or self.settings.tool == "eraser":
            self._begin_erase(pos)
        else:
            self._begin_stroke(pos, pressure, modifiers)

    def pen_move(self, pos, pressure, *, modifiers=None, source="Mouse"):
        modifiers = modifiers if modifiers is not None else Qt.KeyboardModifier.NoModifier
        self._hover = pos
        self._report(source, pressure)
        if self._pan_last is not None:
            self.offset += pos - self._pan_last
            self._pan_last = pos
            self.viewChanged.emit()
            self.update()
        elif self._erase is not None:
            self._erase_move(pos)
        elif self._live is not None:
            self._move_stroke(pos, pressure, modifiers)
        else:
            self.update()

    def pen_release(self, pos):
        if self._pan_last is not None:
            self._pan_last = None
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._space else Qt.CursorShape.CrossCursor)
        elif self._erase is not None:
            self._end_erase()
        elif self._live is not None:
            self._end_stroke()
        self._source = None
        self.update()

    def pen_hover(self, pos, *, eraser=False, source="Mouse", pressure=0.0):
        self._hover = pos
        self._hover_eraser = eraser
        self._report(source, pressure)
        self.update()

    def pen_leave(self):
        self._hover = None
        self.update()

    # --- Traço ---------------------------------------------------------------------

    def _radius(self, pressure):
        s = self.settings
        p = min(max(pressure, 0.0), 1.0)
        f = s.min_ratio + (1.0 - s.min_ratio) * p ** s.gamma
        return max(0.25, s.size * 0.5 * f)

    @staticmethod
    def _spacing_for(zoom):
        return min(1.5, 1.5 / zoom)

    def _begin_stroke(self, pos, pressure, modifiers):
        live = _Live(pos, pressure, for_strength(self.settings.stab_level))
        x, y = self.to_doc(pos)
        r = self._radius(pressure)
        live.pts.append((x, y, r))
        live.raw_pts.append((x, y, r))
        live.profile.append(r)
        s = self.settings
        log.event("stroke_begin", x=pos.x(), y=pos.y(), p=pressure, zoom=self.zoom, stab=s.stab_level,
                  smoothing=s.smoothing, hold_snap=s.hold_snap, hold_ms=s.hold_ms,
                  shift=bool(modifiers & Qt.KeyboardModifier.ShiftModifier))
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            live.shape = {"kind": "line", "a": (x, y), "b": (x, y)}
            live.from_shift = True
        elif s.hold_snap:
            self._hold_timer.start(s.hold_ms)
            self._ring_timer.start()
        if live.filt is not None:
            live.filt(time.monotonic(), pos.x(), pos.y())
        self._live = live
        self.update()

    def _move_stroke(self, pos, pressure, modifiers):
        live = self._live
        live.raw = pos
        live.pressure += (pressure - live.pressure) * PRESSURE_EMA
        r = self._radius(live.pressure)

        if live.shape is not None:
            if live.from_shift:
                live.profile.append(r)
            x, y = self.to_doc(pos)
            if live.shape["kind"] == "line" and modifiers & Qt.KeyboardModifier.ControlModifier:
                x, y = shapes.snap_angle(live.shape["a"], (x, y))
            live.shape = shapes.update_shape_end(live.shape, x, y)
            self.update()
            return

        dx_raw, dy_raw = self.to_doc(pos)
        last = live.raw_pts[-1]
        if math.hypot(dx_raw - last[0], dy_raw - last[1]) * self.zoom >= 0.5:
            live.raw_pts.append((dx_raw, dy_raw, r))

        # 1) filtro 1€: tira o tremor quando a mão vai devagar, sem atrasar quando vai rápido;
        # 2) corda puxada: a ponta só anda quando a caneta se afasta mais que a corda.
        fx, fy = live.filt(time.monotonic(), pos.x(), pos.y()) if live.filt else (pos.x(), pos.y())
        cord = self.settings.cord_px()
        ax, ay = live.anchor
        dx, dy = fx - ax, fy - ay
        d = math.hypot(dx, dy)
        if cord <= 0:
            ax, ay = fx, fy
        elif d > cord:
            k = (d - cord) / d
            ax, ay = ax + dx * k, ay + dy * k
        live.anchor = (ax, ay)
        lx, ly = live.last_emit
        if math.hypot(ax - lx, ay - ly) >= 0.5:
            live.last_emit = (ax, ay)
            x, y = self.to_doc(QPointF(ax, ay))
            live.pts.append((x, y, r))

        hp = live.hold_pos
        moved = math.hypot(pos.x() - hp.x(), pos.y() - hp.y())
        if moved > HOLD_MOVE_TOL:
            still_ms = (time.monotonic() - live.hold_t) * 1000
            if still_ms > 150:  # só interessa quando a pessoa parecia estar segurando
                log.event("hold_reset", moved=moved, still_ms=still_ms)
            live.hold_pos = pos
            live.hold_t = time.monotonic()
            live.hold_failed = False
            if self.settings.hold_snap:
                self._hold_timer.start(self.settings.hold_ms)
        self.update()

    def _ring_tick(self):
        live = self._live
        if live is None or live.shape is not None:
            self._ring_timer.stop()
        elif time.monotonic() - live.hold_t > HOLD_RING_DELAY:
            self.update()

    def _on_hold(self):
        live = self._live
        if live is None or live.shape is not None:
            return
        x, y = self.to_doc(live.raw)
        pts = live.raw_pts + [(x, y, live.raw_pts[-1][2])]
        unit = 1.0 / self.zoom
        shape = shapes.detect_shape(pts, unit=unit, axis_angle=-math.radians(self.angle))
        log.event("hold_fire", result=shapes.shape_name(shape) if shape else None,
                  **shapes.shape_metrics(pts, unit))
        if shape is None:
            live.hold_failed = True
            self.show_toast("Não reconheci a forma — solte para manter o traço", ok=False)
            self.update()
            return
        live.shape = shape
        live.profile = [p[2] for p in live.pts]
        name = shapes.shape_name(shape)
        hint = "" if shapes.is_closed(shape) else " — continue movendo para ajustar a ponta"
        self.show_toast(name[:1].upper() + name[1:])
        self.statusMessage.emit(f"Endireitado: {name}{hint}")
        self.update()

    def _end_stroke(self):
        live = self._live
        self._live = None
        self._hold_timer.stop()
        self._ring_timer.stop()
        log.event("stroke_end", x=live.raw.x(), y=live.raw.y(),
                  shape=shapes.shape_name(live.shape) if live.shape else None,
                  still_ms=(time.monotonic() - live.hold_t) * 1000, n=len(live.pts))
        log.flush()
        raw = None
        if live.shape is not None:
            shape = self._snap_shape_ends(live.shape) if self.settings.close_gaps else live.shape
            pts = shapes.build_shape(shape, live.profile, self._spacing_for(self.zoom))
        else:
            raw = list(live.pts)
            if self.settings.finish_to_tip:
                x, y = self.to_doc(live.raw)
                raw.append((x, y, self._radius(live.pressure)))
            pts = self._process_free(raw, self.zoom)
        if not pts:
            return
        stroke = Stroke(pts, self.settings.color)
        self.doc.add_stroke(stroke)
        self._last_free = {"stroke": stroke, "raw": raw, "zoom": self.zoom} if raw else None
        self._paint_into_cache(stroke)
        self.documentChanged.emit()

    def _process_free(self, raw, zoom, exclude=None):
        """Suaviza um traço à mão livre, emenda nas linhas próximas e afina as pontas."""
        s = self.settings
        spacing = self._spacing_for(zoom)
        sigma = s.smoothing / zoom / spacing
        fit_tol = (0.4 + s.smoothing * 0.08) / zoom if s.smoothing > 0 else 0.0
        corner_k = int(round(CORNER_SCALE_PX / zoom / spacing)) if s.keep_corners else 0
        pts = geo.process_free(raw, spacing, sigma, fit_tol, corner_k)
        snapped = (False, False)
        if s.close_gaps:
            pts, snapped = self._close_gaps(pts, zoom, spacing, exclude)
        if s.taper and len(pts) > 2:
            length = s.size * TAPER_SIZES
            pts = geo.taper(pts, 0 if snapped[0] else length, 0 if snapped[1] else length)
        return pts

    # --- Fechar falhas (emendar pontas em linhas próximas) ------------------------------

    def _gap_target(self, x, y, zoom, exclude=None):
        """Ponto mais próximo de outro traço dentro da distância de emenda, ou None."""
        d = self.settings.gap_px / zoom
        best = None
        for st in self.doc.strokes:
            if st is exclude:
                continue
            x0, y0, x1, y1 = st.bbox
            if x < x0 - d or x > x1 + d or y < y0 - d or y > y1 + d:
                continue
            dist, i = geo.nearest_point(st.pts, x, y)
            if dist <= d and (best is None or dist < best[0]):
                best = (dist, st.pts[i], st)
        return best

    def _close_gaps(self, pts, zoom, spacing, exclude):
        if len(pts) < 2:
            return pts, (False, False)
        d = self.settings.gap_px / zoom
        length = geo.path_length(pts)
        targets = [self._gap_target(pts[0][0], pts[0][1], zoom, exclude),
                   self._gap_target(pts[-1][0], pts[-1][1], zoom, exclude)]
        sx, sy = pts[0][0], pts[0][1]
        ex, ey = pts[-1][0], pts[-1][1]
        if targets[1] is None and length > 4 * d and math.hypot(ex - sx, ey - sy) <= d:
            targets[1] = (math.hypot(ex - sx, ey - sy), pts[0], None)  # fecha o próprio contorno
        snapped = [False, False]
        out = list(pts)
        for end, target in ((0, targets[0]), (1, targets[1])):
            if target is None:
                continue
            dist, q, other = target
            tip = out[0] if end == 0 else out[-1]
            snapped[end] = True
            if dist <= (tip[2] + q[2]) * 0.5:
                continue  # já encosta
            if other is not None and self._end_touches(out, end, other, d):
                continue  # o traço já cruzou a outra linha perto da ponta
            link = geo.bridge(tip, q, spacing)
            out = list(reversed(link)) + out if end == 0 else out + link
        return out, tuple(snapped)

    @staticmethod
    def _end_touches(pts, end, other, d):
        """O trecho final (comprimento d) do traço já encosta em `other`?"""
        seq = pts if end == 0 else pts[::-1]
        walked = 0.0
        for i, p in enumerate(seq):
            if i:
                walked += math.hypot(p[0] - seq[i - 1][0], p[1] - seq[i - 1][1])
            if walked > d:
                break
            dist, j = geo.nearest_point(other.pts, p[0], p[1])
            if dist <= (p[2] + other.pts[j][2]) * 0.5:
                return True
        return False

    def _snap_shape_ends(self, shape):
        """Emenda as pontas de retas e linhas quebradas em linhas próximas."""
        if shape["kind"] == "line":
            ends = [shape["a"], shape["b"]]
        elif shape["kind"] == "poly" and not shape["closed"]:
            ends = [shape["pts"][0], shape["pts"][-1]]
        else:
            return shape
        new = []
        for x, y in ends:
            t = self._gap_target(x, y, self.zoom)
            new.append((t[1][0], t[1][1]) if t else (x, y))
        if shape["kind"] == "line":
            return {**shape, "a": new[0], "b": new[1]}
        return {**shape, "pts": [new[0]] + shape["pts"][1:-1] + [new[1]]}

    # --- Alisar de novo o último traço ---------------------------------------------------

    def schedule_resmooth(self):
        self._resmooth_timer.start()

    def resmooth_last(self):
        """Refaz o último traço à mão livre com os ajustes atuais (suavidade, pontas...)."""
        lf = self._last_free
        if lf is None or self.is_busy() or not self.doc.strokes or self.doc.strokes[-1] is not lf["stroke"]:
            return False
        pts = self._process_free(lf["raw"], lf["zoom"], exclude=lf["stroke"])
        if not pts:
            return False
        new = Stroke(pts, lf["stroke"].color)
        self.doc.strokes[-1] = new
        self.doc.modified = True
        lf["stroke"] = new
        self.invalidate()
        return True

    def has_adjustable_stroke(self):
        lf = self._last_free
        return lf is not None and bool(self.doc.strokes) and self.doc.strokes[-1] is lf["stroke"]

    def _live_path(self):
        live = self._live
        if live.shape is not None:
            spacing = max(self._spacing_for(self.zoom), 2.0 / self.zoom)
            return points_path(shapes.build_shape(live.shape, live.profile, spacing))
        return points_path(live.pts)

    # --- Borracha ------------------------------------------------------------------

    def _begin_erase(self, pos):
        p = self.to_doc(pos)
        self._erase = {"before": list(self.doc.strokes), "changed": False, "last": p}
        self._erase_at(*p)

    def _erase_move(self, pos):
        cx, cy = self.to_doc(pos)
        lx, ly = self._erase["last"]
        er = self.settings.eraser_size / 2
        steps = max(1, int(math.ceil(math.hypot(cx - lx, cy - ly) / max(er * 0.5, 0.5))))
        for i in range(1, steps + 1):
            t = i / steps
            self._erase_at(lx + (cx - lx) * t, ly + (cy - ly) * t)
        self._erase["last"] = (cx, cy)
        self.update()

    def _erase_at(self, cx, cy):
        er = self.settings.eraser_size / 2
        whole = self.settings.eraser_mode == "stroke"
        new, changed = [], False
        for s in self.doc.strokes:
            x0, y0, x1, y1 = s.bbox
            if cx + er < x0 or cx - er > x1 or cy + er < y0 or cy - er > y1:
                new.append(s)
                continue
            if whole:
                if geo.stroke_hit(s.pts, cx, cy, er):
                    changed = True
                else:
                    new.append(s)
                continue
            pieces = geo.erase(s.pts, cx, cy, er)
            if pieces is None:
                new.append(s)
            else:
                changed = True
                new.extend(Stroke(p, s.color) for p in pieces)
        if changed:
            self.doc.strokes = new
            self._erase["changed"] = True
            self._cache_ok = False

    def _end_erase(self):
        if self._erase["changed"]:
            self.doc.checkpoint(self._erase["before"])
            self.documentChanged.emit()
        self._erase = None

    # --- Desenho na tela -----------------------------------------------------------

    def _rerender(self):
        self._render_cache()
        self.update()

    def _render_cache(self):
        dpr = self.devicePixelRatioF()
        img = QImage(
            max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        v = self.view()
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setTransform(v)
        page = QRectF(0, 0, self.doc.width, self.doc.height)
        p.fillRect(page, PAPER)
        if self.sketch is not None and not self.sketch.isNull():
            p.setOpacity(self.settings.sketch_opacity)
            p.drawImage(self._sketch_rect(), self.sketch)
            p.setOpacity(1.0)
        visible = v.inverted()[0].mapRect(QRectF(self.rect()))
        p.setPen(Qt.PenStyle.NoPen)
        for s in self.doc.strokes:
            x0, y0, x1, y1 = s.bbox
            if x1 < visible.left() or x0 > visible.right() or y1 < visible.top() or y0 > visible.bottom():
                continue
            p.fillPath(stroke_path(s), QColor(s.color))
        p.end()
        self._cache = img
        self._cache_view = v
        self._cache_ok = True

    def _sketch_rect(self):
        iw, ih = self.sketch.width(), self.sketch.height()
        k = min(self.doc.width / iw, self.doc.height / ih)
        w, h = iw * k, ih * k
        return QRectF((self.doc.width - w) / 2, (self.doc.height - h) / 2, w, h)

    def _paint_into_cache(self, stroke):
        if self._cache_ok and self._cache_view == self.view():
            p = QPainter(self._cache)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setTransform(self.view())
            p.fillPath(stroke_path(stroke), QColor(stroke.color))
            p.end()
        else:
            self._cache_ok = False
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), BG)
        v = self.view()
        if not self._cache_ok or self._cache is None:
            self._render_cache()
        if self._cache_view == v:
            p.drawImage(QPointF(0, 0), self._cache)
        else:
            # Durante pan/zoom desenha a imagem anterior transformada e refaz em seguida.
            p.setTransform(self._cache_view.inverted()[0] * v)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(QPointF(0, 0), self._cache)
            p.resetTransform()
            self._rerender_timer.start()

        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        live = self._live
        if live is not None:
            p.setTransform(v)
            p.fillPath(self._live_path(), QColor(self.settings.color))
            p.resetTransform()
            if live.shape is None and self.settings.cord_px() > 0:
                p.setPen(QPen(QColor(230, 80, 60, 200), 1))
                p.drawLine(QPointF(*live.anchor), live.raw)
                p.setBrush(QColor(230, 80, 60, 200))
                p.drawEllipse(QPointF(*live.anchor), 2.5, 2.5)
                p.setBrush(Qt.BrushStyle.NoBrush)
            if live.shape is None and self.settings.hold_snap:
                self._paint_hold_ring(p, live)

        if self._hover is not None and self._pan_last is None:
            eraser = self._hover_eraser or self.settings.tool == "eraser"
            size = self.settings.eraser_size if eraser else self.settings.size
            r = max(2.0, size / 2 * self.zoom)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(0, 0, 0, 160), 1))
            p.drawEllipse(self._hover, r + 1, r + 1)
            p.setPen(QPen(QColor(255, 255, 255, 200), 1, Qt.PenStyle.DashLine if eraser else Qt.PenStyle.SolidLine))
            p.drawEllipse(self._hover, r, r)
        if self._toast is not None:
            self._paint_toast(p)
        p.end()

    def _paint_hold_ring(self, p, live):
        """Anel que enche enquanto a caneta está parada; vermelho se não reconheceu."""
        still = time.monotonic() - live.hold_t
        if still < HOLD_RING_DELAY:
            return
        frac = min(1.0, still * 1000 / max(1, self.settings.hold_ms))
        rect = QRectF(live.raw.x() - 16, live.raw.y() - 16, 32, 32)
        color = HOLD_FAIL_COLOR if live.hold_failed else HOLD_COLOR
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 180), 5))
        p.drawArc(rect, 90 * 16, -int(frac * 360 * 16))
        p.setPen(QPen(color, 3))
        p.drawArc(rect, 90 * 16, -int(frac * 360 * 16))

    def _paint_toast(self, p):
        text, ok = self._toast
        font = QFont(self.font())
        font.setPointSizeF(font.pointSizeF() * 1.25)
        font.setBold(True)
        p.setFont(font)
        label = ("✓  " if ok else "") + text
        w = p.fontMetrics().horizontalAdvance(label) + 36
        h = p.fontMetrics().height() + 18
        rect = QRectF((self.width() - w) / 2, self.height() - h - 28, w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, h / 2, h / 2)
        p.fillPath(path, QColor(32, 120, 230, 235) if ok else QColor(200, 70, 50, 235))
        p.setPen(QColor("white"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def resizeEvent(self, event):
        if not self._fitted and self.width() > 50:
            self._fitted = True
            self.fit_view()
        self.invalidate()

    # --- Eventos Qt ----------------------------------------------------------------

    def tabletEvent(self, e):
        e.accept()  # evita que o Qt gere eventos de mouse duplicados
        pos = e.position()
        pressure = e.pressure()
        eraser = e.pointerType() == QPointingDevice.PointerType.Eraser
        t = e.type()
        if log.enabled:
            kind = {QEvent.Type.TabletPress: "ink_press", QEvent.Type.TabletRelease: "ink_release"}.get(
                t, "ink_move" if self.is_busy() else "ink_hover")
            log.event(kind, x=pos.x(), y=pos.y(), p=pressure, ptr=e.pointerType().name,
                      btn=e.buttons().value, ignored=self.wintab_mode)
        if self.wintab_mode:
            return
        self._last_tablet = time.monotonic()
        if t == QEvent.Type.TabletPress:
            barrel = bool(e.buttons() & (Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton))
            self.pen_press(pos, pressure, eraser=eraser, source="Windows Ink", pan=barrel, modifiers=e.modifiers())
        elif t == QEvent.Type.TabletMove:
            if self.is_busy():
                if self._source == "Windows Ink":
                    self.pen_move(pos, pressure, modifiers=e.modifiers(), source="Windows Ink")
            else:
                self.pen_hover(pos, eraser=eraser, source="Windows Ink", pressure=pressure)
        elif t == QEvent.Type.TabletRelease:
            if self._source == "Windows Ink":
                self.pen_release(pos)

    def mark_tablet_activity(self):
        self._last_tablet = time.monotonic()

    def _mouse_blocked(self):
        return time.monotonic() - self._last_tablet < TABLET_MOUSE_GUARD

    def _log_mouse(self, kind, e):
        if log.enabled:
            log.event(kind, x=e.position().x(), y=e.position().y(), btn=e.buttons().value,
                      blocked=self._mouse_blocked(), synth=e.source().name)

    def mousePressEvent(self, e):
        self._log_mouse("mouse_press", e)
        if self._mouse_blocked() or self.is_busy():
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self.pen_press(e.position(), 1.0, source="Mouse", modifiers=e.modifiers())
        elif e.button() == Qt.MouseButton.MiddleButton:
            self.pen_press(e.position(), 1.0, source="Mouse", pan=True)

    def mouseMoveEvent(self, e):
        self._log_mouse("mouse_move" if self._source == "Mouse" else "mouse_hover", e)
        if self._source == "Mouse":
            self.pen_move(e.position(), 1.0, modifiers=e.modifiers(), source="Mouse")
        elif not self.is_busy() and not self._mouse_blocked():
            self.pen_hover(e.position(), source="Mouse", pressure=0.0)

    def mouseReleaseEvent(self, e):
        self._log_mouse("mouse_release", e)
        if self._source == "Mouse":
            self.pen_release(e.position())

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if steps:
            self.zoom_at(e.position(), 1.15 ** steps)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat():
            self._space = True
            if not self.is_busy():
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat():
            self._space = False
            if self._pan_last is None:
                self.setCursor(Qt.CursorShape.CrossCursor)
            return
        super().keyReleaseEvent(e)

    def enterEvent(self, e):
        self.setFocus()

    def leaveEvent(self, e):
        self.pen_leave()
