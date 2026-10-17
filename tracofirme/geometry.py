"""Geometria básica dos traços: reamostragem, suavização, cantos, pontas e contorno.

Um traço é uma lista de pontos (x, y, r): posição no documento e raio do traço
naquele ponto. O reconhecimento de formas fica em `shapes.py` e o ajuste de curvas
Bézier em `curvefit.py`.
"""
from __future__ import annotations

import math

import numpy as np

TAU = 2 * math.pi
SPLIT_TURN_DEG = 35.0  # mudança de direção entre amostras vizinhas que conta como canto


def path_length(pts) -> float:
    total = 0.0
    for i in range(1, len(pts)):
        total += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
    return total


def resample(pts, spacing: float):
    """Reamostra os pontos em intervalos constantes de comprimento de arco."""
    if len(pts) < 2:
        return list(pts)
    out = [pts[0]]
    carry = 0.0  # distância percorrida desde a última amostra
    for i in range(1, len(pts)):
        ax, ay, ar = pts[i - 1]
        bx, by, br = pts[i]
        seg = math.hypot(bx - ax, by - ay)
        if seg == 0:
            continue
        t = spacing - carry
        while t <= seg:
            f = t / seg
            out.append((ax + (bx - ax) * f, ay + (by - ay) * f, ar + (br - ar) * f))
            t += spacing
        carry = seg - (t - spacing)
    last = pts[-1]
    gap = math.hypot(last[0] - out[-1][0], last[1] - out[-1][1])
    if len(out) > 1 and gap < spacing * 0.25:
        out[-1] = last
    elif gap > 0:
        out.append(last)
    return out


def smooth(pts, sigma: float, sigma_r: float | None = None):
    """Suavização gaussiana (sigma em amostras); `sigma_r` é o do raio (padrão: igual).

    Além das pontas, as posições são estendidas por reflexão pontual (2·p0 − pk),
    que mantém o primeiro e o último ponto no lugar e alisa as pontas tanto quanto o
    meio. O raio é estendido repetindo a borda.
    """
    n = len(pts)
    if sigma_r is None:
        sigma_r = sigma
    if n < 3 or (sigma < 0.3 and sigma_r < 0.3):
        return list(pts)
    xy = _gauss_positions(pts, sigma) if sigma >= 0.3 else [(p[0], p[1]) for p in pts]
    rs = _gauss_radius(pts, sigma_r) if sigma_r >= 0.3 else [p[2] for p in pts]
    return [(x, y, r) for (x, y), r in zip(xy, rs)]


def _kernel(sigma):
    radius = int(math.ceil(sigma * 3))
    k = np.arange(-radius, radius + 1)
    w = np.exp(-(k * k) / (2 * sigma * sigma))
    return radius, w / w.sum()


def _gauss_positions(pts, sigma):
    n = len(pts)
    radius, w = _kernel(sigma)
    xy = np.asarray([(p[0], p[1]) for p in pts], dtype=float)
    # Reflexão pontual nas pontas: índice -k vira 2·p0 − p[k] (e o mesmo no fim).
    left = 2 * xy[0] - xy[np.minimum(np.arange(radius, 0, -1), n - 1)]
    right = 2 * xy[-1] - xy[np.maximum(n - 1 - np.arange(1, radius + 1), 0)]
    padded = np.vstack([left, xy, right])
    sx = np.convolve(padded[:, 0], w, mode="valid")
    sy = np.convolve(padded[:, 1], w, mode="valid")
    return list(zip(sx.tolist(), sy.tolist()))


def _gauss_radius(pts, sigma):
    radius, w = _kernel(sigma)
    r = np.asarray([p[2] for p in pts], dtype=float)
    return np.convolve(np.pad(r, radius, mode="edge"), w, mode="valid").tolist()


# --- Cantos, pontas finas e processamento do traço ---------------------------------


def find_corners(pts, k: int, min_angle_deg: float = 65.0):
    """Índices de cantos vivos: pontos onde a direção muda mais que `min_angle_deg`
    comparando os vizinhos a `k` amostras de distância (máximo local)."""
    n = len(pts)
    if k < 1 or n < 2 * k + 1:
        return []
    ang = [0.0] * n
    for i in range(k, n - k):
        ax, ay = pts[i][0] - pts[i - k][0], pts[i][1] - pts[i - k][1]
        bx, by = pts[i + k][0] - pts[i][0], pts[i + k][1] - pts[i][1]
        la, lb = math.hypot(ax, ay), math.hypot(bx, by)
        if la < 1e-9 or lb < 1e-9:
            continue
        c = max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb)))
        ang[i] = math.degrees(math.acos(c))
    corners = []
    for i in range(k, n - k):
        if ang[i] >= min_angle_deg and ang[i] == max(ang[i - k:i + k + 1]):
            if not corners or i - corners[-1] > k:
                corners.append(i)
    return corners


def taper(pts, start_len: float, end_len: float, floor: float = 0.15):
    """Afina o começo e o fim do traço ao longo de `start_len`/`end_len` (comprimento)."""
    n = len(pts)
    if n < 2 or (start_len <= 0 and end_len <= 0):
        return list(pts)
    total = path_length(pts)
    budget = total * 0.8
    if start_len + end_len > budget > 0:
        k = budget / (start_len + end_len)
        start_len, end_len = start_len * k, end_len * k

    def ease(t):
        return floor + (1.0 - floor) * (1.0 - (1.0 - t) ** 2)

    out, s = [], 0.0
    for i, (x, y, r) in enumerate(pts):
        if i:
            s += math.hypot(x - pts[i - 1][0], y - pts[i - 1][1])
        f = 1.0
        if start_len > 0 and s < start_len:
            f = min(f, ease(s / start_len))
        if end_len > 0 and total - s < end_len:
            f = min(f, ease((total - s) / end_len))
        out.append((x, y, r * f))
    return out


def process_free(pts, spacing, sigma, fit_tol=0.0, corner_k=0):
    """Pipeline do traço à mão livre ao soltar a caneta.

    1. reamostra; 2. acha cantos vivos (se `corner_k`) e os mantém fixos;
    3. alisa cada trecho entre cantos (gaussiana; o raio, com o dobro do sigma);
    4. ajusta curvas Bézier (se `fit_tol`), o que tira as ondulações residuais.
    """
    from .curvefit import fit_and_sample

    pts = resample(pts, spacing)
    n = len(pts)
    if n < 3:
        return pts
    corners = []
    if corner_k >= 2:
        pre = smooth(pts, max(1.0, corner_k / 4))
        corners = find_corners(pre, corner_k)
        for c in corners:
            pts[c] = pre[c]
    bounds = [0] + corners + [n - 1]
    out = []
    for a, b in zip(bounds, bounds[1:]):
        seg = smooth(pts[a:b + 1], sigma, sigma * 2)
        if fit_tol > 0 and len(seg) >= 4:
            seg = fit_and_sample(seg, fit_tol, spacing)
        out.extend(seg if not out else seg[1:])
    return out


# --- Contorno ------------------------------------------------------------------------


def _arc_points(cx, cy, r, a_start, sweep, steps):
    """Pontos internos de um arco (sem as extremidades)."""
    return [
        (cx + math.cos(a_start + sweep * k / steps) * r, cy + math.sin(a_start + sweep * k / steps) * r)
        for k in range(1, steps)
    ]


def _cap_steps(r):
    return max(4, min(32, int(math.ceil(r * 1.2))))


def circle_polygon(x, y, r):
    """Círculo com a mesma orientação dos contornos de traço (necessário para a
    regra 'nonzero' somar as partes em vez de abrir buracos)."""
    steps = max(8, min(64, int(math.ceil(r * 2.5))))
    return [(x + math.cos(-TAU * k / steps) * r, y + math.sin(-TAU * k / steps) * r) for k in range(steps)]


def split_at_turns(pts, max_turn_deg=SPLIT_TURN_DEG):
    """Divide o traço nos cantos (mudança brusca de direção). Os pedaços
    compartilham o ponto do canto, e as pontas redondas formam a junção."""
    n = len(pts)
    if n < 3:
        return [list(pts)]
    limit = math.cos(math.radians(max_turn_deg))
    runs, start = [], 0
    for i in range(1, n - 1):
        ax, ay = pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]
        bx, by = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
        la, lb = math.hypot(ax, ay), math.hypot(bx, by)
        if la > 0 and lb > 0 and (ax * bx + ay * by) / (la * lb) < limit:
            runs.append(pts[start:i + 1])
            start = i
    runs.append(pts[start:])
    return runs


def outline(pts):
    """Contorno de um traço de largura variável com pontas redondas: lista de
    polígonos fechados (um por trecho entre cantos), todos com a mesma orientação.
    Deve ser preenchido com a regra 'nonzero'."""
    if not pts:
        return []
    return [_outline_run(run) for run in split_at_turns(pts)]


def _outline_run(pts):
    n = len(pts)
    if n == 1 or path_length(pts) < 1e-6:
        x, y, r = max(pts, key=lambda p: p[2])
        return circle_polygon(x, y, r)
    left, right, normals = [], [], []
    nx, ny = 0.0, 1.0
    for i in range(n):
        a = pts[max(i - 1, 0)]
        b = pts[min(i + 1, n - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length > 0:
            nx, ny = -dy / length, dx / length
        x, y, r = pts[i]
        left.append((x + nx * r, y + ny * r))
        right.append((x - nx * r, y - ny * r))
        normals.append((nx, ny))
    ex, ey, er = pts[-1]
    a_end = math.atan2(normals[-1][1], normals[-1][0])
    sx, sy, sr = pts[0]
    a_start = math.atan2(-normals[0][1], -normals[0][0])
    end_cap = _arc_points(ex, ey, er, a_end, -math.pi, _cap_steps(er))
    start_cap = _arc_points(sx, sy, sr, a_start, -math.pi, _cap_steps(sr))
    return left + end_cap + right[::-1] + start_cap


def signed_area(poly):
    s = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i][0], poly[i][1]
        x1, y1 = poly[(i + 1) % len(poly)][0], poly[(i + 1) % len(poly)][1]
        s += x0 * y1 - x1 * y0
    return s / 2


# --- Utilidades ------------------------------------------------------------------------


def simplify_indices(poly, tol: float):
    """Ramer-Douglas-Peucker iterativo; devolve os índices mantidos."""
    n = len(poly)
    if n < 3:
        return list(range(n))
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        ax, ay = poly[i0][0], poly[i0][1]
        bx, by = poly[i1][0], poly[i1][1]
        best, best_d = -1, tol
        for i in range(i0 + 1, i1):
            d = dist_to_segment(poly[i][0], poly[i][1], ax, ay, bx, by)
            if d > best_d:
                best, best_d = i, d
        if best >= 0:
            keep[best] = True
            stack.append((i0, best))
            stack.append((best, i1))
    return [i for i in range(n) if keep[i]]


def simplify(poly, tol: float):
    return [poly[i] for i in simplify_indices(poly, tol)]


def dist_to_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))


def nearest_point(pts, x, y):
    """(distância, índice) do ponto de `pts` mais próximo de (x, y)."""
    best_d, best_i = math.inf, -1
    for i, p in enumerate(pts):
        d = (p[0] - x) ** 2 + (p[1] - y) ** 2
        if d < best_d:
            best_d, best_i = d, i
    return math.sqrt(best_d), best_i


def bridge(a, b, spacing):
    """Pontos de uma ponte reta de `a` até `b` (sem incluir `a`), com o raio de `a`."""
    ax, ay, r = a
    bx, by = b[0], b[1]
    n = max(1, int(math.ceil(math.hypot(bx - ax, by - ay) / spacing)))
    return [(ax + (bx - ax) * k / n, ay + (by - ay) * k / n, r) for k in range(1, n + 1)]


# --- Borracha --------------------------------------------------------------------


def erase(pts, cx, cy, er):
    """Remove os pontos tocados pela borracha. Retorna None se nada mudou,
    senão a lista de pedaços restantes (cada um com 2+ pontos)."""
    keep = [math.hypot(x - cx, y - cy) >= er + r * 0.5 for x, y, r in pts]
    if all(keep):
        return None
    pieces, cur = [], []
    for p, k in zip(pts, keep):
        if k:
            cur.append(p)
        else:
            if len(cur) >= 2:
                pieces.append(cur)
            cur = []
    if len(cur) >= 2:
        pieces.append(cur)
    return pieces


def stroke_hit(pts, cx, cy, er):
    return any(math.hypot(x - cx, y - cy) < er + r for x, y, r in pts)
