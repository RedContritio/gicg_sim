"""Optional ctypes prototypes for newer libgicg builds."""

from __future__ import annotations

import ctypes


def setup_optional_apis(lib) -> bool:
    try:
        lib.GameSelectGreedyAction.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_longlong,
        ]
        lib.GameSelectGreedyAction.restype = ctypes.c_int
        return True
    except AttributeError:
        return False
