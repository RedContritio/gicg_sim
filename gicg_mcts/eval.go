package mcts

// EvalRequest is the data sent to the eval callback at leaf expansion.
// Slices point into Go-owned memory; callback must not retain them
// past return.
type EvalRequest struct {
	WorkerID int32   // inference_server session key (per-worker)
	GameID   int32   // game handle for the inference_server cache
	DynObs   []int32 // dynamic observation (raw int32, same layout as GameGetDynamicObs)
	Refs     []int32 // flat (N_legal × 3) action refs [kind, hook_idx, char_idx]
	Pay      []int32 // flat (N_legal × 8) dice payments
	NLegal   int32
}

// EvalResponse is what the callback writes back. Caller provides
// pre-allocated slices sized exactly to N_legal / 1.
type EvalResponse struct {
	Prior []float32 // N_legal probabilities (may not sum to 1 after float ops)
	Value float32   // P-current-player value ∈ [-1, 1]
}

// EvalSendFunc pushes an eval request without waiting for the
// response. Called from the Search driver goroutine; the Python
// side typically forwards to client.send_eval() which returns
// immediately after writing to the inference_server pipe.
type EvalSendFunc func(req *EvalRequest) error

// EvalRecvFunc blocks until the next response is available and
// writes it into the caller-provided response. Called after one or
// more matching EvalSendFunc calls. Because Search drives both in
// one goroutine and the server pipe is FIFO, responses arrive in
// send order and require no correlation ID.
type EvalRecvFunc func(resp *EvalResponse) error
