"""Entrada da mesa via WinTab (wintab32.dll), para drivers em que o Windows Ink não
entrega pressão. O Qt 6 não expõe mais o WinTab, então a DLL é lida direto por ctypes
e a fila de pacotes é esvaziada por um timer, alimentando o mesmo Canvas.pen_*."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes as wt

from PySide6.QtCore import QObject, QPointF, Qt, QTimer
from PySide6.QtWidgets import QApplication

from .diag import log

WTI_DEFSYSCTX = 4
WTI_DEVICES = 100
WTI_CURSORS = 200
DVC_NPRESSURE = 15
CSR_NAME = 1

PK_STATUS = 0x0002
PK_CURSOR = 0x0020
PK_BUTTONS = 0x0040
PK_X = 0x0080
PK_Y = 0x0100
PK_NORMAL_PRESSURE = 0x0400
PACKETDATA = PK_STATUS | PK_CURSOR | PK_BUTTONS | PK_X | PK_Y | PK_NORMAL_PRESSURE

QUEUE_SIZE = 256


class LOGCONTEXTW(ctypes.Structure):
    _fields_ = [
        ("lcName", wt.WCHAR * 40),
        ("lcOptions", wt.UINT),
        ("lcStatus", wt.UINT),
        ("lcLocks", wt.UINT),
        ("lcMsgBase", wt.UINT),
        ("lcDevice", wt.UINT),
        ("lcPktRate", wt.UINT),
        ("lcPktData", wt.DWORD),
        ("lcPktMode", wt.DWORD),
        ("lcMoveMask", wt.DWORD),
        ("lcBtnDnMask", wt.DWORD),
        ("lcBtnUpMask", wt.DWORD),
        ("lcInOrgX", wt.LONG), ("lcInOrgY", wt.LONG), ("lcInOrgZ", wt.LONG),
        ("lcInExtX", wt.LONG), ("lcInExtY", wt.LONG), ("lcInExtZ", wt.LONG),
        ("lcOutOrgX", wt.LONG), ("lcOutOrgY", wt.LONG), ("lcOutOrgZ", wt.LONG),
        ("lcOutExtX", wt.LONG), ("lcOutExtY", wt.LONG), ("lcOutExtZ", wt.LONG),
        ("lcSensX", wt.DWORD), ("lcSensY", wt.DWORD), ("lcSensZ", wt.DWORD),
        ("lcSysMode", wt.BOOL),
        ("lcSysOrgX", ctypes.c_int), ("lcSysOrgY", ctypes.c_int),
        ("lcSysExtX", ctypes.c_int), ("lcSysExtY", ctypes.c_int),
        ("lcSysSensX", wt.DWORD), ("lcSysSensY", wt.DWORD),
    ]


class AXIS(ctypes.Structure):
    _fields_ = [("axMin", wt.LONG), ("axMax", wt.LONG), ("axUnits", wt.UINT), ("axResolution", wt.DWORD)]


class PACKET(ctypes.Structure):
    # A ordem dos campos segue a ordem dos bits PK_* em PACKETDATA.
    _fields_ = [
        ("pkStatus", wt.UINT),
        ("pkCursor", wt.UINT),
        ("pkButtons", wt.DWORD),
        ("pkX", wt.LONG),
        ("pkY", wt.LONG),
        ("pkNormalPressure", wt.UINT),
    ]


class WinTabInput(QObject):
    def __init__(self, window, canvas):
        super().__init__(window)
        self.window = window
        self.canvas = canvas
        self._dll = None
        self._ctx = None
        self._down = False
        self._eraser_cache = {}
        self._timer = QTimer(self, interval=4, timerType=Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._poll)
        self._buf = (PACKET * QUEUE_SIZE)()

    def start(self):
        """Abre o contexto WinTab. Retorna (ok, mensagem)."""
        if sys.platform != "win32":
            return False, "WinTab só existe no Windows."
        try:
            dll = ctypes.WinDLL("wintab32.dll")
        except OSError:
            return False, ("wintab32.dll não encontrada. O driver da mesa não instalou suporte a WinTab; "
                           "use Windows Ink.")
        dll.WTInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p]
        dll.WTInfoW.restype = wt.UINT
        dll.WTOpenW.argtypes = [wt.HWND, ctypes.POINTER(LOGCONTEXTW), wt.BOOL]
        dll.WTOpenW.restype = wt.HANDLE
        dll.WTClose.argtypes = [wt.HANDLE]
        dll.WTClose.restype = wt.BOOL
        dll.WTPacketsGet.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p]
        dll.WTPacketsGet.restype = ctypes.c_int
        dll.WTQueueSizeSet.argtypes = [wt.HANDLE, ctypes.c_int]
        dll.WTQueueSizeSet.restype = wt.BOOL
        if not dll.WTInfoW(0, 0, None):
            return False, "O serviço WinTab não está disponível (mesa desconectada ou driver parado)."

        lc = LOGCONTEXTW()
        dll.WTInfoW(WTI_DEFSYSCTX, 0, ctypes.byref(lc))
        lc.lcName = "TracoFirme"
        lc.lcPktData = PACKETDATA
        lc.lcPktMode = 0  # tudo absoluto; botões como máscara de bits
        lc.lcMoveMask = PACKETDATA
        # Saída na resolução nativa da mesa; o mapeamento para a tela é feito em _to_widget.
        lc.lcOutOrgX, lc.lcOutOrgY = lc.lcInOrgX, lc.lcInOrgY
        lc.lcOutExtX, lc.lcOutExtY = lc.lcInExtX, lc.lcInExtY

        pressure = AXIS()
        dll.WTInfoW(WTI_DEVICES, DVC_NPRESSURE, ctypes.byref(pressure))
        self._p_min = pressure.axMin
        self._p_range = max(1, pressure.axMax - pressure.axMin)

        ctx = dll.WTOpenW(wt.HWND(int(self.window.winId())), ctypes.byref(lc), True)
        if not ctx:
            return False, "Não foi possível abrir o contexto WinTab."
        size = QUEUE_SIZE
        while size >= 16 and not dll.WTQueueSizeSet(ctx, size):
            size //= 2
        log.event("wintab_open", in_org=[lc.lcInOrgX, lc.lcInOrgY], in_ext=[lc.lcInExtX, lc.lcInExtY],
                  sys_org=[lc.lcSysOrgX, lc.lcSysOrgY], sys_ext=[lc.lcSysExtX, lc.lcSysExtY],
                  p_min=pressure.axMin, p_max=pressure.axMax, queue=size)
        self._dll, self._ctx, self._lc = dll, ctx, lc
        self._down = False
        self.canvas.wintab_mode = True
        self._timer.start()
        return True, "WinTab ativo."

    def stop(self):
        self._timer.stop()
        if self._down:
            self.canvas.pen_release(QPointF())
            self._down = False
        if self._ctx:
            self._dll.WTClose(self._ctx)
        self._ctx = None
        self.canvas.wintab_mode = False

    def _is_eraser(self, cursor):
        if cursor not in self._eraser_cache:
            buf = ctypes.create_unicode_buffer(128)
            self._dll.WTInfoW(WTI_CURSORS + cursor, CSR_NAME, buf)
            name = buf.value.lower()
            self._eraser_cache[cursor] = ("eraser" in name or "borracha" in name) if name else cursor % 3 == 2
        return self._eraser_cache[cursor]

    def _to_widget(self, pk):
        lc = self._lc
        nx = (pk.pkX - lc.lcOutOrgX) / max(1, lc.lcOutExtX)
        ny = 1.0 - (pk.pkY - lc.lcOutOrgY) / max(1, lc.lcOutExtY)  # WinTab tem origem embaixo
        sx = lc.lcSysOrgX + nx * lc.lcSysExtX
        sy = lc.lcSysOrgY + ny * lc.lcSysExtY
        origin = wt.POINT(0, 0)
        ctypes.windll.user32.ClientToScreen(wt.HWND(int(self.window.winId())), ctypes.byref(origin))
        dpr = self.window.devicePixelRatioF()
        local = QPointF((sx - origin.x) / dpr, (sy - origin.y) / dpr)
        return self.canvas.mapFrom(self.window, local)

    def _poll(self):
        if not self._ctx:
            return
        while True:
            n = self._dll.WTPacketsGet(self._ctx, QUEUE_SIZE, self._buf)
            if n <= 0:
                return
            for i in range(n):
                self._handle(self._buf[i])

    def _handle(self, pk):
        pos = self._to_widget(pk)
        pressure = min(1.0, max(0.0, (pk.pkNormalPressure - self._p_min) / self._p_range))
        eraser = self._is_eraser(pk.pkCursor)
        down = bool(pk.pkButtons & 1) or pressure > 0.01
        inside = self.canvas.rect().contains(pos.toPoint())
        active = QApplication.activeWindow() is self.window
        if log.enabled:
            log.event("wt_move" if (down or self._down) else "wt_hover", x=pos.x(), y=pos.y(), p=pressure,
                      raw_x=pk.pkX, raw_y=pk.pkY, raw_p=pk.pkNormalPressure, btn=pk.pkButtons,
                      cursor=pk.pkCursor, inside=inside, active=active)
        if inside or self._down:
            self.canvas.mark_tablet_activity()
        if down and not self._down:
            if inside and active:
                self._down = True
                pan = bool(pk.pkButtons & 0b110)  # botões laterais da caneta
                self.canvas.pen_press(pos, pressure, eraser=eraser, source="WinTab", pan=pan,
                                      modifiers=QApplication.keyboardModifiers())
        elif down and self._down:
            self.canvas.pen_move(pos, pressure, modifiers=QApplication.keyboardModifiers(), source="WinTab")
        elif not down and self._down:
            self._down = False
            self.canvas.pen_release(pos)
        elif inside and active:
            self.canvas.pen_hover(pos, eraser=eraser, source="WinTab", pressure=pressure)
