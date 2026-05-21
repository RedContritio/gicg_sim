"""GoActorBackend — Python ctypes wrapper for libgicg_actor (I29 P0 scaffold).

Loads ``libgicg_actor.dll/.dylib`` (built from ``gicg_actor/capi/``) and exposes
``start_pool(n)`` / ``stop_pool()`` / ``hello()`` C API。 Phase 0 仅 hello-world
+ 起停;Phase 1 扩 production episode loop + transition SHM read + InfServer
socket 配置。

边界(参 openspec/changes/i29-go-actor-pool/design.md):
- 本 wrapper 不引入 RL 概念到 ``gicg_engine``;libgicg_actor 独立 c-shared,
  跟 libgicg(engine)各自含 Go runtime ~10 MB,保 ``gicg_engine = environment only``
- atexit hook 兜 process exit cleanup(防 Python 异常退出时 Go goroutine 漏)
- SIGTERM 已由 gicg_actor.init() Go side 装 no-op handler(memory:
  feedback_go_cgo_signal_handler)
"""

from __future__ import annotations

import atexit
import ctypes
import os
import sys
from pathlib import Path
from typing import Optional


def _lib_filename() -> str:
    if sys.platform == 'win32':
        return 'libgicg_actor.dll'
    if sys.platform == 'darwin':
        return 'libgicg_actor.dylib'
    return 'libgicg_actor.so'  # linux


def _find_lib() -> Path:
    """Search libgicg_actor in canonical build location (gicg_env/) + env override。"""
    env = os.environ.get('GICG_ACTOR_LIB')
    if env:
        p = Path(env)
        if not p.exists():
            raise FileNotFoundError(f'GICG_ACTOR_LIB={env} but file missing')
        return p
    # Canonical: gicg_env/<libname> relative to repo root.
    # __file__ = .../training/core/actor/go_backend.py → repo root 4 levels up.
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    p = repo_root / 'gicg_env' / _lib_filename()
    if not p.exists():
        raise FileNotFoundError(
            f'libgicg_actor not found at {p}. Build via:\n'
            f'  go build -buildmode=c-shared -o gicg_env/{_lib_filename()} ./gicg_actor/capi'
        )
    return p


class GoActorBackend:
    """ctypes wrapper around libgicg_actor — Phase 0 hello + start/stop only。

    Lazy-loads lib on first ctor; subsequent ctors share the same loaded handle
    (CDLL caches by path)。 ``start(n)`` 起 N actor goroutine,``stop()`` 优雅
    停 + join。 重复 start(未先 stop)返 lib 错误码 1 → raise RuntimeError。
    """

    _lib: Optional[ctypes.CDLL] = None

    def __init__(self) -> None:
        if GoActorBackend._lib is None:
            lib_path = _find_lib()
            lib = ctypes.CDLL(str(lib_path))
            # Bind C signatures — defensive(no implicit int truncation)。
            lib.gicg_actor_hello.restype = ctypes.c_int
            lib.gicg_actor_hello.argtypes = []
            lib.gicg_actor_start_pool.restype = ctypes.c_int
            lib.gicg_actor_start_pool.argtypes = [ctypes.c_int]
            lib.gicg_actor_stop_pool.restype = ctypes.c_int
            lib.gicg_actor_stop_pool.argtypes = []
            GoActorBackend._lib = lib
        self._started = False
        # atexit 兜 Python 异常退出时 stop_pool — 防 Go goroutine 漏 / SHM 未 unmap。
        atexit.register(self._atexit_cleanup)

    def hello(self) -> int:
        """Smoke test:returns 0 if ctypes load + Go runtime init OK。"""
        return int(GoActorBackend._lib.gicg_actor_hello())

    def start(self, n_actors: int) -> None:
        """Spawn N actor goroutine。 重复 start 抛。"""
        if n_actors <= 0:
            raise ValueError(f'GoActorBackend.start: n_actors must be positive, got {n_actors}')
        if self._started:
            raise RuntimeError('GoActorBackend.start: already started, call stop() first')
        rc = int(GoActorBackend._lib.gicg_actor_start_pool(n_actors))
        if rc != 0:
            raise RuntimeError(f'gicg_actor_start_pool({n_actors}) failed: rc={rc}')
        self._started = True

    def stop(self) -> None:
        """优雅停 + join 所有 actor goroutine。 not-started 时 no-op(idempotent)。"""
        if not self._started:
            return
        rc = int(GoActorBackend._lib.gicg_actor_stop_pool())
        if rc != 0:
            # rc=1 = not running on Go side(竞态:atexit 跟显式 stop 并发)→ 不抛
            if rc != 1:
                raise RuntimeError(f'gicg_actor_stop_pool() failed: rc={rc}')
        self._started = False

    def _atexit_cleanup(self) -> None:
        """atexit hook — Python 退出兜 stop_pool,防 Go goroutine 漏。 异常吞掉
        (atexit 期间抛不可恢复)。"""
        try:
            self.stop()
        except Exception:  # noqa: BLE001 — atexit 不能抛
            pass
