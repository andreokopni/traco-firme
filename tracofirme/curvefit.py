"""Ajuste de curvas Bézier cúbicas a pontos digitalizados.

Implementa o algoritmo de Philip J. Schneider ("An Algorithm for Automatically
Fitting Digitized Curves", Graphics Gems, 1990), o mesmo princípio do lápis do
Inkscape/Illustrator: o traço vira poucas curvas suaves dentro de uma tolerância.
"""
from __future__ import annotations

import math

import numpy as np

MAX_DEPTH = 32


def _bezier(ctrl, t):
    mt = 1.0 - t
    return ((mt ** 3)[:, None] * ctrl[0] + (3 * mt * mt * t)[:, None] * ctrl[1]
            + (3 * mt * t * t)[:, None] * ctrl[2] + (t ** 3)[:, None] * ctrl[3])


def _d1(ctrl, t):
    mt = 1.0 - t
    return ((3 * mt * mt)[:, None] * (ctrl[1] - ctrl[0]) + (6 * mt * t)[:, None] * (ctrl[2] - ctrl[1])
            + (3 * t * t)[:, None] * (ctrl[3] - ctrl[2]))


def _d2(ctrl, t):
    return ((6 * (1.0 - t))[:, None] * (ctrl[2] - 2 * ctrl[1] + ctrl[0])
            + (6 * t)[:, None] * (ctrl[3] - 2 * ctrl[2] + ctrl[1]))


def _unit(v):
    n = math.hypot(v[0], v[1])
    return v / n if n > 0 else v


def fit_curve(points, max_error):
    """Lista de curvas (arrays 4×2 de pontos de controle) que passam a no máximo
    `max_error` dos pontos (só x, y são usados)."""
    pts = np.asarray([(p[0], p[1]) for p in points], dtype=float)
    if len(pts) > 1:
        keep = np.r_[True, np.any(np.diff(pts, axis=0) != 0, axis=1)]
        pts = pts[keep]
    if len(pts) < 2:
        return []
    left = _unit(pts[1] - pts[0])
    right = _unit(pts[-2] - pts[-1])
    return _fit_cubic(pts, left, right, max_error, 0)


def fit_closed(points, max_error):
    """Como `fit_curve`, para um polígono fechado (o primeiro ponto é repetido no fim)."""
    pts = [(p[0], p[1]) for p in points]
    if len(pts) < 3:
        return []
    pts.append(pts[0])
    arr = np.asarray(pts, dtype=float)
    tangent = _unit(arr[1] - arr[-2])
    return _fit_cubic(arr, tangent, -tangent, max_error, 0)


def _fit_cubic(pts, left, right, err, depth):
    if len(pts) == 2:
        d = math.hypot(*(pts[1] - pts[0])) / 3
        return [np.array([pts[0], pts[0] + left * d, pts[1] + right * d, pts[1]])]
    u = _chord_params(pts)
    bez = _generate(pts, u, left, right)
    max_err, split = _max_error(pts, bez, u)
    if max_err < err:
        return [bez]
    if max_err < err * 4:
        for _ in range(20):
            u2 = _reparameterize(bez, pts, u)
            bez = _generate(pts, u2, left, right)
            max_err, split = _max_error(pts, bez, u2)
            if max_err < err:
                return [bez]
            u = u2
    if depth >= MAX_DEPTH:
        return [bez]
    center = _unit(pts[split - 1] - pts[split + 1])
    if not center.any():
        center = _unit(pts[split - 1] - pts[split])
    return (_fit_cubic(pts[:split + 1], left, center, err, depth + 1)
            + _fit_cubic(pts[split:], -center, right, err, depth + 1))


def _chord_params(pts):
    d = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    return d / d[-1] if d[-1] > 0 else np.linspace(0, 1, len(pts))


def _generate(pts, u, left, right):
    p0, p3 = pts[0], pts[-1]
    a1 = left[None, :] * (3 * (1 - u) ** 2 * u)[:, None]
    a2 = right[None, :] * (3 * (1 - u) * u ** 2)[:, None]
    c00, c01, c11 = np.sum(a1 * a1), np.sum(a1 * a2), np.sum(a2 * a2)
    tmp = pts - _bezier(np.array([p0, p0, p3, p3]), u)
    x0, x1 = np.sum(a1 * tmp), np.sum(a2 * tmp)
    det = c00 * c11 - c01 * c01
    alpha_l = (x0 * c11 - x1 * c01) / det if det != 0 else 0.0
    alpha_r = (c00 * x1 - c01 * x0) / det if det != 0 else 0.0
    seg = math.hypot(*(p3 - p0))
    eps = 1e-6 * seg
    if alpha_l < eps or alpha_r < eps:
        alpha_l = alpha_r = seg / 3
    return np.array([p0, p0 + left * alpha_l, p3 + right * alpha_r, p3])


def _max_error(pts, bez, u):
    d = np.sum((_bezier(bez, u) - pts) ** 2, axis=1)
    split = int(np.argmax(d[1:-1])) + 1
    return math.sqrt(d[split]), split


def _reparameterize(bez, pts, u):
    d = _bezier(bez, u) - pts
    q1, q2 = _d1(bez, u), _d2(bez, u)
    num = np.sum(d * q1, axis=1)
    den = np.sum(q1 * q1, axis=1) + np.sum(d * q2, axis=1)
    safe = np.abs(den) > 1e-12
    out = u.copy()
    out[safe] = u[safe] - num[safe] / den[safe]
    return np.clip(out, 0.0, 1.0)


def sample_beziers(beziers, spacing):
    """Pontos densos ao longo das curvas, com espaçamento aproximado `spacing`."""
    if not beziers:
        return np.zeros((0, 2))
    out = [beziers[0][0][None, :]]
    for b in beziers:
        approx = (math.hypot(*(b[1] - b[0])) + math.hypot(*(b[2] - b[1])) + math.hypot(*(b[3] - b[2])))
        m = max(1, int(math.ceil(approx / spacing)))
        out.append(_bezier(b, np.linspace(0.0, 1.0, m + 1)[1:]))
    return np.vstack(out)


def fit_and_sample(pts, tol, spacing):
    """Substitui um trecho (x, y, r) pela curva ajustada, levando o raio junto pelo
    comprimento de arco. As pontas do trecho continuam exatamente no lugar."""
    curve = sample_beziers(fit_curve(pts, tol), spacing)
    if len(curve) < 2:
        return list(pts)
    src = np.asarray(pts, dtype=float)
    s_src = np.r_[0.0, np.cumsum(np.hypot(*np.diff(src[:, :2], axis=0).T))]
    s_out = np.r_[0.0, np.cumsum(np.hypot(*np.diff(curve, axis=0).T))]
    if s_src[-1] <= 0 or s_out[-1] <= 0:
        return list(pts)
    radii = np.interp(s_out / s_out[-1], s_src / s_src[-1], src[:, 2])
    return [(float(x), float(y), float(r)) for (x, y), r in zip(curve, radii)]
