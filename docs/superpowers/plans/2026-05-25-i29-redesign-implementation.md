# I29 Go-actor pool 完全重设计 — Implementation Plan

> 分卷导航:本文档共 4 卷 · 续见 [Part 2](2026-05-25-i29-redesign-implementation-part2.md) → [Part 3](2026-05-25-i29-redesign-implementation-part3.md) → [Part 4](2026-05-25-i29-redesign-implementation-part4.md)

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
