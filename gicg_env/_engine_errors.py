"""Raise sticky DSL execution failures at every handle-based ctypes boundary."""

import ctypes


def raise_rule_error(lib, handle):
    size = lib.GameGetRuleError(handle, None, 0)
    if size:
        message = ctypes.create_string_buffer(size + 1)
        lib.GameGetRuleError(handle, message, len(message))
        raise RuntimeError(message.value.decode('utf-8', errors='replace'))


def install_rule_error_checks(lib):
    lib.GameGetRuleError.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    lib.GameGetRuleError.restype = ctypes.c_int

    def check(result, func, args):
        raise_rule_error(lib, args[0])
        return result

    for name, func in vars(lib).copy().items():
        if name in ('GameGetRuleError', 'GameSnapshotFree', 'GameFree'):
            continue
        types = getattr(func, 'argtypes', None)
        if name.startswith('Game') and types and types[0] is ctypes.c_int:
            func.errcheck = check
