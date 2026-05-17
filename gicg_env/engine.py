"""Python bindings for the GICG game engine via ctypes."""

import ctypes
import json
import os
import numpy as np
from pathlib import Path

# Module-level constants (dice color count, phase / step / action
# enums) live in gicg_env._constants so the mixin modules can import
# them without a circular dependency on this module. Re-exported
# here for backward compat — existing
# ``from gicg_env.engine import DICE_COLOR_COUNT`` / PHASE_X / etc.
# call sites keep working.
from gicg_env._constants import (
    ACTION_CARD,
    ACTION_END_TURN,
    ACTION_SKILL,
    ACTION_SWITCH,
    DICE_COLOR_COUNT,
    PHASE_ACTION,
    PHASE_GAME_OVER,
    PHASE_ROUND_END,
    PHASE_ROUND_START,
    PHASE_SELECT_ACTIVE,
    STEP_CONTINUE,
    STEP_GAME_OVER,
    STEP_NEED_TARGET,
)


def _find_lib():
    """Find the shared library, platform-aware.

    Linux container with host repo bind-mounted will see the host's
    .dylib in ``gicg_env/``; loading it fails with "invalid ELF header".
    So on Linux we look at ``/usr/local/lib/libgicg.so`` (Dockerfile-
    installed, out of bind-mount range) FIRST and skip .dylib entirely.

      Linux:   /usr/local/lib/libgicg.so       (container default)
               <here>/libgicg.so               (locally built fallback)
      Darwin:  <here>/libgicg.dylib            (host build)
               <here>/libgicg.so               (rare local fallback)
      Windows: <here>/libgicg.dll              (cgo MinGW build)
    """
    import sys

    here = Path(__file__).resolve().parent
    if sys.platform.startswith('linux'):
        candidates = [
            Path('/usr/local/lib/libgicg.so'),
            here / 'libgicg.so',
        ]
    elif sys.platform == 'win32':
        candidates = [
            here / 'libgicg.dll',
        ]
    else:
        candidates = [
            here / 'libgicg.dylib',
            here / 'libgicg.so',
        ]
    for c in candidates:
        if c.exists():
            return str(c)
    ext_hint = {'linux': 'so', 'win32': 'dll'}.get(sys.platform, 'dylib')
    raise FileNotFoundError(
        f'libgicg not found in {here} or /usr/local/lib. Build with: '
        f'cd gicg_engine && go build -buildmode=c-shared -o ../gicg_env/libgicg.{ext_hint} ./capi/'
    )


def preload_dsl(data_dir: str = 'data') -> None:
    """Eagerly read + parse every .lua file under ``data_dir`` into
    the engine's DSL cache. Call this once at the start of training
    (before spawning workers / creating envs) so every subsequent
    GameNew hits a fully-populated cache and is immune to mid-run
    DSL edits.

    Without preload the cache still fills lazily — the first
    GameNew for each worker reads all files from disk and populates
    — but there's a race window between "training has started" and
    "cache is full" during which an edit can corrupt a worker's
    read. Preload eliminates that window.

    Idempotent: cache hits on re-preload skip all work.
    """
    lib = ctypes.CDLL(_find_lib())
    lib.DSLPreload.argtypes = [ctypes.c_char_p]
    lib.DSLPreload.restype = ctypes.c_int
    rc = lib.DSLPreload(str(data_dir).encode('utf-8'))
    if rc != 0:
        raise RuntimeError(f'DSLPreload failed (rc={rc}) for data_dir={data_dir!r}')


from gicg_env._engine_actions import _ActionsMixin
from gicg_env._engine_api import _ApiMixin
from gicg_env._engine_lifecycle import _LifecycleMixin
from gicg_env._engine_queries import _QueriesMixin
from gicg_env.engine_pool_queries import _PoolQueriesMixin


class GicgEngine(_LifecycleMixin, _ApiMixin, _ActionsMixin, _QueriesMixin, _PoolQueriesMixin):
    """Wrapper around the C API for the GICG card game engine.

    Method implementations live in sibling mixin modules to keep any
    one file under the 300-line cap:

      _engine_api.py        — _setup_api (ctypes argtypes / restypes)
      _engine_lifecycle.py  — __init__, new_game, snapshot / restore /
                              clone, set_player_hand / deck / dice,
                              close / __enter__ / __exit__ / _check
      _engine_actions.py    — step, step_target, random_rollout,
                              legal action enumeration, refs / ids,
                              forced-switch detection
      _engine_queries.py    — counters, static / dynamic obs, phase /
                              winner / turn / acting_player, label
                              lists, replay / view export
      engine_pool_queries.py — hand / deck / discard refs & counts,
                              dice_total / dice_paid / dice_tuned_*

    MRO puts _LifecycleMixin first so its __init__ wins (it calls
    self._setup_api, which _ApiMixin provides).
    """

    pass


def record_extract_info(yaml_path: str, lib_path: str | None = None) -> dict:
    """Parse a replay YAML file and return {teams, total_steps, rounds,
    winner} without constructing a Game. Used by the web backend to
    size a replay slider and to build a matching GicgEnv for rewind
    requests. `lib_path` overrides auto-detection for test fixtures.

    Raises RuntimeError if the file can't be read, parsed, or is
    missing a round-start state."""
    if lib_path is None:
        lib_path = _find_lib()
    lib = ctypes.CDLL(lib_path)
    lib.RecordExtractInfoJSON.argtypes = [ctypes.c_char_p]
    lib.RecordExtractInfoJSON.restype = ctypes.c_void_p
    lib.GameFreeString.argtypes = [ctypes.c_void_p]
    lib.GameFreeString.restype = None
    ptr = lib.RecordExtractInfoJSON(yaml_path.encode('utf-8'))
    if not ptr:
        raise RuntimeError('RecordExtractInfoJSON returned null')
    try:
        s = ctypes.cast(ptr, ctypes.c_char_p).value
        if not s:
            raise RuntimeError('RecordExtractInfoJSON returned empty')
        data = json.loads(s.decode('utf-8'))
    finally:
        lib.GameFreeString(ptr)
    if 'error' in data:
        raise RuntimeError(f'record_extract_info {yaml_path}: {data["error"]}')
    return data
