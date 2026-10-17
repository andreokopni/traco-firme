"""Reconhecimento de formas ao segurar a caneta parada: reta, arco, círculo, elipse,
linha quebrada e polígonos (com retângulo, quadrado e lados alinhados corrigidos).

As tolerâncias usam `unit` (um pixel de tela em unidades do documento) para que o
comportamento seja o mesmo em qualquer zoom.
"""
from __future__ import annotations

import math

import numpy as np

from .geometry import TAU, dist_to_segment, path_length, resample, simplify_indices, smooth

AXIS_SNAP_DEG = 7.0       # lado a menos que isso da horizontal/vertical vira exato
RIGHT_ANGLE_TOL = 15.0    # ângulos de 75° a 105° contam como retos (retângulo)
SQUARE_TOL = 0.12         # lados com até 12% de diferença viram quadrado
MIN_TURN_DEG = 30.0       # vértice de polígono precisa virar pelo menos isso


# --- Detecção principal --------------------------------------------------------------


def detect_shape(pts, unit: float = 1.0, axis_angle: float = 0.0):
    """Tenta reconhecer o traço. Retorna um dicionário de forma ou None.

    `axis_angle` (radianos) é a direção da horizontal da tela no documento, para
    alinhar lados quando a tela está girada.
    """
    if len(pts) < 3:
        return None
    raw_length = path_length(pts)
    if raw_length < 20 * unit:
        return None
    # O tremor infla o comprimento; mede numa versão levemente alisada.
    sm = smooth(resample(pts, max(unit, raw_length / 120)), 3)
    length = path_length(sm)
    diag = _diag(sm)
    ax, ay = pts[0][0], pts[0][1]
    bx, by = pts[-1][0], pts[-1][1]
    chord = math.hypot(bx - ax, by - ay)
    closed = chord <= max(0.2 * diag, 12 * unit) and length >= 1.8 * diag
    if closed:
        return _detect_closed(pts, sm, unit, diag, axis_angle)
    return _detect_open(pts, sm, unit, length, chord, axis_angle)


def _detect_open(pts, sm, unit, length, chord, axis_angle):
    ax, ay = pts[0][0], pts[0][1]
    bx, by = pts[-1][0], pts[-1][1]
    line_devs = [dist_to_segment(p[0], p[1], ax, ay, bx, by) for p in pts]
    line_rms = math.sqrt(sum(d * d for d in line_devs) / len(line_devs))
    line_ok = chord > 0 and length / chord < 1.3 and max(line_devs) <= max(0.10 * chord, 3 * unit)
    # Arco só quando curva de verdade (40°+) e se ajusta bem melhor que uma reta;
    # curvas mais leves quase sempre são uma reta feita à mão com barriga.
    arc = _detect_arc(pts, unit)
    if arc is not None and not (abs(arc["sweep"]) >= math.radians(40) and arc["rms"] < 0.5 * line_rms):
        arc = None
    poly = _detect_polygon(sm, unit, closed=False, raw=pts)
    if arc is not None:
        if poly is not None and poly["rms"] < 0.5 * arc["rms"]:
            return _beautify(poly, axis_angle)
        return arc
    if line_ok:
        if poly is not None and poly["rms"] < 0.4 * line_rms:
            return _beautify(poly, axis_angle)
        return {"kind": "line", "a": (ax, ay), "b": (bx, by)}
    return _beautify(poly, axis_angle) if poly is not None else None


def _detect_closed(pts, sm, unit, diag, axis_angle):
    rounds = []
    arc = _detect_arc(pts, unit)
    if arc is not None and is_closed(arc):
        rounds.append((arc["rms"] / diag, 0, arc))
    ell = _detect_ellipse(pts, unit)
    if ell is not None:
        if ell["b"] / ell["a"] > 0.9:  # quase redonda: círculo
            r = (ell["a"] + ell["b"]) / 2
            cx, cy = ell["c"]
            ell = {"kind": "arc", "c": ell["c"], "r": r, "sweep": ell["sweep"], "rms": ell["rms"],
                   "a0": math.atan2(pts[0][1] - cy, pts[0][0] - cx)}
            rounds.append((ell["rms"] / diag, 0, ell))
        else:
            rounds.append((ell["rms"] / diag * 1.25, 1, ell))  # 1,25: prefere o círculo, mais simples
    best_round = min(rounds, key=lambda c: (c[0], c[1])) if rounds else None
    poly = _detect_polygon(sm, unit, closed=True, raw=pts)
    if poly is not None and (best_round is None or poly["rms"] / diag < 0.6 * best_round[0]):
        return _beautify(poly, axis_angle)
    if best_round is not None and best_round[0] <= 0.05:
        return best_round[2]
    return _beautify(poly, axis_angle) if poly is not None else None


def _diag(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return max(1e-9, math.hypot(max(xs) - min(xs), max(ys) - min(ys)))


# --- Círculo e arco -------------------------------------------------------------------


def fit_circle(pts):
    """Ajuste algébrico de círculo (método de Bullock). Retorna (cx, cy, R) ou None."""
    n = len(pts)
    if n < 3:
        return None
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    suu = suv = svv = suuu = svvv = suvv = svuu = 0.0
    for p in pts:
        u, v = p[0] - mx, p[1] - my
        suu += u * u
        suv += u * v
        svv += v * v
        suuu += u * u * u
        svvv += v * v * v
        suvv += u * v * v
        svuu += v * u * u
    det = suu * svv - suv * suv
    if abs(det) < 1e-9:
        return None
    b1 = 0.5 * (suuu + suvv)
    b2 = 0.5 * (svvv + svuu)
    uc = (b1 * svv - b2 * suv) / det
    vc = (suu * b2 - suv * b1) / det
    r = math.sqrt(uc * uc + vc * vc + (suu + svv) / n)
    return mx + uc, my + vc, r


def _wrap(a):
    return (a + math.pi) % TAU - math.pi


def signed_sweep(pts, cx, cy):
    total = 0.0
    prev = math.atan2(pts[0][1] - cy, pts[0][0] - cx)
    for p in pts[1:]:
        a = math.atan2(p[1] - cy, p[0] - cx)
        total += _wrap(a - prev)
        prev = a
    return total


def _detect_arc(pts, unit):
    fit = fit_circle(pts)
    if fit is None:
        return None
    cx, cy, r = fit
    if r < 5 * unit:
        return None
    devs = [abs(math.hypot(p[0] - cx, p[1] - cy) - r) for p in pts]
    rms = math.sqrt(sum(d * d for d in devs) / len(devs))
    if max(devs) > max(0.12 * r, 3 * unit) or rms > max(0.05 * r, 1.5 * unit):
        return None
    sweep = signed_sweep(pts, cx, cy)
    if abs(sweep) > TAU * 1.15:
        return None
    if abs(sweep) >= TAU * 0.85:
        sweep = math.copysign(TAU, sweep)
    ax, ay = pts[0][0], pts[0][1]
    return {"kind": "arc", "c": (cx, cy), "r": r, "a0": math.atan2(ay - cy, ax - cx), "sweep": sweep, "rms": rms}


# --- Elipse ----------------------------------------------------------------------------


def fit_ellipse(xs, ys):
    """Ajuste direto de elipse por mínimos quadrados (Fitzgibbon; versão estável de
    Halír e Flusser). Retorna (cx, cy, a, b, ângulo do eixo a) com a >= b, ou None."""
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    if len(xs) < 6:
        return None
    mx, my = xs.mean(), ys.mean()
    s = max(xs.std(), ys.std()) or 1.0
    x, y = (xs - mx) / s, (ys - my) / s
    d1 = np.c_[x * x, x * y, y * y]
    d2 = np.c_[x, y, np.ones_like(x)]
    s1, s2, s3 = d1.T @ d1, d1.T @ d2, d2.T @ d2
    try:
        t = -np.linalg.solve(s3, s2.T)
    except np.linalg.LinAlgError:
        return None
    m = s1 + s2 @ t
    m = np.array([m[2] / 2, -m[1], m[0] / 2])
    _, vecs = np.linalg.eig(m)
    vecs = vecs.real
    cond = 4 * vecs[0] * vecs[2] - vecs[1] ** 2
    idx = np.where(cond > 0)[0]
    if len(idx) == 0:
        return None
    a_, b_, c_ = vecs[:, idx[0]]
    d_, e_, f_ = t @ vecs[:, idx[0]]
    q = np.array([[a_, b_ / 2], [b_ / 2, c_]])
    try:
        x0, y0 = np.linalg.solve(2 * q, [-d_, -e_])
    except np.linalg.LinAlgError:
        return None
    f0 = f_ + (d_ * x0 + e_ * y0) / 2
    lam, vec = np.linalg.eigh(q)
    if np.any(-f0 / lam <= 0):
        return None
    axes = np.sqrt(-f0 / lam)
    i_major = int(np.argmax(axes))
    a, b = axes[i_major], axes[1 - i_major]
    theta = math.atan2(vec[1, i_major], vec[0, i_major])
    return mx + s * x0, my + s * y0, s * a, s * b, theta


def _ellipse_points(cx, cy, a, b, rot, t):
    c, s = math.cos(rot), math.sin(rot)
    ex, ey = a * np.cos(t), b * np.sin(t)
    return cx + ex * c - ey * s, cy + ex * s + ey * c


def _detect_ellipse(pts, unit):
    fit = fit_ellipse([p[0] for p in pts], [p[1] for p in pts])
    if fit is None:
        return None
    cx, cy, a, b, rot = fit
    if b < 5 * unit or a > 50 * b:
        return None
    ex, ey = _ellipse_points(cx, cy, a, b, rot, np.linspace(0, TAU, 360, endpoint=False))
    px = np.array([p[0] for p in pts])[:, None]
    py = np.array([p[1] for p in pts])[:, None]
    d = np.sqrt(np.min((px - ex[None, :]) ** 2 + (py - ey[None, :]) ** 2, axis=1))
    rms = float(np.sqrt(np.mean(d * d)))
    diag = _diag(pts)
    if rms > 0.04 * diag or d.max() > 0.12 * diag:
        return None
    c, s = math.cos(rot), math.sin(rot)
    u = (pts[0][0] - cx) * c + (pts[0][1] - cy) * s
    v = -(pts[0][0] - cx) * s + (pts[0][1] - cy) * c
    sweep = math.copysign(TAU, signed_sweep(pts, cx, cy))
    return {"kind": "ellipse", "c": (cx, cy), "a": a, "b": b, "rot": rot,
            "t0": math.atan2(v / b, u / a), "sweep": sweep, "rms": rms}


# --- Polígonos -------------------------------------------------------------------------


def _fit_line(piece):
    arr = np.asarray([(p[0], p[1]) for p in piece], dtype=float)
    n = len(arr)
    trim = int(n * 0.12) if n >= 8 else 0  # longe dos cantos, que o tremor arredonda
    core = arr[trim:n - trim] if n - 2 * trim >= 2 else arr
    c = core.mean(axis=0)
    _, _, vt = np.linalg.svd(core - c)
    d = vt[0]
    if np.dot(d, arr[-1] - arr[0]) < 0:
        d = -d
    rel = core - c
    dev = float(np.max(np.abs(rel[:, 0] * d[1] - rel[:, 1] * d[0])))
    return c, d, dev


def _intersect(c1, d1, c2, d2):
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cross) < 1e-9:
        return None
    t = ((c2[0] - c1[0]) * d2[1] - (c2[1] - c1[1]) * d2[0]) / cross
    return c1 + d1 * t


def _project(p, c, d):
    rel = np.array([p[0], p[1]]) - c
    return c + d * float(np.dot(rel, d))


def _turn_deg(d1, d2):
    return math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(d1, d2))))))


def _detect_polygon(sm, unit, closed, raw):
    diag = _diag(sm)
    tol = max(0.05 * diag, 3 * unit)
    idx = simplify_indices(sm, tol)
    pieces = [sm[a:b + 1] for a, b in zip(idx, idx[1:])]
    if len(pieces) < 2:
        return None
    # Junta trechos vizinhos quase alinhados (inclusive o último com o primeiro,
    # quando o traço fechado começou no meio de um lado).
    changed = True
    while changed and len(pieces) >= 2:
        changed = False
        lines = [_fit_line(p) for p in pieces]
        pairs = list(zip(range(len(pieces)), range(1, len(pieces))))
        if closed:
            pairs.append((len(pieces) - 1, 0))
        for i, j in pairs:
            if _turn_deg(lines[i][1], lines[j][1]) < MIN_TURN_DEG:
                if j == 0:
                    pieces[0] = pieces[-1] + pieces[0][1:]
                    pieces.pop()
                else:
                    pieces[i] = pieces[i] + pieces[j][1:]
                    pieces.pop(j)
                changed = True
                break
    n = len(pieces)
    if (closed and not 3 <= n <= 8) or (not closed and not 2 <= n <= 6):
        return None
    lines = [_fit_line(p) for p in pieces]
    if any(dev > tol * 1.2 for _, _, dev in lines):
        return None
    verts = []
    if not closed:
        verts.append(_project(sm[0], lines[0][0], lines[0][1]))
    links = range(n) if closed else range(n - 1)
    for i in links:
        j = (i + 1) % n
        p = _intersect(lines[i][0], lines[i][1], lines[j][0], lines[j][1])
        if p is None:
            return None
        verts.append(p)
    if not closed:
        verts.append(_project(sm[-1], lines[-1][0], lines[-1][1]))
    if closed:
        verts = verts[-1:] + verts[:-1]  # vértice i = início do lado i
    centroid = np.mean([(p[0], p[1]) for p in sm], axis=0)
    if any(np.hypot(*(v - centroid)) > diag * 1.5 for v in verts):
        return None
    # Quina de verdade: o traço passa perto do vértice. Numa curva suave (um S, por
    # exemplo) o encontro das retas fica longe do traço.
    corners = verts if closed else verts[1:-1]
    raw_xy = np.asarray([(p[0], p[1]) for p in raw], dtype=float)
    for v in corners:
        if np.min(np.hypot(raw_xy[:, 0] - v[0], raw_xy[:, 1] - v[1])) > max(0.5 * tol, 3 * unit):
            return None
    verts = [(float(v[0]), float(v[1])) for v in verts]
    return {"kind": "poly", "pts": verts, "closed": closed, "rms": _poly_rms(sm, verts, closed)}


def _poly_rms(pts, verts, closed):
    edges = list(zip(verts, verts[1:] + verts[:1])) if closed else list(zip(verts, verts[1:]))
    total = 0.0
    for p in pts:
        d = min(dist_to_segment(p[0], p[1], a[0], a[1], b[0], b[1]) for a, b in edges)
        total += d * d
    return math.sqrt(total / len(pts))


def _beautify(shape, axis_angle):
    """Lados quase horizontais/verticais ficam exatos; quatro ângulos quase retos
    viram retângulo, e lados quase iguais, quadrado."""
    verts = [np.array(v) for v in shape["pts"]]
    closed = shape["closed"]
    n_edges = len(verts) if closed else len(verts) - 1
    lines = []
    for i in range(n_edges):
        p, q = verts[i], verts[(i + 1) % len(verts)]
        d = (q - p) / max(1e-12, float(np.hypot(*(q - p))))
        lines.append(((p + q) / 2, _snap_dir(d, axis_angle)))
    if closed and n_edges == 4 and all(
        abs(_turn_deg(lines[i][1], lines[(i + 1) % 4][1]) - 90) <= RIGHT_ANGLE_TOL for i in range(4)
    ):
        return _rectangle(verts, lines, axis_angle, shape)
    new = []
    if not closed:
        new.append(_project(verts[0], *lines[0]))
    for i in range(n_edges if closed else n_edges - 1):
        j = (i + 1) % n_edges
        p = _intersect(lines[i][0], lines[i][1], lines[j][0], lines[j][1])
        new.append(p if p is not None else verts[j])
    if not closed:
        new.append(_project(verts[-1], *lines[-1]))
    else:
        new = new[-1:] + new[:-1]
    return {**shape, "pts": [(float(v[0]), float(v[1])) for v in new]}


def _snap_dir(d, axis_angle):
    ang = math.atan2(d[1], d[0]) - axis_angle
    snapped = round(ang / (math.pi / 2)) * (math.pi / 2)
    if abs(ang - snapped) <= math.radians(AXIS_SNAP_DEG):
        a = snapped + axis_angle
        return np.array([math.cos(a), math.sin(a)])
    return d


def _rectangle(verts, lines, axis_angle, shape):
    # Orientação média dos quatro lados (média circular de 4·ângulo).
    sx = sum(math.cos(4 * math.atan2(d[1], d[0])) for _, d in lines)
    sy = sum(math.sin(4 * math.atan2(d[1], d[0])) for _, d in lines)
    theta = math.atan2(sy, sx) / 4
    rel = theta - axis_angle
    snapped = round(rel / (math.pi / 2)) * (math.pi / 2)
    if abs(rel - snapped) <= math.radians(AXIS_SNAP_DEG):
        theta = snapped + axis_angle
    d0 = verts[1] - verts[0]
    # Eixo x do retângulo = direção (θ + k·90°) mais próxima do primeiro lado desenhado.
    k = round((math.atan2(d0[1], d0[0]) - theta) / (math.pi / 2))
    a = theta + k * math.pi / 2
    ex = np.array([math.cos(a), math.sin(a)])
    ey = np.array([-ex[1], ex[0]])
    if np.dot(verts[3] - verts[0], ey) < 0:
        ey = -ey
    w = (abs(np.dot(verts[1] - verts[0], ex)) + abs(np.dot(verts[2] - verts[3], ex))) / 2
    h = (abs(np.dot(verts[3] - verts[0], ey)) + abs(np.dot(verts[2] - verts[1], ey))) / 2
    square = abs(w - h) / max(w, h) < SQUARE_TOL
    if square:
        w = h = (w + h) / 2
    c = np.mean(verts, axis=0)
    v0 = c - ex * w / 2 - ey * h / 2
    out = [v0, v0 + ex * w, v0 + ex * w + ey * h, v0 + ey * h]
    return {**shape, "pts": [(float(v[0]), float(v[1])) for v in out], "rect": "square" if square else "rect"}


# --- Uso das formas ----------------------------------------------------------------------


def is_closed(shape):
    kind = shape["kind"]
    if kind == "arc":
        return abs(shape["sweep"]) >= TAU - 1e-9
    if kind == "ellipse":
        return True
    if kind == "poly":
        return shape["closed"]
    return False


def shape_name(shape):
    kind = shape["kind"]
    if kind == "line":
        return "reta"
    if kind == "arc":
        return "círculo" if is_closed(shape) else "arco"
    if kind == "ellipse":
        return "elipse"
    if not shape["closed"]:
        return "linha quebrada"
    if shape.get("rect") == "square":
        return "quadrado"
    if shape.get("rect") == "rect":
        return "retângulo"
    n = len(shape["pts"])
    return {3: "triângulo", 4: "quadrilátero"}.get(n, f"polígono de {n} lados")


def update_shape_end(shape, x, y):
    """Move a ponta final da forma para acompanhar a caneta (formas abertas)."""
    kind = shape["kind"]
    if kind == "line":
        return {**shape, "b": (x, y)}
    if kind == "poly" and not shape["closed"]:
        return {**shape, "pts": shape["pts"][:-1] + [(x, y)]}
    if kind != "arc" or is_closed(shape):
        return shape
    cx, cy = shape["c"]
    end = shape["a0"] + shape["sweep"]
    sweep = shape["sweep"] + _wrap(math.atan2(y - cy, x - cx) - end)
    sweep = max(-TAU, min(TAU, sweep))
    return {**shape, "sweep": sweep}


def snap_angle(a, b, step_deg=15.0):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    step = math.radians(step_deg)
    ang = round(math.atan2(dy, dx) / step) * step
    return a[0] + math.cos(ang) * length, a[1] + math.sin(ang) * length


def sample_profile(profile, t):
    if not profile:
        return 1.0
    f = max(0.0, min(1.0, t)) * (len(profile) - 1)
    i = int(f)
    if i >= len(profile) - 1:
        return profile[-1]
    return profile[i] + (profile[i + 1] - profile[i]) * (f - i)


def build_shape(shape, profile, spacing):
    """Pontos (x, y, r) da forma, distribuindo o perfil de raio ao longo dela."""
    kind = shape["kind"]
    if kind == "line":
        xy = _polyline([shape["a"], shape["b"]], spacing)
    elif kind == "poly":
        verts = list(shape["pts"])
        if shape["closed"]:
            verts.append(verts[0])
        xy = _polyline(verts, spacing)
    elif kind == "arc":
        cx, cy = shape["c"]
        r, a0, sweep = shape["r"], shape["a0"], shape["sweep"]
        n = max(3, int(math.ceil(abs(sweep) * r / spacing)) + 1)
        xy = [(cx + math.cos(a0 + sweep * k / (n - 1)) * r, cy + math.sin(a0 + sweep * k / (n - 1)) * r)
              for k in range(n)]
    else:  # elipse
        a, b = shape["a"], shape["b"]
        perimeter = math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))  # Ramanujan
        n = max(8, int(math.ceil(perimeter / spacing)) + 1)
        t = shape["t0"] + shape["sweep"] * np.linspace(0, 1, n)
        ex, ey = _ellipse_points(*shape["c"], a, b, shape["rot"], t)
        xy = list(zip(ex.tolist(), ey.tolist()))
    total = path_length(xy) or 1.0
    out, s = [], 0.0
    for i, (x, y) in enumerate(xy):
        if i:
            s += math.hypot(x - xy[i - 1][0], y - xy[i - 1][1])
        out.append((x, y, sample_profile(profile, s / total)))
    return out


def _polyline(verts, spacing):
    """Pontos ao longo dos lados, incluindo cada vértice exatamente uma vez."""
    out = [tuple(verts[0])]
    for (ax, ay), (bx, by) in zip(verts, verts[1:]):
        n = max(1, int(math.ceil(math.hypot(bx - ax, by - ay) / spacing)))
        out.extend((ax + (bx - ax) * k / n, ay + (by - ay) * k / n) for k in range(1, n + 1))
    return out


def shape_metrics(pts, unit=1.0):
    """Medidas usadas pela detecção, para o log de diagnóstico."""
    if len(pts) < 3:
        return {"n": len(pts)}
    raw_length = path_length(pts)
    sm = smooth(resample(pts, max(unit, raw_length / 120)), 3)
    length = path_length(sm)
    ax, ay, bx, by = pts[0][0], pts[0][1], pts[-1][0], pts[-1][1]
    chord = math.hypot(bx - ax, by - ay)
    out = {
        "n": len(pts),
        "len_px": raw_length / unit,
        "len_smooth_px": length / unit,
        "chord_px": chord / unit,
        "diag_px": _diag(sm) / unit,
        "len_ratio": length / chord if chord else None,
        "line_dev_ratio": (max(dist_to_segment(p[0], p[1], ax, ay, bx, by) for p in pts) / chord) if chord else None,
    }
    fit = fit_circle(pts)
    if fit:
        cx, cy, r = fit
        devs = [abs(math.hypot(p[0] - cx, p[1] - cy) - r) for p in pts]
        out.update(
            arc_r_px=r / unit,
            arc_maxdev_ratio=max(devs) / r,
            arc_rms_ratio=math.sqrt(sum(d * d for d in devs) / len(devs)) / r,
            arc_sweep_deg=math.degrees(signed_sweep(pts, cx, cy)),
        )
    return out
