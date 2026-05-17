package interp

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
)

// Counter write-hook helpers + the shared registerHook. Kept beside
// builtins_counter.go which hosts declare_counter / get_counter and
// callers of these helpers.

func (rt *Runtime) builtinOnBeforeWrite(args []Value) (Value, error) {
	return rt.registerWriteHookFromArgs("before", args)
}

func (rt *Runtime) builtinOnAfterWrite(args []Value) (Value, error) {
	return rt.registerWriteHookFromArgs("after", args)
}

func (rt *Runtime) registerWriteHookFromArgs(hookType string, args []Value) (Value, error) {
	counterRef := args[0]
	opVal, _ := ToInt(args[1])
	fn, _ := args[2].(*Closure)
	op := engine.Op(opVal)

	rt.registerWriteHooksForProxy(counterRef, hookType, op, fn, nil)
	return nil, nil
}

func (rt *Runtime) registerWriteHooksForProxy(ref Value, hookType string, op engine.Op, fn *Closure, passRef Value) {
	var ids []int
	switch r := ref.(type) {
	case *CounterProxy:
		ids = []int{r.ID}
	case *PerPlayerProxy:
		ids = r.AllCounterIDs()
	case *PerCharProxy:
		ids = r.AllCounterIDs()
	case *SelfSlotProxy:
		ids = r.AllCounterIDs()
	default:
		return
	}

	ht := engine.HookBeforeWrite
	if hookType == "after" {
		ht = engine.HookAfterWrite
	}

	for _, id := range ids {
		hookFn := rt.makeWriteHookFn(fn, passRef, id)
		rt.registerHook(engine.Hook{
			Type:      ht,
			CounterID: id,
			Op:        op,
			Fn:        hookFn,
			Priority:  0,
		})
	}
}

// registerHook stamps the current source file + per-file registration
// index (set by ExecFileSandboxed) onto the Hook before registration.
// All builtin hook registrations should go through this so the visualizer
// can disambiguate hooks by their DSL source. The "#N" suffix
// distinguishes multiple on_xxx of the same type within one file (e.g.
// 蝶火.lua has 2 on_damage_boost: 物理→火 enchant and 枪 加伤).
func (rt *Runtime) registerHook(h engine.Hook) int {
	if rt.CurrentSourceFile != "" {
		h.Source = fmt.Sprintf("%s#%d", rt.CurrentSourceFile, rt.CurrentSourceHookIdx)
		rt.CurrentSourceHookIdx++
	}
	return rt.Game.Hooks.Register(h)
}
