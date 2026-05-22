package gicg_actor

import "testing"

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
