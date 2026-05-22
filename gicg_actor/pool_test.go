package gicg_actor

import (
	"context"
	"net"
	"sync/atomic"
	"testing"
	"time"
)

// TestAliveCount 守 I29 T-RR.7 actor 死亡可见性:AliveCount 在 StartPool 后 == NActors,
// StopPool 后 == 0(wg.Wait 返回时所有 actorLoop 的 defer 已执行)。 用 placeholder
// 路径(paradigm==""),actor 跑 <-ctx.Done() 占位。
func TestAliveCount(t *testing.T) {
	if c := AliveCount(); c != 0 {
		t.Fatalf("AliveCount before start = %d, want 0", c)
	}
	if rc := StartPool(3); rc != 0 {
		t.Fatalf("StartPool(3) rc=%d", rc)
	}
	if c := AliveCount(); c != 3 {
		t.Errorf("AliveCount after StartPool(3) = %d, want 3", c)
	}
	if rc := StopPool(); rc != 0 {
		t.Fatalf("StopPool rc=%d", rc)
	}
	if c := AliveCount(); c != 0 {
		t.Errorf("AliveCount after StopPool = %d, want 0", c)
	}
}

// countingParadigm — 测试用 paradigm:Run 等 ctx.Done 即退,只验 pool 接线。
type countingParadigm struct{}

func (p *countingParadigm) Name() string                   { return "test_counting" }
func (p *countingParadigm) Configure(jsonCfg string) error { return nil }
func (p *countingParadigm) Run(ctx context.Context, id int, inf *InferenceClient, tw *TransitionWriter) error {
	<-ctx.Done()
	return nil
}

// TestStartPool_PerActorInferenceConn 守 I29 T-RR.5:N actor 各自一条 inference socket
// conn(非单一共享 client)。 mock inf server 计 accepted conn 数 == NActors。
func TestStartPool_PerActorInferenceConn(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer listener.Close()
	var accepted int32
	go func() {
		conns := []net.Conn{}
		for {
			conn, err := listener.Accept()
			if err != nil {
				for _, c := range conns {
					_ = c.Close()
				}
				return
			}
			atomic.AddInt32(&accepted, 1)
			conns = append(conns, conn) // 持有,保持 conn open
		}
	}()

	RegisterParadigm("test_counting", &countingParadigm{})
	const N = 5
	rc := StartPoolWithConfig(Config{
		NActors:       N,
		ParadigmName:  "test_counting",
		InfServerAddr: listener.Addr().String(),
		IOTimeoutMs:   2000,
	})
	if rc != 0 {
		t.Fatalf("StartPoolWithConfig rc=%d", rc)
	}
	if got := len(currentInfs); got != N {
		t.Errorf("len(currentInfs) = %d, want %d (per-actor client)", got, N)
	}
	for i, c := range currentInfs {
		if c == nil {
			t.Errorf("currentInfs[%d] = nil, want connected client", i)
		}
	}
	if rc := StopPool(); rc != 0 {
		t.Fatalf("StopPool rc=%d", rc)
	}
	// 等 listener accept goroutine 收齐(短轮询)。
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) && atomic.LoadInt32(&accepted) < N {
		time.Sleep(10 * time.Millisecond)
	}
	if got := atomic.LoadInt32(&accepted); got != N {
		t.Errorf("mock inf server accepted %d conn, want %d (per-actor conn)", got, N)
	}
}
