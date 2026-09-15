// paradigm_mock_test.go — paradigm_test.go 的 mock 依赖。
//
// 与 paradigm_test.go 同 package(mock InferenceClient + TransitionWriterTCP),
// 供 TestRunEpisode_* 终结契约 integration test 使用。

package dmc

import (
	"net"
	"sync"
	"testing"

	"gicg_mono/gicg_actor"
)

// startMockInfServerZeros 起 mock InfServer:每 InferRequest 回 maxActions 个 0 logit。
// me 据此 argmax → 恒选 legal action 0(deterministic)。
func startMockInfServerZeros(t *testing.T, maxActions int) (addr string, stop func()) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				defer c.Close()
				for {
					payload, err := gicg_actor.ReadLengthPrefixed(c)
					if err != nil {
						return
					}
					if _, err := gicg_actor.DecodeInferRequest(payload); err != nil {
						return
					}
					resp := &gicg_actor.InferResponse{
						Status: gicg_actor.InferStatusOK,
						Logits: make([]float32, maxActions),
					}
					enc, err := gicg_actor.EncodeInferResponse(resp)
					if err != nil {
						return
					}
					if _, err := c.Write(enc); err != nil {
						return
					}
				}
			}(conn)
		}
	}()
	return listener.Addr().String(), func() { _ = listener.Close(); wg.Wait() }
}

// startMockTransSinkChan 起 mock transition sink — decode 每条 frame 推入 channel。
// F1 后 Go side 发 EpisodeBatch frames(Kind=1)。 本 mock 走 DecodeEpisodeBatch 解包,
// 将整 episode 的 []*Transition 逐条推入 channel(保持 per-trans channel 语义,测试不变)。
func startMockTransSinkChan(t *testing.T) (addr string, recv <-chan *gicg_actor.Transition, stop func()) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	ch := make(chan *gicg_actor.Transition, 8192)
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				defer c.Close()
				for {
					payload, err := gicg_actor.ReadLengthPrefixed(c)
					if err != nil {
						return
					}
					// Dispatch by Kind byte at offset 14 (F1: KindEpisodeBatch=1 at both header kinds)
					if len(payload) > 14 && payload[14] == gicg_actor.KindEpisodeBatch {
						txs, err := gicg_actor.DecodeEpisodeBatch(payload)
						if err != nil {
							return
						}
						for _, tr := range txs {
							ch <- tr
						}
					} else {
						tr, err := gicg_actor.DecodeTransition(payload)
						if err != nil {
							return
						}
						ch <- tr
					}
				}
			}(conn)
		}
	}()
	return listener.Addr().String(), ch, func() { _ = listener.Close(); wg.Wait() }
}
