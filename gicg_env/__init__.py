"""gicg_env — Python binding for the Go gicg engine.

Public surface: ``GicgEngine`` + ``GicgEnv``. Both are loaded lazily via
PEP 562 module ``__getattr__`` so importing ``gicg_env._constants`` (or
any other sub-module that does not need the cgo lib) does NOT trigger
``ctypes.CDLL(libgicg.dylib)``. This is load-bearing for the I29 DMC
master-process invariant: the master orchestrator imports buffer / obs
schema constants from ``gicg_env._constants`` but MUST NOT load libgicg
(cgo state belongs in the spawned subprocess only — see
``training/paradigms/dmc/tests/test_go_subprocess_5ep_e2e.py`` lsof
guard).
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-checker only
    from .engine import GicgEngine
    from .env import GicgEnv

__all__ = ['GicgEngine', 'GicgEnv']


def __getattr__(name: str):
    if name == 'GicgEngine':
        from .engine import GicgEngine

        return GicgEngine
    if name == 'GicgEnv':
        from .env import GicgEnv

        return GicgEnv
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
