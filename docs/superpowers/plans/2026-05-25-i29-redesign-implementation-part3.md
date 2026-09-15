> 分卷导航:回到 [← Part 1](2026-05-25-i29-redesign-implementation.md) · [← Part 2](2026-05-25-i29-redesign-implementation-part2.md) · 续见 [Part 4](2026-05-25-i29-redesign-implementation-part4.md)

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
