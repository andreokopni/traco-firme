"""Filtro 1€ (Casiez, Roussel e Vogel, CHI 2012): passa-baixa cuja frequência de
corte sobe com a velocidade. Devagar, alisa muito (tira tremor); rápido, quase não
atrasa (o traço acompanha a mão)."""
from __future__ import annotations

import math


def _alpha(cutoff, dt):
    tau = 1.0 / (2 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuroFilter:
    def __init__(self, min_cutoff=1.0, beta=0.01, d_cutoff=1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._t = None
        self._x = self._y = 0.0
        self._dx = self._dy = 0.0

    def __call__(self, t, x, y):
        if self._t is None:
            self._t, self._x, self._y = t, x, y
            return x, y
        dt = t - self._t
        if dt <= 0:
            return self._x, self._y
        self._t = t
        a_d = _alpha(self.d_cutoff, dt)
        self._dx += a_d * ((x - self._x) / dt - self._dx)
        self._dy += a_d * ((y - self._y) / dt - self._dy)
        cutoff = self.min_cutoff + self.beta * math.hypot(self._dx, self._dy)
        a = _alpha(cutoff, dt)
        self._x += a * (x - self._x)
        self._y += a * (y - self._y)
        return self._x, self._y


def for_strength(strength):
    """Filtro para o nível de estabilização (0–100) do painel, ou None se desligado."""
    if strength <= 0:
        return None
    min_cutoff = 10.0 * 0.15 ** (min(strength, 100) / 100)  # 10 Hz (leve) até 1,5 Hz (forte)
    return OneEuroFilter(min_cutoff=min_cutoff, beta=0.01)
