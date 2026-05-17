package tests

// 契约测试:hook fn 执行期间即使发生 Go panic,CurrentContextPlayer /
// CurrentOwnerPlayer / CurrentOwnerChar 的 prev 值也必须恢复到外层状态,
// 不能把当前 hook 的 context 悬挂到下一个事件。
//
// 修复前:makeHookFn / makeWriteHookFn 用 prevCtx := ...; ...;
// activeRT.CurrentContextPlayer = prevCtx 没有 defer 包裹,Go panic
// 穿透时 prev 永远不恢复。修复后:defer func(){ restore } 包围。

import (
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

func TestMakeHookFn_RestoresContextOnPanic(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	rt := env.RT
	g := env.G

	// 外层上下文 sentinel
	rt.CurrentContextPlayer = 77

	// 注入一个会 panic 的 native function
	rt.Interp.Global.SetLocal("boom", interp.GoFunc(
		func(r *interp.Runtime, args []interp.Value) (interp.Value, error) {
			panic("synthetic panic for test")
		},
	))

	// 定义一个 Closure:body 就是 boom()
	src := `my_hook = function(ctx) boom() end`
	lenv := interp.NewEnv(rt.Interp.Global)
	if err := rt.Interp.ExecFile(rt, []byte(src), lenv); err != nil {
		t.Fatalf("ExecFile: %v", err)
	}
	hookClVal, _ := lenv.Get("my_hook")
	hookCl, ok := hookClVal.(*interp.Closure)
	if !ok {
		t.Fatalf("my_hook not a Closure: %T", hookClVal)
	}

	// 调 makeHookFn 得到 engine.HookFn,fire 时会 panic 穿透
	hookFn := interp.MakeHookFnForTest(rt, hookCl, nil)
	ctx := &engine.EventContext{ActorPlayer: 1} // makeHookFn set ctx=1

	// fire hookFn — 应当 panic,但 defer 保证 CurrentContextPlayer 恢复
	defer func() {
		_ = recover() // 吞掉 panic,让测试继续
		if rt.CurrentContextPlayer != 77 {
			t.Errorf("after panic, CurrentContextPlayer=%d, want 77 (restored); "+
				"panic leaked hook's ctx=1 to outer frame",
				rt.CurrentContextPlayer)
		}
	}()
	hookFn(g, ctx)
	t.Errorf("expected panic, but hookFn returned normally")
}

func TestMakeWriteHookFn_RestoresContextOnPanic(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	rt := env.RT
	g := env.G

	rt.CurrentContextPlayer = 77
	rt.CurrentOwnerPlayer = 8
	rt.CurrentOwnerChar = 9

	rt.Interp.Global.SetLocal("boom", interp.GoFunc(
		func(r *interp.Runtime, args []interp.Value) (interp.Value, error) {
			panic("synthetic panic for test")
		},
	))

	src := `my_hook = function(ctx) boom() end`
	lenv := interp.NewEnv(rt.Interp.Global)
	if err := rt.Interp.ExecFile(rt, []byte(src), lenv); err != nil {
		t.Fatalf("ExecFile: %v", err)
	}
	hookClVal, _ := lenv.Get("my_hook")
	hookCl, ok := hookClVal.(*interp.Closure)
	if !ok {
		t.Fatalf("my_hook not a Closure: %T", hookClVal)
	}

	// counterID = 0 (取第一个 counter,其 owner 可能是 [-1, -1])
	hookFn := interp.MakeWriteHookFnForTest(rt, hookCl, nil, 0)
	ctx := &engine.EventContext{ActorPlayer: 1}

	defer func() {
		_ = recover()
		if rt.CurrentContextPlayer != 77 {
			t.Errorf("CurrentContextPlayer=%d, want 77 (restored after panic)",
				rt.CurrentContextPlayer)
		}
		if rt.CurrentOwnerPlayer != 8 {
			t.Errorf("CurrentOwnerPlayer=%d, want 8", rt.CurrentOwnerPlayer)
		}
		if rt.CurrentOwnerChar != 9 {
			t.Errorf("CurrentOwnerChar=%d, want 9", rt.CurrentOwnerChar)
		}
	}()
	hookFn(g, ctx)
	t.Errorf("expected panic, but hookFn returned normally")
}
