import math

import pytest
from helpers import arc_pts, ellipse_pts, line_pts, noisy, polygon_pts

from tracofirme import shapes


def name_of(pts, **kw):
    s = shapes.detect_shape(pts, **kw)
    return s and shapes.shape_name(s)


def test_detect_line():
    assert shapes.detect_shape(noisy(line_pts(), 3.0))["kind"] == "line"


@pytest.mark.parametrize("bow", [0.03, 0.06, 0.08])
def test_hand_drawn_line_with_belly_is_still_a_line(bow):
    length = 300
    pts = noisy([(x, bow * length * 4 * (x / length) * (1 - x / length), 1) for x in range(0, length + 1, 2)], 1.5)
    assert name_of(pts) == "reta"


def test_detect_arc_and_circle():
    arc = shapes.detect_shape(noisy(arc_pts(120), 2.0))
    assert arc["kind"] == "arc" and abs(abs(math.degrees(arc["sweep"])) - 120) < 10
    assert abs(arc["r"] - 150) < 5
    assert name_of(noisy(arc_pts(345), 2.0)) == "círculo"


def test_s_curve_is_not_snapped():
    pts = [(x, math.sin(x / 400 * 2 * math.pi) * 60, 3.0) for x in range(0, 400, 2)]
    assert shapes.detect_shape(pts) is None


def test_ellipse():
    s = shapes.detect_shape(noisy(ellipse_pts(200, 90, 0.5), 2.0))
    assert s["kind"] == "ellipse"
    assert abs(s["a"] - 200) < 8 and abs(s["b"] - 90) < 8
    assert abs(math.degrees(s["rot"]) % 180 - 28.6) < 4


def test_crooked_square_becomes_square_aligned_to_screen():
    s = shapes.detect_shape(noisy(polygon_pts([(100, 100), (305, 92), (312, 300), (96, 310)]), 2.0))
    assert shapes.shape_name(s) == "quadrado"
    xs = sorted({round(x, 6) for x, _ in s["pts"]})
    ys = sorted({round(y, 6) for _, y in s["pts"]})
    assert len(xs) == 2 and len(ys) == 2  # lados exatamente horizontais/verticais
    assert math.isclose(xs[1] - xs[0], ys[1] - ys[0], abs_tol=1e-4)


def test_square_follows_rotated_view():
    """Com a tela girada, "alinhado" é em relação à tela, não à folha."""
    rot = math.radians(30)

    def r(p):
        return (p[0] * math.cos(rot) - p[1] * math.sin(rot), p[0] * math.sin(rot) + p[1] * math.cos(rot))

    verts = [r(p) for p in [(0, 0), (200, 6), (204, 200), (-4, 205)]]
    s = shapes.detect_shape(noisy(polygon_pts(verts), 1.5), axis_angle=rot)
    assert shapes.shape_name(s) == "quadrado"
    (x0, y0), (x1, y1) = s["pts"][0], s["pts"][1]
    assert abs(math.degrees(math.atan2(y1 - y0, x1 - x0)) % 90 - 30) < 1e-6


@pytest.mark.parametrize("verts,expected", [
    ([(100, 100), (400, 108), (395, 260), (103, 252)], "retângulo"),
    ([(100, 300), (250, 80), (400, 310)], "triângulo"),
    ([(250, 60), (420, 180), (360, 380), (140, 380), (80, 180)], "polígono de 5 lados"),
])
def test_polygons(verts, expected):
    assert name_of(noisy(polygon_pts(verts), 2.0)) == expected


def test_open_polyline():
    assert name_of(noisy(polygon_pts([(100, 300), (250, 100), (400, 300)], closed=False), 2.0)) == "linha quebrada"


def test_update_shape_end_and_build():
    shape = shapes.detect_shape(arc_pts(90))
    shape = shapes.update_shape_end(shape, -150.0, 0.0)  # arrasta a ponta para 180°
    assert abs(math.degrees(shape["sweep"]) - 180) < 1
    pts = shapes.build_shape(shape, [1.0, 3.0], 1.0)
    assert pts[0][2] == 1.0 and abs(pts[-1][2] - 3.0) < 1e-9
    assert all(abs(math.hypot(x - shape["c"][0], y - shape["c"][1]) - shape["r"]) < 1e-6 for x, y, _ in pts)


def test_build_closed_polygon_includes_exact_corners():
    shape = {"kind": "poly", "pts": [(0, 0), (100, 0), (100, 100), (0, 100)], "closed": True}
    pts = shapes.build_shape(shape, [2.0], 1.5)
    xy = {(round(x, 9), round(y, 9)) for x, y, _ in pts}
    assert {(0, 0), (100, 0), (100, 100), (0, 100)} <= xy
    assert pts[0][:2] == pts[-1][:2]


def test_snap_angle():
    x, y = shapes.snap_angle((0, 0), (100, 9))
    assert abs(y) < 1e-9 and abs(x - math.hypot(100, 9)) < 1e-9


def rounded_square(side=200.0, radius=16.0, step=2.0, start=(100.0, 100.0)):
    """Quadrado com quinas arredondadas, como sai à mão."""
    x0, y0 = start
    pts = []
    corners = [(x0 + side - radius, y0 + radius, -90), (x0 + side - radius, y0 + side - radius, 0),
               (x0 + radius, y0 + side - radius, 90), (x0 + radius, y0 + radius, 180)]
    for cx, cy, a0 in corners:
        for k in range(0, 91, 6):
            a = math.radians(a0 + k)
            pts.append((cx + math.cos(a) * radius, cy + math.sin(a) * radius, 3.0))
    pts.append(pts[0])
    from tracofirme.geometry import resample
    return resample(pts, step)


def test_hand_drawn_square_with_rounded_corners():
    assert name_of(noisy(rounded_square(), 1.5)) == "quadrado"
