import math

from helpers import line_pts, noisy

from tracofirme import geometry as geo


def test_resample_spacing_and_endpoints():
    pts = [(0, 0, 1), (10, 0, 1), (10, 10, 3)]
    out = geo.resample(pts, 1.0)
    assert out[0] == pts[0] and out[-1] == pts[-1]
    gaps = [math.hypot(out[i][0] - out[i - 1][0], out[i][1] - out[i - 1][1]) for i in range(1, len(out) - 1)]
    assert all(0.7 < g <= 1.0001 for g in gaps)


def test_smooth_keeps_endpoints_and_removes_jitter():
    pts = noisy(line_pts(), 2.0)
    out = geo.smooth(pts, 6)
    for a, b in ((out[0], pts[0]), (out[-1], pts[-1])):
        assert math.isclose(a[0], b[0], abs_tol=1e-9) and math.isclose(a[1], b[1], abs_tol=1e-9)
    mid_raw = max(abs(p[1]) for p in pts[40:160])
    mid_smooth = max(abs(p[1]) for p in out[40:160])
    assert mid_smooth < mid_raw * 0.4


def test_outline_is_closed_polygon_around_stroke():
    pts = line_pts(50, 100.0, 4.0)
    (poly,) = geo.outline(pts)
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    assert min(xs) < -3.5 and max(xs) > 103.5
    assert abs(max(ys) - 4) < 1e-6 and abs(min(ys) + 4) < 1e-6
    assert len(geo.outline([(5, 5, 2)])[0]) >= 8


def test_outline_splits_at_corners_with_consistent_orientation():
    pts = [(float(x), 0.0, 2.0) for x in range(0, 50)] + [(50.0, float(y), 2.0) for y in range(0, 50)]
    polys = geo.outline(pts)
    assert len(polys) == 2
    dot = geo.circle_polygon(0, 0, 3)
    signs = {math.copysign(1, geo.signed_area(p)) for p in polys + [dot]}
    assert len(signs) == 1  # mesma orientação: a regra 'nonzero' une as partes


def test_find_corners_and_process_free_keep_sharp_corner():
    v = [(x, 0.0, 2.0) for x in range(0, 200, 2)] + [(200.0, y, 2.0) for y in range(0, 200, 2)]
    shaky = noisy(v, 0.8)
    kept = geo.process_free(shaky, 1.5, 6, fit_tol=1.0, corner_k=8)
    rounded = geo.process_free(shaky, 1.5, 6, fit_tol=1.0, corner_k=0)
    gap_kept = min(math.hypot(x - 200, y) for x, y, _ in kept)
    gap_rounded = min(math.hypot(x - 200, y) for x, y, _ in rounded)
    assert gap_kept < 2.5 and gap_rounded > gap_kept * 2


def test_taper_thins_ends_only():
    pts = geo.taper(line_pts(201, 200.0, 4.0), 40, 40)
    assert pts[0][2] < 1.0 and pts[-1][2] < 1.0
    assert math.isclose(pts[100][2], 4.0)


def test_erase_splits_stroke():
    pieces = geo.erase(line_pts(101, 100.0, 1.0), 50, 0, 5)
    assert len(pieces) == 2
    assert pieces[0][-1][0] < 45 and pieces[1][0][0] > 55
    assert geo.erase(line_pts(), 50, 50, 5) is None


def test_simplify_reduces_straight_runs():
    poly = [(i * 0.5, 0.0) for i in range(200)]
    assert geo.simplify(poly, 0.1) == [poly[0], poly[-1]]
