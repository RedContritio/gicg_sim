> 分卷导航:回到 [← Part 1](2026-05-25-i29-redesign-implementation.md) · 续见 [Part 3](2026-05-25-i29-redesign-implementation-part3.md) → [Part 4](2026-05-25-i29-redesign-implementation-part4.md)

### Task 0.3: Python master spawner + SHMRing trans (轻 wrapper)

**Files:**
- Create: `training/core/actor/go_subprocess.py` — `GoSubprocessHandle` (spawn / wait_ready / alive / terminate / join API)
- Create: `training/core/actor/transition_shm_channel.py` — N-producer single-ring 封装 (薄 wrapper over `CrossLangShmRing`)
- Create: `training/core/actor/tests/test_go_subprocess_spawn.py` — spawn → READY → terminate cycle
- Create: `training/core/actor/tests/test_transition_shm_channel.py` — owner create + attach + push/try_pop

- [ ] **Step 1: 写 failing test for transition_shm_channel**

`training/core/actor/tests/test_transition_shm_channel.py`:

```python
"""I29 redesign P0.3 — transition SHM channel thin wrapper test."""

from training.core.actor.transition_shm_channel import TransitionShmChannel


def test_owner_create_then_external_attach():
    name = 'gicg_test_p03_trans'
    ch = TransitionShmChannel.create_owner(name, capacity=4, slot_size=64)
    try:
        # external attach (worker side)
        worker = TransitionShmChannel.attach_worker(name, capacity=4, slot_size=64)
        try:
            assert worker.push(b'hello world', client_id=0, req_id=1)
            item = ch.try_pop_with_meta()
            assert item is not None
            cid, rid, payload = item
            assert (cid, rid, payload) == (0, 1, b'hello world')
            # empty after pop
            assert ch.try_pop_with_meta() is None
        finally:
            worker.close()
    finally:
        ch.close()


def test_push_full_returns_false():
    name = 'gicg_test_p03_full'
    ch = TransitionShmChannel.create_owner(name, capacity=2, slot_size=16)
    try:
        worker = TransitionShmChannel.attach_worker(name, capacity=2, slot_size=16)
        try:
            assert worker.push(b'a')
            assert worker.push(b'b')
            assert not worker.push(b'c')  # full
        finally:
            worker.close()
    finally:
        ch.close()
```

- [ ] **Step 2: Write transition_shm_channel.py**

`training/core/actor/transition_shm_channel.py`:

```python
"""TransitionShmChannel — N-producer single-ring transition channel (I29 redesign).

Thin alias over training.core.actor.ipc.ring_shm.CrossLangShmRing。 把通用 ring 封成
specific 用例:N goroutine push transition,master driver single-thread try_pop ingest。

Wire format:payload 字节 = wire v3 episode-batch (gicg_actor/transition_wire.go encode)。
本 channel 不 decode,只搬运 raw bytes (decoder 在 paradigm-specific `_decoder.py`)。

Lifecycle:
- Master 端 create_owner (allocate SHM block + init header)
- Go subprocess attach_worker (经 stdin Config 传 name + capacity + slot_size)
- Master close() unlink SHM;worker close() 只 detach
"""

from __future__ import annotations

from typing import Optional

from training.core.actor.ipc.ring_shm import CrossLangShmRing


class TransitionShmChannel:
    """Single-ring N-producer transition channel。 owner = master,workers = Go goroutines。"""

    def __init__(self, ring: CrossLangShmRing) -> None:
        self._ring = ring

    @classmethod
    def create_owner(cls, name: str, *, capacity: int, slot_size: int) -> 'TransitionShmChannel':
        ring = CrossLangShmRing(name, capacity, slot_size, create=True)
        return cls(ring)

    @classmethod
    def attach_worker(cls, name: str, *, capacity: int, slot_size: int) -> 'TransitionShmChannel':
        ring = CrossLangShmRing(name, capacity, slot_size, create=False)
        return cls(ring)

    def push(self, payload: bytes, *, client_id: int = 0, req_id: int = 0) -> bool:
        return self._ring.push(payload, client_id=client_id, req_id=req_id)

    def try_pop(self) -> Optional[bytes]:
        return self._ring.try_pop()

    def try_pop_with_meta(self) -> Optional[tuple[int, int, bytes]]:
        return self._ring.try_pop_with_meta()

    def close(self) -> None:
        self._ring.close()

    def __enter__(self) -> 'TransitionShmChannel':
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
```

- [ ] **Step 3: Run test PASS**

Run: `.venv/bin/python -m pytest training/core/actor/tests/test_transition_shm_channel.py -v`
Expected: 2 PASS。 若 ring_shm lib 未 build,test 会在 SHM attach 时触发 _build_shm_lib 自动 build,首次 ~3-5s。

- [ ] **Step 4: 写 failing test for go_subprocess spawner**

`training/core/actor/tests/test_go_subprocess_spawn.py`:

```python
"""I29 redesign P0.3 — Go subprocess spawner test (uses bin/gicg_actor binary)."""

import os
import subprocess
import time
from pathlib import Path

import pytest

from training.core.actor.go_subprocess import GoSubprocessHandle

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BIN = _REPO_ROOT / 'bin' / 'gicg_actor'


@pytest.fixture(scope='module', autouse=True)
def build_go_binary():
    """Build cmd/gicg_actor once per module."""
    _BIN.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ['go', 'build', '-o', str(_BIN), './cmd/gicg_actor'],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.skip(f'go build failed: {r.stderr}')


def test_spawn_wait_ready_terminate():
    cfg = {
        'n_actors': 1,
        'trans_shm_name': 'gicg_test_spawn_p03',
        'trans_shm_capacity': 4,
        'trans_shm_slot_size': 64,
    }
    h = GoSubprocessHandle.spawn(str(_BIN), cfg, ready_timeout_s=10.0)
    try:
        assert h.alive()
    finally:
        h.terminate(timeout_s=5.0)
    assert not h.alive()
    assert h.returncode is not None
    # SIGTERM exit code 0 (graceful)
    assert h.returncode == 0


def test_spawn_invalid_config_fails():
    cfg = {'n_actors': 0}  # invalid
    with pytest.raises(RuntimeError, match='Go subprocess exit'):
        GoSubprocessHandle.spawn(str(_BIN), cfg, ready_timeout_s=5.0)
```

- [ ] **Step 5: Write go_subprocess.py**

`training/core/actor/go_subprocess.py`:

```python
"""GoSubprocessHandle — Python spawner for cmd/gicg_actor standalone executable.

I29 redesign 2026-05-25。 master Python 用 subprocess.Popen spawn Go binary,经 stdin
传 Config JSON,等 subprocess 输出一行 "READY" 表示初始化完毕。 lifecycle:
spawn → wait_ready → run → terminate (SIGTERM + timeout SIGKILL) → join。
"""

from __future__ import annotations

import json
import signal
import subprocess
import time
from typing import Any, Optional


class GoSubprocessHandle:
    """Handle for a running Go-actor subprocess。 Not thread-safe; one handle per process."""

    def __init__(self, proc: subprocess.Popen) -> None:
        self._proc = proc
        self.returncode: Optional[int] = None

    @classmethod
    def spawn(
        cls,
        binary_path: str,
        config: dict[str, Any],
        *,
        ready_timeout_s: float = 30.0,
    ) -> 'GoSubprocessHandle':
        """Spawn Go subprocess + write Config JSON to stdin + wait 'READY' on stdout。

        Fail-loud:若 ready_timeout_s 内 subprocess 退出或未输出 READY,raise RuntimeError
        含 stderr 完整内容。
        """
        proc = subprocess.Popen(
            [binary_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
        )
        # Write Config JSON + close stdin → Go parseConfig returns.
        assert proc.stdin is not None
        try:
            proc.stdin.write(json.dumps(config) + '\n')
            proc.stdin.flush()
            proc.stdin.close()
        except BrokenPipeError:
            pass  # subprocess died before write — handled by readline below

        # Wait READY on stdout (line-buffered)
        deadline = time.monotonic() + ready_timeout_s
        assert proc.stdout is not None
        while True:
            if proc.poll() is not None:
                # subprocess exited before READY
                stderr = proc.stderr.read() if proc.stderr else ''
                raise RuntimeError(f'Go subprocess exited (rc={proc.returncode}) before READY: {stderr}')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                proc.wait(timeout=5.0)
                raise RuntimeError(f'Go subprocess did not signal READY within {ready_timeout_s}s')
            # Non-blocking peek by polling subprocess + readline (blocks until line)。
            # 简化:用 select 等 stdout 可读;Mac/Linux 都支持。
            import select
            r, _, _ = select.select([proc.stdout], [], [], min(remaining, 0.1))
            if not r:
                continue
            line = proc.stdout.readline()
            if line == '':
                # EOF — subprocess closed stdout
                continue
            line = line.strip()
            if line == 'READY':
                break
            # else: 其他 stdout (warnings etc) — 透传到 master stderr。
            print(f'[gicg_actor stdout] {line}', flush=True)

        return cls(proc)

    def alive(self) -> bool:
        if self._proc.poll() is None:
            return True
        self.returncode = self._proc.returncode
        return False

    def terminate(self, *, timeout_s: float = 10.0) -> None:
        """SIGTERM + wait + SIGKILL fallback。"""
        if not self.alive():
            return
        self._proc.send_signal(signal.SIGTERM)
        try:
            self.returncode = self._proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self.returncode = self._proc.wait(timeout=5.0)
```

- [ ] **Step 6: Run test PASS**

Run: `.venv/bin/python -m pytest training/core/actor/tests/test_go_subprocess_spawn.py -v`
Expected: 2 PASS (build_go_binary fixture builds bin/gicg_actor first)

- [ ] **Step 7: Commit**

```bash
git add training/core/actor/go_subprocess.py training/core/actor/transition_shm_channel.py training/core/actor/tests/test_go_subprocess_spawn.py training/core/actor/tests/test_transition_shm_channel.py
git commit -F - <<'COMMIT_MSG'
training/core/actor: P0.2 Python spawner + transition SHM channel — I29 redesign

GoSubprocessHandle.spawn / wait_ready / terminate API (subprocess.Popen + stdin JSON + stdout READY)。
TransitionShmChannel thin wrapper over CrossLangShmRing (Phase 1-4 verified infra)。
打底 master 不参与 IPC 的架构 (deal-breaker #1)。

training/core/actor/go_subprocess.py 90 LOC
training/core/actor/transition_shm_channel.py 50 LOC
test_go_subprocess_spawn.py 2 test PASS (Mac smoke build + SIGTERM exit 0)
test_transition_shm_channel.py 2 test PASS (owner create + worker attach + push/pop)
COMMIT_MSG
```
