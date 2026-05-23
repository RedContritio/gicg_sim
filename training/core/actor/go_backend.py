"""GoActorBackend — Python ctypes wrapper for libgicg_actor (I29 P0/P1.4)。

Loads ``libgicg_actor.dll/.dylib`` (built from ``gicg_actor/capi/``) and exposes
``hello`` / ``start_pool(n)`` / ``start_pool_v2(...)`` / ``stop_pool`` C API。

P0 入口:``start(n_actors)`` 起 N goroutine 占位(hello-world 用)。
P1.4 production 入口:``start_with_config(paradigm, n_actors, inf_addr, trans_addr,
paradigm_cfg)`` 起完整 episode loop pool。

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
import json
import sys
from pathlib import Path
from typing import Any, Optional


def _lib_filename() -> str:
    if sys.platform == 'win32':
        return 'libgicg_actor.dll'
    if sys.platform == 'darwin':
        return 'libgicg_actor.dylib'
    return 'libgicg_actor.so'  # linux


def _find_lib(override: Optional[str] = None) -> Path:
    """Search libgicg_actor in canonical build location (gicg_env/) + optional override。

    Post 2026-05-24:GICG_ACTOR_LIB env var 全砍 — cfg-driven only。 显式 override
    由 cfg.runtime.actor_lib_path 提供 (production cfg 不写则走 canonical path)。
    """
    if override:
        p = Path(override)
        if not p.exists():
            raise FileNotFoundError(f'cfg.runtime.actor_lib_path={override} but file missing')
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

    def __init__(self, lib_path: Optional[str] = None) -> None:
        """``lib_path``: optional explicit libgicg_actor path (post 2026-05-24
        cfg-driven only)。 None = canonical ``gicg_env/<libname>`` (走 _find_lib
        default)。 ``cfg.runtime.actor_lib_path`` 由 DMC go_collector 透传。

        CDLL caches by path,后续 ctor (无论 lib_path) 共享首次 load 的 handle。
        """
        if GoActorBackend._lib is None:
            lib_path = _find_lib(override=lib_path)
            lib = ctypes.CDLL(str(lib_path))
            # Bind C signatures — defensive(no implicit int truncation)。
            lib.gicg_actor_hello.restype = ctypes.c_int
            lib.gicg_actor_hello.argtypes = []
            lib.gicg_actor_start_pool.restype = ctypes.c_int
            lib.gicg_actor_start_pool.argtypes = [ctypes.c_int]
            lib.gicg_actor_start_pool_v2.restype = ctypes.c_int
            lib.gicg_actor_start_pool_v2.argtypes = [
                ctypes.c_char_p,  # paradigm_name
                ctypes.c_int,  # n_actors
                ctypes.c_char_p,  # inf_addr
                ctypes.c_char_p,  # trans_addr
                ctypes.c_char_p,  # paradigm_cfg_json
                ctypes.c_int,  # io_timeout_ms
            ]
            lib.gicg_actor_stop_pool.restype = ctypes.c_int
            lib.gicg_actor_stop_pool.argtypes = []
            lib.gicg_actor_alive_count.restype = ctypes.c_int
            lib.gicg_actor_alive_count.argtypes = []
            # Wire-layout introspection — Go↔Python wire header 交叉校验(I29 T-RR.8)。
            for _fn in (
                'gicg_actor_wire_version',
                'gicg_actor_transition_header_size',
                'gicg_actor_infer_request_header_size',
                'gicg_actor_infer_response_header_size',
            ):
                getattr(lib, _fn).restype = ctypes.c_int
                getattr(lib, _fn).argtypes = []
            GoActorBackend._lib = lib
        self._started = False
        # atexit 兜 Python 异常退出时 stop_pool — 防 Go goroutine 漏 / SHM 未 unmap。
        atexit.register(self._atexit_cleanup)

    def hello(self) -> int:
        """Smoke test:returns 0 if ctypes load + Go runtime init OK。"""
        return int(GoActorBackend._lib.gicg_actor_hello())

    def start(self, n_actors: int) -> None:
        """Spawn N actor goroutine — P0 占位入口(hello-world only)。 重复 start 抛。"""
        if n_actors <= 0:
            raise ValueError(f'GoActorBackend.start: n_actors must be positive, got {n_actors}')
        if self._started:
            raise RuntimeError('GoActorBackend.start: already started, call stop() first')
        rc = int(GoActorBackend._lib.gicg_actor_start_pool(n_actors))
        if rc != 0:
            raise RuntimeError(f'gicg_actor_start_pool({n_actors}) failed: rc={rc}')
        self._started = True

    def start_with_config(
        self,
        *,
        paradigm: str,
        n_actors: int,
        inf_addr: str,
        trans_addr: str,
        paradigm_cfg: dict[str, Any],
        io_timeout_ms: int = 30000,
    ) -> None:
        """Production 入口(P1.4 起)— spawn N actor 走指定 paradigm + InfServer / TransSink。

        paradigm_cfg 是 paradigm-specific config dict — 序列化成 JSON 透传给 Go side
        paradigm.Configure。 DMC schema(gicg_actor/dmc/paradigm.go:DMCConfig):
            {
              "game_spec": {pools, players[][chars][{name}], seed, ...},  # factory.GameConfig
              "opp_features": "F1" | "F2" | ...,
              "opp_depth": 1..4,
              "max_actions": 30,
              "max_episode_steps": 360,
              "my_player_strategy": "alternate" | "fixed_0" | "fixed_1",
              "base_seed": int,
              "epsilon": 0.05
            }

        rc 含义(参 gicg_actor/pool.go):
            1=already_running,2=invalid_n,3=unknown_paradigm,4=inf_connect_fail,
            5=trans_connect_fail,6=paradigm_configure_fail。
        """
        if n_actors <= 0:
            raise ValueError(f'GoActorBackend.start_with_config: n_actors must be positive, got {n_actors}')
        if self._started:
            raise RuntimeError('GoActorBackend.start_with_config: already started, call stop() first')
        if not paradigm:
            raise ValueError('GoActorBackend.start_with_config: paradigm name required')
        cfg_json = json.dumps(paradigm_cfg)
        rc = int(
            GoActorBackend._lib.gicg_actor_start_pool_v2(
                paradigm.encode('utf-8'),
                n_actors,
                (inf_addr or '').encode('utf-8'),
                (trans_addr or '').encode('utf-8'),
                cfg_json.encode('utf-8'),
                io_timeout_ms,
            )
        )
        if rc != 0:
            raise RuntimeError(
                f'gicg_actor_start_pool_v2(paradigm={paradigm}, n={n_actors}) failed: rc={rc}\n'
                f'  rc=1 already_running, 2 invalid_n, 3 unknown_paradigm, 4 inf_connect_fail, '
                f'5 trans_connect_fail, 6 paradigm_configure_fail'
            )
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

    def alive_count(self) -> int:
        """当前在跑的 actor goroutine 数。 pool 运行期间 < start 时的 n_actors 说明有
        actor 静默 fatal 死亡(I29 T-RR.7 — actor 死亡可见性)。 not-started 时返 0。"""
        if not self._started:
            return 0
        return int(GoActorBackend._lib.gicg_actor_alive_count())

    def wire_layout(self) -> dict[str, int]:
        """Go 侧 wire 协议 header 尺寸 + 版本 —— 供 Python 测试与 ``struct.calcsize``
        交叉校验,catch Go↔Python header 漂移(I29 T-RR.8)。 不需 start_pool。"""
        lib = GoActorBackend._lib
        return {
            'wire_version': int(lib.gicg_actor_wire_version()),
            'transition_header_size': int(lib.gicg_actor_transition_header_size()),
            'infer_request_header_size': int(lib.gicg_actor_infer_request_header_size()),
            'infer_response_header_size': int(lib.gicg_actor_infer_response_header_size()),
        }

    def _atexit_cleanup(self) -> None:
        """atexit hook — Python 退出兜 stop_pool,防 Go goroutine 漏。 异常吞掉
        (atexit 期间抛不可恢复)。"""
        try:
            self.stop()
        except Exception:  # noqa: BLE001 — atexit 不能抛
            pass
