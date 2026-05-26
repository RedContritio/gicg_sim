// inference_requester.go — Transport-agnostic inference RPC interface。
//
// I29 R7.1 (2026-05-25) 删 SHM inference path,InferenceClient (TCP localhost socket)
// 是唯一 impl。 保留 interface 是为 future-proofing (paradigm.Run 不 import 具体类型,
// 测试可注入 mock InferenceRequester)。 历史 SHM ring 路径见 git history。

package gicg_actor

// InferenceRequester abstracts inference transport。 actor goroutine (via paradigm.Run)
// 只调本 interface 两 method,不关心 underlying socket。
//
// Request 是同步 send-then-recv,thread-safety 由 impl 内部 mutex 保证 (TCP path:
// shared client + mutex)。
type InferenceRequester interface {
	Request(req *InferRequest) (*InferResponse, error)
	Close() error
}

// Compile-time check that the TCP transport satisfies the interface。
var _ InferenceRequester = (*InferenceClient)(nil)
