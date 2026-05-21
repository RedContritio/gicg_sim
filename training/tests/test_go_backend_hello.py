"""I29 P0 — GoActorBackend hello-world + 起停 lifecycle smoke。

Verify gate(per openspec/changes/i29-go-actor-pool/tasks.md T-0.7 + T-0.10):
1. ctypes load libgicg_actor + Go runtime init OK(``hello()`` 返 0)
2. start(N) → goroutine 起 → stop() → join < 2s 干净
3. 跑 100 次连续不 hang(防 SIGTERM handler missing 时 mp 关闭挂死)
4. 重复 start 抛 RuntimeError(idempotent error)
5. n_actors <= 0 抛 ValueError(fail-loud invariant)

Skip if libgicg_actor not built — CI 应 build 后才跑(build 命令 task T-0.3 文档化)。
"""

from __future__ import annotations

import os
import pytest

from training.core.actor.go_backend import GoActorBackend, _find_lib


def _lib_available() -> bool:
    try:
        _find_lib()
        return True
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(
    not _lib_available(),
    reason='libgicg_actor not built. Run `go build -buildmode=c-shared -o gicg_env/libgicg_actor.<dylib|dll|so> ./gicg_actor/capi` first.',
)


def test_hello_returns_zero():
    """ctypes load + Go runtime init OK → hello() 返 0。"""
    backend = GoActorBackend()
    assert backend.hello() == 0


def test_start_stop_single_actor():
    """N=1 起 → stop → join 干净。"""
    backend = GoActorBackend()
    backend.start(1)
    backend.stop()
    # Idempotent stop after stop → no-op。
    backend.stop()


def test_start_stop_multi_actor():
    """N=4 多 goroutine 起停。"""
    backend = GoActorBackend()
    backend.start(4)
    backend.stop()


@pytest.mark.skipif(
    os.environ.get('CI_FAST', '') == '1',
    reason='100x stress (CI_FAST=1 skips); local + CI 默认跑',
)
def test_start_stop_100_iter_no_hang():
    """T-0.10 verify gate:100 次连续 start+stop 不 hang。

    防 SIGTERM handler missing 时 mp 关闭挂死(memory: feedback_go_cgo_signal_handler)。
    每次 ~ms 级 wall,100 次总 < 5s wall。"""
    backend = GoActorBackend()
    for i in range(100):
        backend.start(2)
        backend.stop()


def test_invalid_n_raises():
    """n_actors <= 0 fail loud。"""
    backend = GoActorBackend()
    with pytest.raises(ValueError, match='must be positive'):
        backend.start(0)
    with pytest.raises(ValueError, match='must be positive'):
        backend.start(-1)


def test_double_start_raises():
    """重复 start(未先 stop)抛 RuntimeError。"""
    backend = GoActorBackend()
    backend.start(1)
    try:
        with pytest.raises(RuntimeError, match='already started'):
            backend.start(1)
    finally:
        backend.stop()
