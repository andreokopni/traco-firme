"""Ajustes do Windows Ink para a janela: desliga o "pressionar e segurar = clique
direito", os círculos de feedback e os gestos (flicks), que atrapalham o desenho."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes as wt

TABLET_DISABLE_PRESSANDHOLD = 0x00000001
TABLET_DISABLE_PENTAPFEEDBACK = 0x00000008
TABLET_DISABLE_PENBARRELFEEDBACK = 0x00000010
TABLET_DISABLE_FLICKS = 0x00010000
FEEDBACK_TYPES = range(1, 12)  # FEEDBACK_TOUCH_CONTACTVISUALIZATION .. FEEDBACK_GESTURE_PRESSANDTAP


def disable_pen_feedback(hwnd: int):
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    flags = (TABLET_DISABLE_PRESSANDHOLD | TABLET_DISABLE_PENTAPFEEDBACK
             | TABLET_DISABLE_PENBARRELFEEDBACK | TABLET_DISABLE_FLICKS)
    user32.SetPropW.argtypes = [wt.HWND, wt.LPCWSTR, wt.HANDLE]
    user32.SetPropW(hwnd, "MicrosoftTabletPenServiceProperty", flags)
    try:
        set_feedback = user32.SetWindowFeedbackSetting
    except AttributeError:
        return
    set_feedback.argtypes = [wt.HWND, ctypes.c_int, wt.DWORD, wt.UINT, ctypes.c_void_p]
    off = wt.BOOL(False)
    for ft in FEEDBACK_TYPES:
        set_feedback(hwnd, ft, 0, ctypes.sizeof(off), ctypes.byref(off))
