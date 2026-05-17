package tests

// 契约测试:builtinDeferFn 必须在 DrainDeferred 时 restore 入队时的
// runtime context(CurrentContextPlayer / CurrentOwnerPlayer /
// CurrentOwnerChar),确保延后 DSL 闭包内动态 resolve 得到入队 hook
// 的视角。
//
// 回归 2026-04-21 发现的 bug:旧 builtinDeferFn 只捕获 rt 指针,不
// snapshot 任何字段,DrainDeferred 晚期 fire 时碰巧的上下文被
// silently 读取。以逸待劳.lua 等 defer_fn(deal_damage(Target.
// EnemyActive, ...)) 路径会受影响。

import (
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// TestDeferFn_PreservesContextAtQueueTime 通过 DSL 的 defer_fn 入队
// 一个闭包,闭包里调 `record_ctx()` native 回调。native 回调读当时
// rt.CurrentContextPlayer。对比:
//   - 入队时 rt.CurrentContextPlayer = 5
//   - 入队后改成 99(模拟另一 hook 上下文)
//   - 触发 DrainDeferred,闭包 fire
//   - 修复后:回调看到 5(入队值)
//   - 修复前:回调会看到 99(fire-time 值)
func TestDeferFn_PreservesContextAtQueueTime(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	rt := env.RT
	g := env.G

	// 注入 native 回调 record_ctx:读当时 runtime 上下文
	var observed struct {
		CtxPlayer int
		OwnerP    int
		OwnerC    int
	}
	rt.Interp.Global.SetLocal("record_ctx", interp.GoFunc(
		func(r *interp.Runtime, args []interp.Value) (interp.Value, error) {
			observed.CtxPlayer = r.CurrentContextPlayer
			observed.OwnerP = r.CurrentOwnerPlayer
			observed.OwnerC = r.CurrentOwnerChar
			return nil, nil
		},
	))

	// 准备 DSL:定义一个函数 queue_defer,它调 defer_fn(fn) 把闭包塞入
	// 当前 event frame 的 deferred 队列。闭包 fire 时会 record_ctx。
	src := `
queue_defer = function()
  defer_fn(function()
    record_ctx()
  end)
end
`
	lenv := interp.NewEnv(rt.Interp.Global)
	if err := rt.Interp.ExecFile(rt, []byte(src), lenv); err != nil {
		t.Fatalf("ExecFile: %v", err)
	}

	// 推 event layer 让 defer_fn 入队而非立即 fire
	g.PushEvent(engine.EventFrame{})
	defer g.PopEvent()

	// 设入队时的 context = 5
	rt.CurrentContextPlayer = 5
	rt.CurrentOwnerPlayer = 0
	rt.CurrentOwnerChar = 1

	// 调用 queue_defer() 把闭包塞入 deferred
	queueDeferVal, _ := lenv.Get("queue_defer")
	queueDefer, ok := queueDeferVal.(*interp.Closure)
	if !ok {
		t.Fatalf("queue_defer not a Closure: %T", queueDeferVal)
	}
	callEnv := interp.NewEnv(queueDefer.Env)
	if err := rt.Interp.ExecChunk(rt, queueDefer.Body, callEnv); err != nil {
		t.Fatalf("call queue_defer: %v", err)
	}

	// 模拟另一个 hook 跑过,上下文变 99
	rt.CurrentContextPlayer = 99
	rt.CurrentOwnerPlayer = 1
	rt.CurrentOwnerChar = 2

	// DrainDeferred → fire 闭包
	g.DrainDeferred()

	// 修复后应看到 5(入队时的值)
	if observed.CtxPlayer != 5 {
		t.Errorf("defer fn observed CurrentContextPlayer=%d, want 5 "+
			"(queue-time snapshot); fire-time was 99",
			observed.CtxPlayer)
	}
	if observed.OwnerP != 0 {
		t.Errorf("defer fn observed CurrentOwnerPlayer=%d, want 0",
			observed.OwnerP)
	}
	if observed.OwnerC != 1 {
		t.Errorf("defer fn observed CurrentOwnerChar=%d, want 1",
			observed.OwnerC)
	}

	// drain 完外部上下文应 restore 到 fire-time(99)
	if rt.CurrentContextPlayer != 99 {
		t.Errorf("after drain, outer CurrentContextPlayer=%d, want 99 "+
			"(fire-time unchanged after deferred restore)",
			rt.CurrentContextPlayer)
	}
}
