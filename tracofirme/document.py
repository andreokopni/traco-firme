"""Modelo do documento: traços vetoriais, desfazer/refazer e arquivo de projeto."""
from __future__ import annotations

import json

from . import geometry as geo

MAX_UNDO = 300


class Stroke:
    """Traço imutável. `qpath` é um cache preenchido pela camada de desenho (Qt)."""

    __slots__ = ("pts", "color", "_bbox", "_outline", "qpath")

    def __init__(self, pts, color="#000000"):
        self.pts = tuple(pts)
        self.color = color
        self._bbox = None
        self._outline = None
        self.qpath = None

    @property
    def bbox(self):
        if self._bbox is None:
            self._bbox = (
                min(x - r for x, y, r in self.pts),
                min(y - r for x, y, r in self.pts),
                max(x + r for x, y, r in self.pts),
                max(y + r for x, y, r in self.pts),
            )
        return self._bbox

    @property
    def outline(self):
        """Lista de polígonos (um por trecho entre cantos)."""
        if self._outline is None:
            self._outline = geo.outline(self.pts)
        return self._outline


class Document:
    def __init__(self, width=2480, height=3508, dpi=300):
        self.width = width
        self.height = height
        self.dpi = dpi
        self.strokes: list[Stroke] = []
        self.sketch_path: str | None = None
        self.modified = False
        # Cada estado guardado é (traços, largura, altura).
        self._undo: list[tuple[list[Stroke], int, int]] = []
        self._redo: list[tuple[list[Stroke], int, int]] = []

    def _state(self):
        return self.strokes, self.width, self.height

    def _restore(self, state):
        self.strokes, self.width, self.height = state

    def checkpoint(self, before=None):
        """Guarda o estado anterior a uma alteração para poder desfazê-la.
        `before` é a lista de traços de antes, quando a alteração já aconteceu."""
        strokes = list(self.strokes) if before is None else before
        self._undo.append((strokes, self.width, self.height))
        del self._undo[:-MAX_UNDO]
        self._redo.clear()
        self.modified = True

    def resize(self, width, height, dx=0.0, dy=0.0):
        """Muda o tamanho da folha deslocando o desenho em (dx, dy)."""
        self.checkpoint()
        if dx or dy:
            self.strokes = [
                Stroke([(x + dx, y + dy, r) for x, y, r in s.pts], s.color) for s in self.strokes
            ]
        self.width, self.height = width, height

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def add_stroke(self, stroke):
        self.checkpoint()
        self.strokes.append(stroke)

    def clear(self):
        if self.strokes:
            self.checkpoint()
            self.strokes = []

    def undo(self):
        if not self._undo:
            return False
        self._redo.append(self._state())
        self._restore(self._undo.pop())
        self.modified = True
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append(self._state())
        self._restore(self._redo.pop())
        self.modified = True
        return True

    # --- Arquivo de projeto (.traco, JSON) ---

    def save(self, path):
        data = {
            "format": "tracofirme",
            "version": 1,
            "width": self.width,
            "height": self.height,
            "dpi": self.dpi,
            "sketch": self.sketch_path,
            "strokes": [
                {"color": s.color, "pts": [[round(x, 2), round(y, 2), round(r, 3)] for x, y, r in s.pts]}
                for s in self.strokes
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        self.modified = False

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("format") != "tracofirme":
            raise ValueError("Arquivo não é um projeto do Traço Firme.")
        doc = cls(int(data["width"]), int(data["height"]), int(data.get("dpi", 300)))
        doc.sketch_path = data.get("sketch")
        doc.strokes = [Stroke([tuple(p) for p in s["pts"]], s.get("color", "#000000")) for s in data["strokes"]]
        return doc
