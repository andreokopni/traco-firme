"""Preferências do pincel e do estabilizador, persistidas com QSettings."""
from __future__ import annotations

from dataclasses import dataclass, fields

from PySide6.QtCore import QSettings

OBSOLETE_KEYS = ("diag_log", "stabilizer")  # o log não é lembrado; "stabilizer" virou stab_level


@dataclass
class Settings:
    tool: str = "brush"            # "brush" | "eraser"
    size: float = 6.0              # diâmetro máximo, em px do documento
    color: str = "#000000"
    min_ratio: float = 0.15        # espessura com pressão mínima (fração do tamanho)
    gamma: float = 1.0             # curva de pressão: <1 engrossa cedo, >1 engrossa tarde
    stab_level: float = 35.0       # 0–100: corda + filtro 1€ enquanto desenha
    smoothing: float = 10.0        # suavização ao soltar, em px de tela
    keep_corners: bool = True      # não arredondar cantos vivos ao suavizar
    taper: bool = True             # pontas finas
    close_gaps: bool = True        # emendar a ponta do traço em linhas próximas
    gap_px: float = 12.0           # distância (px de tela) para emendar
    finish_to_tip: bool = True     # completar o traço até onde a caneta saiu
    hold_snap: bool = True         # segurar parado no fim para endireitar
    hold_ms: int = 500
    eraser_size: float = 24.0      # diâmetro, em px do documento
    eraser_mode: str = "partial"   # "partial" | "stroke"
    sketch_opacity: float = 0.35
    input_backend: str = "ink"     # "ink" | "wintab"
    theme: str = "system"          # "system" | "light" | "dark" (só a interface; o papel é sempre branco)

    def cord_px(self):
        """Comprimento da corda do estabilizador, em px de tela."""
        return self.stab_level * 0.6

    @classmethod
    def load(cls):
        qs = QSettings()
        s = cls()
        for f in fields(cls):
            if qs.contains(f.name):
                default = getattr(s, f.name)
                value = qs.value(f.name)
                try:
                    if isinstance(default, bool):
                        value = value in (True, "true", "1", 1)
                    else:
                        value = type(default)(value)
                except (TypeError, ValueError):
                    continue
                setattr(s, f.name, value)
        s.stab_level = max(0.0, min(100.0, s.stab_level))
        return s

    def save(self):
        qs = QSettings()
        for key in OBSOLETE_KEYS:
            qs.remove(key)
        for f in fields(self):
            qs.setValue(f.name, getattr(self, f.name))
