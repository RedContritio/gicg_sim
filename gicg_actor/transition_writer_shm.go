// transition_writer_shm.go — SHM ring sink,Go actor → master Python (single-thread try_pop)。
//
// I29 redesign (2026-05-25) transport:cmd/gicg_actor standalone executable + master 0 cgo lib loaded
// (deal-breaker invariant #1)。 N actor goroutine 共享一条 SHM ring (MPSC,shm_ring_push CAS-safe,
// 见 gicg_actor/shm Phase 1-4 verify)。 master 端 TransitionShmChannel.try_pop_with_meta 读 (cid, rid,
// payload) → assembler ingest_episode (P1.4 wire up)。
//
// 失败语义:ring full 时 Push 返 err — paradigm 端决定 abort / retry / continue (与 TCP fire-and-forget
// 一致)。 不自己 spin — caller (paradigm) 自管 backoff 策略。 ring owner 在 caller (master Python),
// Close 仅 detach mmap 不 unlink。

package gicg_actor

import (
	"gicg_mono/gicg_actor/shm"
)

// TransitionWriterShm — TransitionSink SHM 实现。 wrap *shm.Ring,Push 透传 (cid, seq, payload) →
// shm.Ring.Push (MPSC CAS-safe,N actor goroutine 共享同一 ring)。
type TransitionWriterShm struct {
	ring  *shm.Ring
	owned bool // true = sink Close 时关 ring;false = ring 生命周期归 caller
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

// Push 透传到 shm.Ring.Push。 ring 满返 err "shm.Ring.Push: ring full",caller 决定 retry / abort。
// payload 长度超 slot capacity 返 err — paradigm 端 wire encode 不应超 slot_size (sizing 责任在 master cfg)。
func (w *TransitionWriterShm) Push(clientID, seq uint32, payload []byte) error {
	return w.ring.Push(clientID, seq, payload)
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
