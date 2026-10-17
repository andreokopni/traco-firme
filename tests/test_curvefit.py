import math

import numpy as np
from helpers import arc_pts, noisy

from tracofirme import curvefit
from tracofirme.filters import OneEuroFilter


def test_fit_curve_stays_within_tolerance_and_uses_few_curves():
    pts = arc_pts(180, n=400)
    curves = curvefit.fit_curve(pts, 0.5)
    assert 1 <= len(curves) <= 4
    dense = curvefit.sample_beziers(curves, 0.5)
    for x, y, _ in pts:
        assert np.min(np.hypot(dense[:, 0] - x, dense[:, 1] - y)) < 0.6


def test_fit_and_sample_keeps_endpoints_and_carries_radius():
    pts = [(p[0], p[1], 1.0 + i / 100) for i, p in enumerate(noisy(arc_pts(90, n=200), 0.3))]
    out = curvefit.fit_and_sample(pts, 1.0, 1.0)
    assert math.isclose(out[0][0], pts[0][0]) and math.isclose(out[-1][1], pts[-1][1])
    assert abs(out[0][2] - 1.0) < 1e-6 and abs(out[-1][2] - pts[-1][2]) < 1e-6


def test_fit_closed_returns_closed_path():
    circle = [(math.cos(t) * 50, math.sin(t) * 50) for t in np.linspace(0, 2 * math.pi, 120, endpoint=False)]
    curves = curvefit.fit_closed(circle, 0.2)
    assert np.allclose(curves[0][0], curves[-1][3])


def test_one_euro_smooths_slow_jitter_but_follows_fast_motion():
    f = OneEuroFilter(min_cutoff=1.5, beta=0.01)
    ys = [f(i * 0.005, 0.0, (1.0 if i % 2 else -1.0))[1] for i in range(200)]
    assert max(abs(y) for y in ys[50:]) < 0.3  # tremor de ±1 px quase some
    f = OneEuroFilter(min_cutoff=1.5, beta=0.01)
    xs = [f(i * 0.005, i * 10.0, 0.0)[0] for i in range(100)]  # 2000 px/s
    assert 990 - xs[-1] < 40  # o atraso fica pequeno em movimento rápido
