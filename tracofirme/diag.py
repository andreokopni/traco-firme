"""Log de diagnóstico: grava em JSON Lines tudo o que a mesa envia e as decisões do
estabilizador, para reproduzir fora da máquina problemas que dependem do hardware."""
from __future__ import annotations

import json
import os
import time

LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "TracoFirme", "logs")
HOVER_INTERVAL = 0.1  # s entre registros de caneta pairando, para o arquivo não explodir
MAX_FILES = 20


class DiagLog:
    def __init__(self, enabled=False):
        self._f = None
        self.path = None
        self._t0 = time.monotonic()
        self._last_hover = 0.0
        self.enabled = False
        self.set_enabled(enabled)

    def set_enabled(self, enabled):
        if enabled and self._f is None:
            os.makedirs(LOG_DIR, exist_ok=True)
            self._prune()
            self.path = os.path.join(LOG_DIR, time.strftime("tracofirme-%Y%m%d-%H%M%S.jsonl"))
            self._f = open(self.path, "a", encoding="utf-8")
        elif not enabled and self._f is not None:
            self._f.close()
            self._f = None
        self.enabled = enabled

    def _prune(self):
        files = sorted(f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl"))
        for f in files[: max(0, len(files) - MAX_FILES + 1)]:
            try:
                os.remove(os.path.join(LOG_DIR, f))
            except OSError:
                pass

    def event(self, kind, **data):
        if self._f is None:
            return
        now = time.monotonic()
        if kind.endswith("hover"):
            if now - self._last_hover < HOVER_INTERVAL:
                return
            self._last_hover = now
        rec = {"t": round((now - self._t0) * 1000, 1), "k": kind}
        for key, value in data.items():
            rec[key] = round(value, 3) if isinstance(value, float) else value
        self._f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def flush(self):
        if self._f is not None:
            self._f.flush()

    def close(self):
        self.set_enabled(False)


log = DiagLog()
