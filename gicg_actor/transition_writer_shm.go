// transition_writer_shm.go — SHM ring sink,Go actor → master Python (single-thread try_pop)。
//
// I29 redesign (2026-05-25) transport:cmd/gicg_actor standalone executable + master 0 cgo lib loaded
// (deal-breaker invariant #1)。 N actor goroutine 共享一条 SHM ring (MPSC,shm_ring_push CAS-safe,
// 见 gicg_actor/shm Phase 1-4 verify)。 master 端 TransitionShmChannel.try_pop_with_meta 读 (cid, rid,
// payload) → assembler ingest_episode (P1.4 wire up)。
//
// 失败语义 (2026-05-27 fix):ring full 时 Push **内部 blocking retry** (spin with 1ms backoff until
// ring 有空位 或 30s timeout),与 Python mp.Queue.put() default blocking 同语义。 与 [[python_arch
// _mimicry_for_go_port]] memo 一致 — port 应保留原 mp.Queue blocking backpressure,而非引入 "drop on
// full" 让 RL data 丢失。 timeout 后才 return err (paradigm 视作 fatal abort)。 payload 长度超 slot
// capacity 返 err 不 retry (sizing 错误不应被掩盖)。
//
// Backpressure metric:Push 内部 atomic 累计 pushTotal / pushWaitNs / pushDropTimeouts → Stats()
// getter。 paradigm.go runActor 每 N episode emit stderr line `[gicg_actor backpressure] ...`
// master 端 Python stderr_thr 解析后进 metrics.jsonl "backpressure" kind。

package gicg_actor

import (
	"fmt"
	"strings"
	"sync/atomic"
	"time"

	"gicg_mono/gicg_actor/shm"
)

const (
	// pushRetryInterval — ring full 时 spin sleep。 1ms 短到 master collect (poll_interval_s=5ms
	// default) 有空 drain 时立即得到 slot,长到不烧 CPU (1k spin/sec)。
	pushRetryInterval = 1 * time.Millisecond
	// pushTimeout — ring full retry 上限。 超过 = master 完全 stuck (e.g. train deadlock),
	// fail-loud 让 caller (paradigm) 看到。 30s = 5 × InferenceServer batch_timeout 留头,production
	// train cycle worst case 仍可承。
	pushTimeout = 30 * time.Second
)

// TransitionWriterShm — TransitionSink SHM 实现。 wrap *shm.Ring,Push 透传 (cid, seq, payload) →
// shm.Ring.Push (MPSC CAS-safe,N actor goroutine 共享同一 ring)。
type TransitionWriterShm struct {
	ring  *shm.Ring
	owned bool // true = sink Close 时关 ring;false = ring 生命周期归 caller

	// Backpressure stats — atomic for MPSC (N actor goroutine 共享 sink instance)。
	pushTotal       atomic.Uint64 // 成功 push 数
	pushWaitTotalNs atomic.Int64  // 累计 push 等待 (含 success path 的 0ns + retry path 实际等待)
	pushDropTimeout atomic.Uint64 // pushTimeout 后 fail 数 (master deadlock 信号)
}

// 编译期断言。
var _ TransitionSink = (*TransitionWriterShm)(nil)

// NewTransitionWriterShm 构造 SHM sink。 ring 由 caller attach / create — sink 不 own 默认
// (Close 不关 ring,caller 自管);若 caller 想交给 sink 管理,用 NewTransitionWriterShmOwned。
func NewTransitionWriterShm(ring *shm.Ring) *TransitionWriterShm {
	return &TransitionWriterShm{ring: ring, owned: false}
}

// NewTransitionWriterShmOwned 构造 SHM sink,Close 时关 ring (sink own ring 生命周期)。
// 适用于 sink 与 ring 一对一绑定的场景 (e.g. cmd/gicg_actor main 内 attach 后传给唯一 sink)。
func NewTransitionWriterShmOwned(ring *shm.Ring) *TransitionWriterShm {
	return &TransitionWriterShm{ring: ring, owned: true}
}

// Push 透传到 shm.Ring.Push。 ring full 时 blocking retry (1ms spin) until 有空位 或 30s timeout。
// payload 超 slot capacity 或 ring 已 close 时立即 return err (不 retry — 配置 / 生命周期错误)。
//
// Backpressure metric (atomic 累计):
//   - pushTotal++ 仅 success path (含 first-try-OK 与 retry-eventually-OK 两种)
//   - pushWaitTotalNs += time.Since(start).Nanoseconds() 每 push (success 时 0ns;retry path 含 spin 总时间)
//   - pushDropTimeout++ 仅 30s timeout fail path (master deadlock 信号 — caller 应当 fail-loud)
func (w *TransitionWriterShm) Push(clientID, seq uint32, payload []byte) error {
	start := time.Now()
	deadline := start.Add(pushTimeout)
	for {
		err := w.ring.Push(clientID, seq, payload)
		if err == nil {
			elapsed := time.Since(start).Nanoseconds()
			w.pushTotal.Add(1)
			w.pushWaitTotalNs.Add(elapsed)
			return nil
		}
		// 区分 "ring full" (可 retry) vs hard err (payload 超 slot / ring 已 close):后者立即 return。
		if !strings.Contains(err.Error(), "ring full") {
			return err
		}
		if time.Now().After(deadline) {
			w.pushDropTimeout.Add(1)
			return fmt.Errorf("shm.Ring.Push: ring full after %v (master likely deadlocked): %w", pushTimeout, err)
		}
		time.Sleep(pushRetryInterval)
	}
}

// Stats 返回 backpressure 累计指标 — paradigm runActor 周期性 sample 用于 stderr emit。
// 跨 actor goroutine call-safe (atomic load)。 reset 不需要 — caller 取 delta 自管。
func (w *TransitionWriterShm) Stats() (pushTotal uint64, pushWaitTotalNs int64, pushDropTimeout uint64) {
	return w.pushTotal.Load(), w.pushWaitTotalNs.Load(), w.pushDropTimeout.Load()
}

// Close — owned=true 时关 ring (detach mmap,owner unlink 由 master 端 TransitionShmChannel.close 管);
// owned=false 时 no-op (ring 生命周期归 caller)。 幂等。
func (w *TransitionWriterShm) Close() error {
	if !w.owned || w.ring == nil {
		return nil
	}
	err := w.ring.Close()
	w.ring = nil
	return err
}
