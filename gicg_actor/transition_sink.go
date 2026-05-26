// transition_sink.go — paradigm-agnostic transition transport interface (I29 redesign 2026-05-25)。
//
// Paradigm 端把 encoded transition bytes 交给 sink,sink 选择 transport (TCP socket 走 listener / SHM ring 走
// master single-thread try_pop)。 paradigm 不关心底层 transport,sink 不解析 payload。
//
// 设计:Push 接 (clientID, seq, payload) 与 shm.Ring.Push 对齐 — SHM impl 透传,TCP impl 直接 conn.Write
// (payload 已含 outer length prefix + wire header,由 paradigm 端 EncodeEpisodeBatch / EncodeTransition 产)。
//
// 历史:旧 *TransitionWriter (TCP only) 暴露 Push(*Transition) + PushBatch(cid, eid, txs) 双 API,paradigm
// 内部分发。 redesign 后 encode 责任移到 paradigm 端,sink 单一签名 Push(cid, seq, bytes)。 cid=actor ID,
// seq 对 episode batch = episode ID,对 per-trans = transition step (paradigm 自定)。

package gicg_actor

// TransitionSink — transition transport abstraction。 由 paradigm.Run 接收,paradigm 端 encode 后透传 bytes。
//
// 实现:
//   - TransitionWriterTCP (TCP socket,Python listener 端 length-prefixed stream decode)
//   - TransitionWriterShm (shm.Ring wrapper,Python try_pop_with_meta 直读 slot bytes)
//
// 失败语义:Push 返 err = 本条 push 失败,paradigm 决定 abort 当前 episode / 重试 / continue;
// 不致死 actor (caller 端 fire-and-forget 视角)。 Close 幂等,sink 自管资源生命周期。
type TransitionSink interface {
	// Push fire-and-forget 一条 payload。 clientID = actor ID (路由),seq = batch/episode ID 或 step ID。
	// payload 是 paradigm-encoded wire frame (含 outer length prefix + header — TCP transport 直接透传;
	// SHM transport 也透传,slot bytes 含冗余 outer length prefix,Python 端 wire decode 时 skip)。
	Push(clientID, seq uint32, payload []byte) error
	// Close 关闭底层 transport。 幂等。 TCP 关 socket;SHM detach mmap (owner 在 caller,不 unlink)。
	Close() error
}
