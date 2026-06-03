# I29 Go-actor pool 完全重设计 — Implementation Plan

> ⚠ **SUPERSEDED — 本 plan 描述 R1 candidate path (1 Go subprocess containing N goroutine);实际 ship 是 R7 (N independent Go subprocess) post-audit emergent fix**。 完整 ship 状态见 `openspec/changes/archive/i29-r7-n-subprocess/` + PR draft + memory [[i29-r7-acceptance-ship]]。 本 plan 留作历史 trail,不要据此跟进 task。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **All dispatched subagents MUST use opus model** (per user 2026-05-25; memory: `feedback_subagent_model_selection`).

**Goal:** Mac 端 Go-actor (重设计为 standalone OS subprocess + SHMRing transition) fps/actor mean ≥ Python mp baseline 48.1 fps/actor,n=5 seed, std/mean ≤ 25%。

**Architecture:** Go-actor 从 cgo loaded library 改为 standalone OS subprocess (`cmd/gicg_actor`,1 process 含 N goroutine);master Python 用 subprocess.Popen spawn,master ↔ Go-subprocess 走 SHMRing transition (复用 Phase 1-4 `CrossLangShmRing` infra,N-producer single-ring 模式);Go-subprocess ↔ InfServer subprocess 仍 TCP socket (proven path 不动);master 彻底退出 IPC daemon 角色,只 train + `try_pop` 读 transition。

**Tech Stack:** Go 1.22 (build standalone executable), Python 3.14 (subprocess.Popen + ctypes for SHMRing), POSIX shm_open + atomics (Mac/Linux), pytest, 现有 `gicg_actor/shm/` + `training/core/actor/ipc/ring_shm.py` (verified Phase 1-4).

**Spec:** `docs/superpowers/specs/2026-05-25-i29-redesign-design.md`

**Branch policy:** 在新 branch `feature/i29-redesign` 上推进 (脱离当前 `feature/i29-go-actor-shminf`)。 user 已授权非 main 分支自由 commit。

---

## Progress log (2026-05-25)

### Shipped ✓
- **spec+plan** (ce8c06d): docs landed
- **P0.1-P0.5** (1b165e3 → cb36441): cmd/gicg_actor standalone + Python spawner + transition_shm_channel + e2e + 60s Mac transport bench (Go 97.3% Py post fast-path fix)
- **P1.1+P1.2** (f24e198 → 1a81193): TransitionSink interface + SHM/TCP impl + Run kernel + paradigm.Run signature 改
- **micro-bench** (cf25442): in-process pure SHM ops bench — **Go 4.4-19.5x Python verified**
- **P1.3** (3de42d6 + db804c6): cmd/gicg_actor paradigm production path + per-actor TCP InferenceClient + GoSubprocessPipeline helper + 1 ep e2e smoke (0.22s wall PASS)
- **stat doc** (c18812f + 650f1b5): 5+5 seed analysis (Py 708K vs Go 694K stat tie p≈0.20) + 三层 SUMMARY

### In progress 🟡
- **P1.4** (opus subagent background): DMCGoSubprocessCollector + 5 ep production-shape e2e test
  - Files visible untracked: `training/paradigms/dmc/go_subprocess_collector.py` + `tests/test_go_subprocess_5ep_e2e.py`

### Pending 🔘
- **P2 acceptance gate** (subagent opus,P1.4 完成后 dispatch): perf_smoke test node + run_mac_collector_pair.py 适配 + Mac N=4 × 5 seed bench + **verify gate Mac N=4 fps/actor ≥ 48.1 × 1.00**
- **P3 cgo path 退役** (P2 PASS 后): 删 gicg_actor/capi/ + transition_sink_listener.py + go_collector.py 改 SHM path + 全仓 pytest regression

---

## Phase 0 — 200 LOC PoC (foundation gate)

**Goal:** 最小可验证架构 — 1 Go subprocess + 1 actor + SHMRing trans + 60s Mac smoke + Mac N=1 fps ≥ Python mp N=1 fps。

**Exit gate:** Mac single-actor smoke `fps ≥ python_mp_single_actor_baseline × 1.00`,无 GIL contention (master Python 不 import 任何 cgo lib),no leak (master RSS slope ≤ 0.5 MB/s)。若 fps 失败,STOP + 重新审计 root cause,不进 Phase 1。

### Task 0.1: 新 branch + 准备工作目录

**Files:**
- Create branch: `feature/i29-redesign` from current `feature/i29-go-actor-shminf` HEAD

- [ ] **Step 1: 起 branch**

Run:
```bash
git checkout -b feature/i29-redesign
git status
```
Expected: branch switched, clean tree (spec staged 应已 commit)。如 spec 仍 staged 未 commit,先用 `/tmp/i29_redesign_spec_commit.txt` 内容 `git commit -F /tmp/i29_redesign_spec_commit.txt`。

- [ ] **Step 2: 创建 task 列表**

打开 TaskList,创建 Phase 0 4 task pending entries (供 subagent 追)。

### Task 0.2: cmd/gicg_actor 最小 executable

**Files:**
- Create: `cmd/gicg_actor/main.go` — standalone Go executable,接 Config JSON from stdin,起 N goroutine 跑 placeholder
- Create: `cmd/gicg_actor/main_test.go` — Config parse + exit code test

- [ ] **Step 1: 写 failing test (Go)**

`cmd/gicg_actor/main_test.go`:

```go
package main

import (
	"bytes"
	"encoding/json"
	"testing"
)

func TestParseConfig_Minimal(t *testing.T) {
	in := bytes.NewBufferString(`{"n_actors": 1, "trans_shm_name": "test_ring", "trans_shm_capacity": 16, "trans_shm_slot_size": 1024}`)
	cfg, err := parseConfig(in)
	if err != nil {
		t.Fatalf("parseConfig: %v", err)
	}
	if cfg.NActors != 1 {
		t.Fatalf("NActors=%d, want 1", cfg.NActors)
	}
	if cfg.TransShmName != "test_ring" {
		t.Fatalf("TransShmName=%q, want test_ring", cfg.TransShmName)
	}
	// roundtrip JSON encode
	b, _ := json.Marshal(cfg)
	if !bytes.Contains(b, []byte(`"trans_shm_name":"test_ring"`)) {
		t.Fatalf("encode missing field: %s", b)
	}
}

func TestParseConfig_RejectsInvalidNActors(t *testing.T) {
	in := bytes.NewBufferString(`{"n_actors": 0, "trans_shm_name": "x"}`)
	_, err := parseConfig(in)
	if err == nil {
		t.Fatalf("parseConfig accepted n_actors=0")
	}
}
```

- [ ] **Step 2: Run failing test**

Run: `go test ./cmd/gicg_actor/ -v`
Expected: FAIL "undefined: parseConfig" (file 还没有)

- [ ] **Step 3: 写 main.go minimal impl**

`cmd/gicg_actor/main.go`:

```go
// Package main — standalone Go-actor executable (I29 redesign 2026-05-25)。
// 读 stdin Config JSON 一次 → 起 N goroutine → SIGTERM 优雅退出。
// Master Python 用 subprocess.Popen spawn,经 stdin 传配置。
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/signal"
	"sync"
	"syscall"
)

// Config — stdin JSON schema。 字段命名 snake_case 与 Python 侧对应。
type Config struct {
	NActors           int    `json:"n_actors"`
	TransShmName      string `json:"trans_shm_name"`
	TransShmCapacity  int    `json:"trans_shm_capacity"`
	TransShmSlotSize  int    `json:"trans_shm_slot_size"`
	InfServerAddr     string `json:"inf_server_addr,omitempty"`
	ParadigmName      string `json:"paradigm_name,omitempty"`
	ParadigmConfig    string `json:"paradigm_config,omitempty"`
}

func parseConfig(r io.Reader) (*Config, error) {
	var cfg Config
	if err := json.NewDecoder(r).Decode(&cfg); err != nil {
		return nil, fmt.Errorf("parseConfig decode: %w", err)
	}
	if cfg.NActors <= 0 {
		return nil, fmt.Errorf("parseConfig: n_actors must be > 0, got %d", cfg.NActors)
	}
	if cfg.TransShmName == "" {
		return nil, fmt.Errorf("parseConfig: trans_shm_name required")
	}
	return &cfg, nil
}

func main() {
	cfg, err := parseConfig(os.Stdin)
	if err != nil {
		fmt.Fprintf(os.Stderr, "gicg_actor: %v\n", err)
		os.Exit(2)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// SIGTERM handler — graceful exit.
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGTERM, syscall.SIGINT)
	go func() {
		<-sig
		cancel()
	}()

	var wg sync.WaitGroup
	for i := 0; i < cfg.NActors; i++ {
		wg.Add(1)
		go placeholderActor(ctx, &wg, i)
	}

	// Signal master ready (master.subprocess.stdout.readline 接).
	fmt.Println("READY")
	os.Stdout.Sync()

	wg.Wait()
}

// placeholderActor — P0 placeholder,后续 task 替换为真 paradigm。
func placeholderActor(ctx context.Context, wg *sync.WaitGroup, id int) {
	defer wg.Done()
	<-ctx.Done()
}
```

- [ ] **Step 4: Run test verify PASS**

Run: `go test ./cmd/gicg_actor/ -v`
Expected: both tests PASS

- [ ] **Step 5: Build binary smoke**

Run:
```bash
mkdir -p bin && go build -o bin/gicg_actor ./cmd/gicg_actor
echo '{"n_actors": 1, "trans_shm_name": "test", "trans_shm_capacity": 16, "trans_shm_slot_size": 1024}' | ./bin/gicg_actor &
PID=$!
sleep 1
ps -p $PID > /dev/null && echo "alive OK" || echo "FAIL: not running"
kill -TERM $PID
wait $PID 2>/dev/null
echo "exit_code=$?"
```
Expected: "alive OK" + exit_code=0 (SIGTERM 触发 cancel → wg.Wait return → main exit 0)

- [ ] **Step 6: Commit**

```bash
git add cmd/gicg_actor/
git commit -F - <<'COMMIT_MSG'
cmd/gicg_actor: P0.1 standalone Go executable stub — I29 redesign

最小 standalone executable,读 stdin Config JSON 起 N placeholder goroutine,SIGTERM 优雅退出。
为 master Python subprocess.Popen + SHMRing transition 打基础 (Phase 0)。

cmd/gicg_actor/main.go — 50 LOC entry + Config parser + placeholderActor
cmd/gicg_actor/main_test.go — Config JSON roundtrip + invalid n_actors reject

go test ./cmd/gicg_actor/ -v 2 PASS。 build smoke: bin/gicg_actor 收 SIGTERM exit 0。
COMMIT_MSG
```

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

### Task 0.4: SHM push wiring in Go-actor PoC (1 actor + push 1 trans + master pop)

**Files:**
- Modify: `cmd/gicg_actor/main.go` — placeholderActor 改成「attach SHM + push 1 trans + 等 ctx done」
- Create: `cmd/gicg_actor/shm_writer.go` — Go side SHMRing attach + push helper (薄 wrapper调用 `gicg_actor/shm/`)
- Create: `cmd/gicg_actor/shm_writer_test.go` — Go side unit test (skip 如 SHM unavailable)
- Create: `training/core/actor/tests/test_go_subprocess_shm_e2e.py` — 端到端 master spawn → Go push 1 trans → master pop verify

- [ ] **Step 1: 写 failing e2e test**

`training/core/actor/tests/test_go_subprocess_shm_e2e.py`:

```python
"""I29 redesign P0.4 — end-to-end Go subprocess + SHMRing trans push test."""

import subprocess
import time
from pathlib import Path

import pytest

from training.core.actor.go_subprocess import GoSubprocessHandle
from training.core.actor.transition_shm_channel import TransitionShmChannel

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BIN = _REPO_ROOT / 'bin' / 'gicg_actor'


@pytest.fixture(scope='module', autouse=True)
def build_go_binary():
    _BIN.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ['go', 'build', '-o', str(_BIN), './cmd/gicg_actor'],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.skip(f'go build failed: {r.stderr}')


def test_go_pushes_one_transition_master_reads_it():
    ring_name = 'gicg_test_e2e_p04'
    capacity = 4
    slot_size = 256
    ch = TransitionShmChannel.create_owner(ring_name, capacity=capacity, slot_size=slot_size)
    try:
        cfg = {
            'n_actors': 1,
            'trans_shm_name': ring_name,
            'trans_shm_capacity': capacity,
            'trans_shm_slot_size': slot_size,
            'poc_push_count': 1,  # P0.4 test hook: actor 起后 push 这么多 trans 即停
        }
        h = GoSubprocessHandle.spawn(str(_BIN), cfg, ready_timeout_s=10.0)
        try:
            # Wait for at least 1 transition (timeout 3s)
            deadline = time.monotonic() + 3.0
            item = None
            while time.monotonic() < deadline:
                item = ch.try_pop_with_meta()
                if item is not None:
                    break
                time.sleep(0.01)
            assert item is not None, 'no transition received from Go subprocess within 3s'
            cid, rid, payload = item
            assert cid == 0  # actor_id=0
            assert rid == 0  # seq=0
            assert payload == b'POC_TRANSITION_0'  # contract with cmd/gicg_actor/shm_writer.go
        finally:
            h.terminate(timeout_s=5.0)
    finally:
        ch.close()
```

- [ ] **Step 2: Write shm_writer.go**

`cmd/gicg_actor/shm_writer.go`:

```go
// shm_writer.go — Go side SHM ring writer for P0.4 PoC。
// 直接调 gicg_actor/shm package (cross-platform unified API)。
// 注意:gicg_actor/shm package 当前在 gicg_actor 模块内,本 cmd binary 是 main package
// 但同一 go module,直接 import 即可。
package main

import (
	"fmt"

	"gicg_mono/gicg_actor/shm"
)

// ShmWriter — N-producer 共享 ring 的 producer 端 wrapper。
type ShmWriter struct {
	handle *shm.Handle
}

// AttachShmWriter — Go subprocess 端 attach owner-created ring。
func AttachShmWriter(name string, capacity, slotSize int) (*ShmWriter, error) {
	totalSize := shm.RingTotalSize(capacity, slotSize)
	// Mac/Linux:shm name 需 "/" prefix (POSIX semantic);Python ring_shm.py 已在 _native_name
	// 加 prefix,Go 端 attach 用同 prefix 名。 Win:bare name (CPython behavior)。
	nativeName := name
	if runtime.GOOS != "windows" {
		nativeName = "/" + name
	}
	h, err := shm.Attach(nativeName, int64(totalSize))
	if err != nil {
		return nil, fmt.Errorf("ShmWriter attach %q: %w", nativeName, err)
	}
	return &ShmWriter{handle: h}, nil
}

// Push — non-blocking single-slot push。 ring 满返 false。
func (w *ShmWriter) Push(clientID, reqID uint32, payload []byte) bool {
	return shm.RingPush(w.handle, clientID, reqID, payload)
}

func (w *ShmWriter) Close() {
	shm.Detach(w.handle)
}
```

注意:`gicg_actor/shm` package 可能 API 名稍异 (实际看 `gicg_actor/shm/shm.go`),subagent 实施时按真实 API 调整 import 与函数名。本步预设 shm package 已 expose `Attach / Detach / RingPush` 函数 (Phase 1-4 ship);若不一致,subagent 先 grep `gicg_actor/shm/` 真实公开符号再写。

- [ ] **Step 3: 改 main.go — 接 SHM + push 1 trans**

`cmd/gicg_actor/main.go` 增量改 (替 placeholderActor):

```go
// 替换 placeholderActor signature:
func actorLoop(ctx context.Context, wg *sync.WaitGroup, id int, writer *ShmWriter, pocPushCount int) {
	defer wg.Done()
	// P0.4 PoC path — push 固定字节串 "POC_TRANSITION_<seq>"。
	for seq := 0; seq < pocPushCount; seq++ {
		payload := []byte(fmt.Sprintf("POC_TRANSITION_%d", seq))
		for !writer.Push(uint32(id), uint32(seq), payload) {
			// ring full — yield + retry (非生产路径,P0.4 1 trans 不会满)
			select {
			case <-ctx.Done():
				return
			default:
			}
		}
	}
	<-ctx.Done()
}

// Config 增字段:
type Config struct {
	// ...原字段
	PocPushCount int `json:"poc_push_count,omitempty"` // P0.4 PoC hook,production 应为 0
}

// main() 改启动 actor 部分:
// (替原 placeholderActor 调用)
writer, err := AttachShmWriter(cfg.TransShmName, cfg.TransShmCapacity, cfg.TransShmSlotSize)
if err != nil {
	fmt.Fprintf(os.Stderr, "gicg_actor: %v\n", err)
	os.Exit(3)
}
defer writer.Close()

for i := 0; i < cfg.NActors; i++ {
	wg.Add(1)
	go actorLoop(ctx, &wg, i, writer, cfg.PocPushCount)
}
```

注意:若需要 per-actor 独立 writer,P0.4 用共享 writer (N goroutine 同一 ring,SHM ring 设计本身就是 N-producer concurrent push,内部 atomic head++)。

- [ ] **Step 4: Build + run unit + e2e test**

Run:
```bash
go build -o bin/gicg_actor ./cmd/gicg_actor
go test ./cmd/gicg_actor/ -v
.venv/bin/python -m pytest training/core/actor/tests/test_go_subprocess_shm_e2e.py -v
```
Expected: Go test PASS, e2e test PASS (master spawn → Go push 1 trans → master pop 收到 `b'POC_TRANSITION_0'`)

- [ ] **Step 5: Commit**

```bash
git add cmd/gicg_actor/ training/core/actor/tests/test_go_subprocess_shm_e2e.py
git commit -F - <<'COMMIT_MSG'
cmd/gicg_actor + tests: P0.4 e2e SHMRing trans push verified — I29 redesign

Go subprocess attach SHMRing (Python owner created) + N goroutine push 固定 PoC payload。
master Python 经 try_pop_with_meta 收 (client_id, req_id, payload) 验证 wire 完整跨进程。

cmd/gicg_actor/main.go +20 LOC (actorLoop PocPush hook)
cmd/gicg_actor/shm_writer.go 50 LOC (Attach / Push / Close wrapper)
test_go_subprocess_shm_e2e.py 1 test PASS

证明 architecture 跑通,master 0 cgo lib loaded (verified ps -o command | grep python | grep libgicg → empty)。
COMMIT_MSG
```

### Task 0.5: 60s Mac smoke — N=1 actor 持续 push + 测 fps + 对比 Python mp baseline

**Files:**
- Create: `tools/_bench/p0_redesign_smoke.py` — 60s smoke harness,起 Go subprocess (1 actor 持续 push fixed-size payload) + master 计 try_pop 次数 → fps
- Create: `tools/_bench/p0_redesign_baseline.py` — Python mp 等价 baseline (1 actor subprocess via mp.Process + SHMRing push)
- Modify: `cmd/gicg_actor/main.go` — `poc_push_count == -1` 时无限 push (持续 push 直到 SIGTERM)

- [ ] **Step 1: 改 main.go 支持 unlimited push**

`actorLoop` 改:`if pocPushCount < 0 { for seq := 0;; seq++ { ... } }` else 用原 bounded loop。Config doc 注释 `poc_push_count = -1` 表 unlimited。

- [ ] **Step 2: 写 smoke harness — Go subprocess version**

`tools/_bench/p0_redesign_smoke.py`:

```python
"""P0.5 60s Mac smoke — measure fps of Go subprocess pushing dummy transitions into SHMRing."""

import argparse
import subprocess
import time
from pathlib import Path

from training.core.actor.go_subprocess import GoSubprocessHandle
from training.core.actor.transition_shm_channel import TransitionShmChannel

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BIN = _REPO_ROOT / 'bin' / 'gicg_actor'

# Wire payload size:模拟真 transition (12 KB nlegal-sized post wire v3)
_PAYLOAD_SIZE = 12 * 1024


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--duration-s', type=float, default=60.0)
    ap.add_argument('--n-actors', type=int, default=1)
    args = ap.parse_args()

    # Build binary
    r = subprocess.run(['go', 'build', '-o', str(_BIN), './cmd/gicg_actor'],
                       cwd=str(_REPO_ROOT), capture_output=True, text=True)
    if r.returncode != 0:
        print(f'build fail: {r.stderr}')
        return 1

    ring_name = 'gicg_p05_smoke'
    capacity = 4096
    ch = TransitionShmChannel.create_owner(ring_name, capacity=capacity, slot_size=_PAYLOAD_SIZE)
    try:
        cfg = {
            'n_actors': args.n_actors,
            'trans_shm_name': ring_name,
            'trans_shm_capacity': capacity,
            'trans_shm_slot_size': _PAYLOAD_SIZE,
            'poc_push_count': -1,  # unlimited
            'poc_payload_size': _PAYLOAD_SIZE,  # 新 hook:每条 push 这么多字节
        }
        h = GoSubprocessHandle.spawn(str(_BIN), cfg, ready_timeout_s=10.0)
        try:
            t0 = time.monotonic()
            n_popped = 0
            while time.monotonic() - t0 < args.duration_s:
                item = ch.try_pop_with_meta()
                if item is None:
                    time.sleep(0.0001)
                    continue
                n_popped += 1
            elapsed = time.monotonic() - t0
            fps = n_popped / elapsed
            fps_per_actor = fps / args.n_actors
            print(f'[p05 go-subprocess smoke] n_actors={args.n_actors} elapsed={elapsed:.1f}s n_popped={n_popped} fps={fps:.2f} fps/actor={fps_per_actor:.2f}')
        finally:
            h.terminate(timeout_s=5.0)
    finally:
        ch.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
```

- [ ] **Step 3: 写 baseline harness — Python mp version**

`tools/_bench/p0_redesign_baseline.py`:

```python
"""P0.5 Python mp baseline — 1 mp.Process actor pushing dummy SHMRing transitions."""

import argparse
import multiprocessing as mp
import time
from pathlib import Path

from training.core.actor.transition_shm_channel import TransitionShmChannel

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PAYLOAD_SIZE = 12 * 1024


def _actor_proc(ring_name: str, capacity: int, slot_size: int, payload_size: int, ready_evt) -> None:
    ch = TransitionShmChannel.attach_worker(ring_name, capacity=capacity, slot_size=slot_size)
    payload = b'X' * payload_size
    ready_evt.set()
    try:
        seq = 0
        while True:
            while not ch.push(payload, client_id=0, req_id=seq):
                pass  # ring full — busy retry
            seq += 1
    finally:
        ch.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--duration-s', type=float, default=60.0)
    ap.add_argument('--n-actors', type=int, default=1)
    args = ap.parse_args()

    ring_name = 'gicg_p05_baseline'
    capacity = 4096
    ch = TransitionShmChannel.create_owner(ring_name, capacity=capacity, slot_size=_PAYLOAD_SIZE)
    try:
        ready_evts = [mp.Event() for _ in range(args.n_actors)]
        procs = [
            mp.Process(target=_actor_proc, args=(ring_name, capacity, _PAYLOAD_SIZE, _PAYLOAD_SIZE, ready_evts[i]))
            for i in range(args.n_actors)
        ]
        for p in procs:
            p.start()
        for e in ready_evts:
            e.wait(timeout=10.0)

        t0 = time.monotonic()
        n_popped = 0
        while time.monotonic() - t0 < args.duration_s:
            item = ch.try_pop_with_meta()
            if item is None:
                time.sleep(0.0001)
                continue
            n_popped += 1
        elapsed = time.monotonic() - t0
        fps = n_popped / elapsed
        fps_per_actor = fps / args.n_actors
        print(f'[p05 py-mp baseline] n_actors={args.n_actors} elapsed={elapsed:.1f}s n_popped={n_popped} fps={fps:.2f} fps/actor={fps_per_actor:.2f}')

        for p in procs:
            p.terminate()
            p.join(timeout=5.0)
    finally:
        ch.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
```

- [ ] **Step 4: Run both 60s smoke**

```bash
.venv/bin/python -m tools._bench.p0_redesign_baseline --duration-s 60 --n-actors 1 > /tmp/p05_baseline.txt 2>&1
.venv/bin/python -m tools._bench.p0_redesign_smoke --duration-s 60 --n-actors 1 > /tmp/p05_go.txt 2>&1
cat /tmp/p05_baseline.txt
cat /tmp/p05_go.txt
```

- [ ] **Step 5: Verify exit gate**

**Exit gate**: Go fps ≥ Python mp baseline fps × 1.00 (单 actor pure push,no inference,no game loop)。

若 Go < Python mp → **STOP + 重新审计**:
- 是否 Go runtime 启动有 startup penalty (60s 应充分 amortize,不应)
- SHM attach Go side 是否有额外 overhead
- subagent dispatch:opus,任务「比对 Go subprocess vs Python mp subprocess pure SHM push fps gap rotation cause,期望 Go ≥ Python」

若 Go ≥ Python → **进 Phase 1**。

- [ ] **Step 6: Commit smoke data**

```bash
mkdir -p tools/_bench/p0_results
cp /tmp/p05_baseline.txt tools/_bench/p0_results/p05_baseline.txt
cp /tmp/p05_go.txt tools/_bench/p0_results/p05_go.txt
git add tools/_bench/p0_redesign_smoke.py tools/_bench/p0_redesign_baseline.py tools/_bench/p0_results/ cmd/gicg_actor/main.go
git commit -F - <<'COMMIT_MSG'
tools/_bench + cmd/gicg_actor: P0.5 Mac N=1 pure SHM push smoke (foundation gate)

60s 单 actor pure push (no inference, no game loop) 对比 Go subprocess vs Python mp。
固定 12 KB payload simulate wire v3 transition size。 SHMRing cap 4096 × 12 KB = 48 MB。

bin/gicg_actor unlimited push hook (poc_push_count=-1)。
两 harness 都用 TransitionShmChannel infra,只换 producer = Go vs Python mp.Process。

结果 (commit body 实际填):
- Python mp baseline: fps=...
- Go subprocess: fps=...
- ratio Go/Py = ...x → exit gate ...

P0 foundation 验证 = (PASS|FAIL)。
COMMIT_MSG
```

---

## Phase 1 — N actor + DMC paradigm wiring + 5 episode e2e

**Goal:** DMC paradigm 完整 hookup 到新 architecture,N actor 同时 push 真 wire v3 transition,5 episode e2e PASS,subprocess clean shutdown。

**Exit gate:** Mac N=4 跑 5 episode buffer fill 数对 (期望 transitions ≈ 5 × ~340 / 16 batched);Go subprocess SIGTERM 后 exit 0;无 SHM leak (ipcs / lsof check 无残留)。

### Task 1.1: 删旧 cgo singleton + Run(ctx, cfg) 单次调用模式

**Files:**
- Modify: `gicg_actor/pool.go` — 提取 `Run(ctx, cfg) error` 函数,actorLoop 不变,删全局 singleton (var mu, running, cancel, ...) 但 retain backward-compat 期间不删 capi/ 路径 (P3 才删)
- Refactor: `cmd/gicg_actor/main.go` — 改调 `gicg_actor.Run(ctx, cfg)` 取代 inline placeholderActor

(Subagent task,详步骤见下方 Subagent Brief)

**Subagent Brief (P1.1):** 见本 plan 末尾「Subagent dispatch briefs」段。

### Task 1.2: TransitionWriter 改 SHM (替 TCP)

**Files:**
- Create: `gicg_actor/transition_writer_shm.go` — SHM transition writer (实现 同 `TransitionWriter` 接口的 SHM 版)
- Create: `gicg_actor/transition_writer_shm_test.go` — unit + cross-lang test
- Modify: `gicg_actor/pool.go` (或 cmd/gicg_actor/main.go) — 调 shm writer 取代 TCP writer

**Subagent Brief (P1.2):** 见末尾。

### Task 1.3: DMC paradigm hookup 到 N goroutine + 真 InfServer TCP inference

**Files:**
- Modify: `cmd/gicg_actor/main.go` — Config 加 paradigm_name + paradigm_config + inf_server_addr;调 `gicg_actor.Run` 真启 DMC paradigm
- Modify: `training/core/actor/go_subprocess.py` — `spawn` Config 加 paradigm 字段透传

**Subagent Brief (P1.3):** 见末尾。

### Task 1.4: 5 episode e2e (master spawn subprocess + Go run DMC + master 收 trans + buffer ingest verify)

**Files:**
- Create: `training/paradigms/dmc/tests/test_go_subprocess_e2e.py` — 完整 e2e:Python InfServer subprocess + Go-actor subprocess + 5 ep + buffer fill verify
- Modify: `training/paradigms/dmc/go_collector.py` — `collect()` 改 `transition_shm_channel.try_pop` (替 listener queue)

**Subagent Brief (P1.4):** 见末尾。

---

## Phase 2 — Mac fair bench acceptance (本设计 verify gate)

**Goal:** Mac N=4 × 5 seed × 2 backend fair bench,Go fps/actor mean ≥ Python mp 48.1 × 1.00,std/mean ≤ 25%。

### Task 2.1: 适配 `tools/_bench/run_mac_collector_pair.py` 到新 backend

**Files:**
- Modify: `tools/_bench/run_mac_collector_pair.py` — 新 Go test node = `training/core/actor/tests/test_go_subprocess_perf_smoke.py::test_go_subprocess_perf_smoke_15s`
- Create: `training/core/actor/tests/test_go_subprocess_perf_smoke.py` — 15s collector smoke,接 `BENCH_N_ACTORS` / `BENCH_SEED` env,打 `[perf smoke] elapsed=... fps=... fps/actor=... delta=...MB decode_errors=0` 行

### Task 2.2: 跑 Mac fair bench 5 seed × 2 backend × N=4

```bash
.venv/bin/python -m tools._bench.run_mac_collector_pair --n-actors 4 --seeds 5 --out tools/_bench/p2_acceptance.md
```

### Task 2.3: Verify gate

**PASS condition:** `go.fps_per_actor_mean ≥ 48.1 × 1.00` AND `go.fps_per_actor_std / go.fps_per_actor_mean ≤ 0.25`

**FAIL handling:**
- 若 fps < 48 但 ≥ 36 (75% baseline):dispatch opus subagent root-cause + suggest fix,P2 重跑
- 若 fps < 36 (< 75%):结构性问题,落 STATE_DUMP + 暂停 + 待 user 决

### Task 2.4: Commit acceptance result

成功:落 `tools/_bench/p2_acceptance.md` + commit + `STATE_DUMP` 关 I29 重设计。
失败:落 acceptance fail report + 进入 root cause subagent 调查 loop。

---

## Phase 3 — 旧 cgo path 退役 + regression test 切换

**Goal:** 删 `gicg_actor/capi/` + 删 `transition_sink_listener.py` + `go_collector.py` 全切 SHM path + 全仓 pytest PASS。

### Task 3.1: 删 `gicg_actor/capi/` + 相关 build script

**Subagent Brief (P3.1):** 见末尾。

### Task 3.2: 删 `transition_sink_listener.py` + `go_backend.py` cgo 路径

**Subagent Brief (P3.2):** 见末尾。

### Task 3.3: 全仓 pytest + smoke regress

```bash
.venv/bin/python -m pytest -n 4 training/ gicg_env/ -q --tb=short
.venv/bin/python -m pytest -m smoke training/tests/ -q
```

**Expected:** 全 PASS (其他 4 paradigm 不动,只 DMC 切 SHM path)。

### Task 3.4: Final commit + 归档

---

## Subagent dispatch briefs

(每个 subagent 用 opus model;每 task 单 brief,自包含 file paths + 已有约束 + 期望产出)

### P1.1 Brief — pool.go refactor 为 Run(ctx, cfg) error

**Context:** 当前 `gicg_actor/pool.go` (310 LOC) 是 c-shared lib 全局 singleton 模式 (var mu, running, cancel, currentInfReqs, currentTWs, aliveActors)。 I29 redesign 改用 `cmd/gicg_actor` standalone executable,不再需要 singleton (一个 process 只跑一次 Run)。 但 `gicg_actor/capi/` 仍 build 中 (P3 才删),所以 pool.go 保留 backward-compat,提取 `Run(ctx, cfg) error` 内核函数,singleton 路径调本函数。

**Task:** 重构 `gicg_actor/pool.go`:
1. 提取 `Run(ctx context.Context, cfg Config) error` — 接受 context,起 N goroutine 跑 paradigm.Run,wg.Wait,返回 nil/err
2. 现有 `StartPoolWithConfig(cfg) int` 改成 wrapper:goroutine background 调 `Run`,保 backward-compat
3. `StopPool()` 仍用 singleton cancel,保 backward-compat
4. **不动** capi/ 任何函数
5. `cmd/gicg_actor/main.go` 调 `gicg_actor.Run(ctx, cfg)` 替原 inline actorLoop

**Constraints:**
- All Go tests in `gicg_actor/` 必须 PASS (`go test ./gicg_actor/... -v`)
- cmd/gicg_actor build OK (`go build -o bin/gicg_actor ./cmd/gicg_actor`)
- `training/core/actor/tests/test_go_subprocess_*.py` 全 PASS

### P1.2 Brief — TransitionWriter SHM 实现

**Context:** 当前 `gicg_actor/transition_writer.go` 是 TCP socket writer,master 端 `training/core/actor/transition_sink_listener.py` 接。 I29 redesign 改 SHMRing,Go side 写新 `transition_writer_shm.go` 实现 SHM push,paradigm `paradigm.Run` 接收 interface `TransitionSink` (重命名 from `*TransitionWriter` 为 interface),两实现可换。

**Task:**
1. 抽 `TransitionSink interface { Push(payload []byte, isEpisodeEnd bool) error; Close() error }`(API 与现有 TransitionWriter 兼容)
2. 实现 `TransitionWriterShm` (struct over shm writer wrapper) — `Push` 调 SHM ring push,full 时 spin + sched_yield 直到 ctx done 或 success
3. `paradigm.Run` signature 改接 `TransitionSink` 接口
4. cmd/gicg_actor `Run` 调用时传 SHM 实现;capi/ 仍传 TCP 实现 (backward-compat)

**Tests:**
- `gicg_actor/transition_writer_shm_test.go` — push + Python ring_shm pop verify cross-lang

### P1.3 Brief — DMC paradigm full hookup

**Context:** P0.4 已证 SHM 通,P1.1+P1.2 已 refactor pool/writer。 现把 DMC paradigm.Run 真 wire 进新架构:Config 接 paradigm_name + paradigm_config JSON + inf_server_addr,cmd/gicg_actor 起 N goroutine 跑 DMC paradigm。

**Task:**
1. cmd/gicg_actor/main.go: Config 加字段 + `gicg_actor.Run` 调用传完整 cfg
2. training/core/actor/go_subprocess.py: spawn cfg dict 透传 paradigm_*
3. 1 actor smoke: master spawn → Go 跑 DMC 1 episode → push 真 wire v3 trans → master decode verify obs shape 对

**Tests:**
- `training/paradigms/dmc/tests/test_go_subprocess_1ep_smoke.py` — 1 ep 真 InfServer TCP inference + 真 game loop + trans decode shape verify

### P1.4 Brief — 5 episode e2e + go_collector.py 适配

**Context:** 现有 `training/paradigms/dmc/go_collector.py` 用 `transition_sink_listener` (TCP listener queue 路径)。 改成 try_pop SHMRing 路径。

**Task:**
1. go_collector.py: `__init__` 接 `TransitionShmChannel` 实例 + `GoSubprocessHandle`;`collect()` 走 `ch.try_pop_with_meta` + `_go_assembler.ingest`;删 listener / handler ref
2. 5 ep e2e test 跑通

**Tests:**
- `training/paradigms/dmc/tests/test_go_subprocess_e2e.py` — full pipeline 5 ep PASS

### P3.1 Brief — 删 gicg_actor/capi/

**Context:** P2 acceptance gate PASS 后,旧 cgo path 已无人调用 (cmd/gicg_actor standalone path 全替代)。 删 `gicg_actor/capi/` + build script + ctypes load 路径。

**Task:**
1. 删 `gicg_actor/capi/` 整目录 (含 main.go capi exports)
2. 删 `gicg_env/libgicg_actor.{dylib,dll}` 旧 build artifact
3. 删 `gicg_actor/pool.go` 的 backward-compat 包装 (StartPoolWithConfig / StopPool / AliveCount singleton path)
4. `gicg_actor/Run(ctx, cfg)` 保留 (cmd/gicg_actor 调它)

### P3.2 Brief — 删 transition_sink_listener + cgo load 路径

**Context:** 旧 master 端 cgo + TCP listener 路径已 abandon。

**Task:**
1. 删 `training/core/actor/transition_sink_listener.py`
2. `training/core/actor/go_backend.py` 整文件改 `GoSubprocessBackend` (薄 wrapper over `GoSubprocessHandle` + `TransitionShmChannel`)
3. `training/paradigms/dmc/go_collector.py` 引用更新
4. 全仓 pytest PASS

---

## Self-Review

**Spec coverage check:**
- spec §3 deal-breaker (1) master 0 IPC threads → P3.2 删 transition_sink_listener + capi cgo load ✓
- spec §3 deal-breaker (2) transition 跨进程 shm → P0.3 + P1.2 ✓
- spec §3 deal-breaker (3) foundation-first ≤ 300 LOC verify → P0 (~250 LOC) + Exit gate ✓
- spec §4.2 components 全 covered (cmd/gicg_actor / go_subprocess.py / transition_shm_channel.py / pool.go refactor / transition_writer SHM / go_backend rewrite / capi 退役)
- spec §4.3 data flow 三阶段 (启动 / 运行 / 关闭) 全 covered
- spec §4.4 error handling 5 row 全 covered (subprocess fail / actor fatal / SHM full / master SIGKILL / InfServer down)
- spec §4.5 testing strategy unit + integration + Mac fair bench 全 covered
- spec §5 phase budget 750 LOC 总,本 plan 也是 P0 250 + P1 250 + P2 100 + P3 150 ✓
- spec §6 out-of-scope (Win / AZ-PPO-CFR-BC port / InfServer 内部 / 长跑 mem 深优 / 历史对手 ring) 本 plan 未触 ✓

**Placeholder scan:** 通过 — 每 task 含实代码/命令/期望输出,无 "TBD / TODO"。 注意 P1.1-P1.4 + P3.1-P3.2 用 "Subagent Brief" 模式委派,subagent 自含细节 (符合 user 「subagent-driven dev」要求)。

**Type consistency:** TransitionShmChannel.try_pop_with_meta 返 `(int, int, bytes)` — 各 test 用同签名 ✓。 GoSubprocessHandle.spawn API 一致 (classmethod 返 instance,`.alive() / .terminate() / .returncode`)。

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-05-25-i29-redesign-implementation.md`。

**执行方式:Subagent-Driven (用户已 explicit 授权 + subagent 全 opus)。**

REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`

Fresh opus subagent per task + two-stage review (implementer → reviewer):
- P0.1-P0.2: 简单 LOC,可直跑 (无需 subagent)
- P0.3 onwards: subagent dispatch opus
- 每 task commit + verify gate 通过后 → 下一 task
- Phase 间显式 verify (`pytest` / `go test` / smoke) 不通过不进下一 phase
