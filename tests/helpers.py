"""Geradores de traços sintéticos com tremor para os testes."""
import math
import random


def noisy(points, amp, seed=1):
    rnd = random.Random(seed)
    return [(p[0] + rnd.uniform(-amp, amp), p[1] + rnd.uniform(-amp, amp), p[2] if len(p) > 2 else 3.0)
            for p in points]


def line_pts(n=200, length=400.0, r=3.0):
    return [(length * i / (n - 1), 0.0, r) for i in range(n)]


def arc_pts(sweep_deg, n=200, radius=150.0, r=3.0):
    return [
        (math.cos(math.radians(sweep_deg) * i / (n - 1)) * radius,
         math.sin(math.radians(sweep_deg) * i / (n - 1)) * radius, r)
        for i in range(n)
    ]


def ellipse_pts(a, b, rot, n=300, cx=400.0, cy=400.0):
    out = []
    for i in range(n + 1):
        t = 2 * math.pi * i / n
        out.append((cx + a * math.cos(t) * math.cos(rot) - b * math.sin(t) * math.sin(rot),
                    cy + a * math.cos(t) * math.sin(rot) + b * math.sin(t) * math.cos(rot), 3.0))
    return out


def polygon_pts(verts, step=2.0, closed=True):
    vs = list(verts) + ([verts[0]] if closed else [])
    out = []
    for (ax, ay), (bx, by) in zip(vs, vs[1:]):
        n = max(1, int(math.hypot(bx - ax, by - ay) / step))
        out += [(ax + (bx - ax) * k / n, ay + (by - ay) * k / n, 3.0) for k in range(n)]
    if not closed:
        out.append((vs[-1][0], vs[-1][1], 3.0))
    return out
