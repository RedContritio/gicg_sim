package interp

import (
	"fmt"
	"path/filepath"
	"strings"

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
	var opts *Table
	if len(args) == 4 {
		opts, _ = args[2].(*Table)
	}
	fn, _ := args[len(args)-1].(*Closure)
	return nil, rt.registerWriteHooksForProxy(counterRef, hookType, engine.Op(opVal), fn, nil, opts)
}

func (rt *Runtime) registerWriteHooksForProxy(ref Value, hookType string, op engine.Op, fn *Closure, passRef Value, opts *Table) error {
	if fn == nil {
		return fmt.Errorf("write hook requires function")
	}
	var ids []int
	var refKind int
	switch r := ref.(type) {
	case *CounterProxy:
		ids = []int{r.ID}
		refKind = r.RefKind
	case *PerPlayerProxy:
		ids = r.AllCounterIDs()
		refKind = r.RefKind
	case *PerCharProxy:
		ids = r.AllCounterIDs()
		refKind = r.RefKind
	case *SelfSlotProxy:
		ids = r.AllCounterIDs()
		refKind = r.RefKind
	default:
		return fmt.Errorf("write hook requires counter")
	}

	ht := engine.HookBeforeWrite
	if hookType == "after" {
		ht = engine.HookAfterWrite
	}

	for _, id := range ids {
		boundRef := passRef
		if passRef != nil {
			// A tag callback receives the concrete counter being written,
			// not a summary proxy whose owner cannot be resolved in DSL.
			boundRef = &CounterProxy{ID: id, RefKind: refKind}
		}
		hookFn := rt.makeWriteHookFn(fn, boundRef, id)
		h := engine.Hook{
			Type:            ht,
			CounterID:       id,
			Op:              op,
			Fn:              hookFn,
			OwnerPlayer:     engine.FilterAny,
			OwnerChar:       engine.FilterAny,
			CounterAccess:   hookCounterAccess(fn),
			SkillReferences: rt.hookSkillReferences(fn),
			BodyAny:         fn.Body,
		}
		if passRef != nil && len(fn.Params) > 1 {
			h.CounterParam = fn.Params[1]
		}
		if opts != nil && opts.Fields["order"] != nil {
			resolve, orderIDs, err := rt.hookOrder(opts.Fields["order"], ht)
			if err != nil {
				return err
			}
			h.OrderIDs = orderIDs
			owner := rt.Game.GetCounterChar(id)
			h.OrderCounter = func(ctx *engine.EventContext) int {
				copy := *ctx
				copy.ActorPlayer, copy.ActorChar = owner[0], owner[1]
				return resolve(&copy)
			}
			h.Priority, _ = ToInt(opts.Fields["priority"])
		}
		rt.registerHook(h)
	}
	return nil
}

// registerHook stamps the current source file + per-file registration
// index (set by ExecFileSandboxed) onto the Hook before registration.
// All builtin hook registrations should go through this so the visualizer
// can disambiguate hooks by their DSL source. The "#N" suffix
// distinguishes multiple on_xxx of the same type within one file (e.g.
// 蝶火.lua has 2 on_damage_boost: 物理→火 enchant and 枪 加伤).
func (rt *Runtime) registerHook(h engine.Hook) int {
	if rt.CurrentSourceFile != "" && len(rt.LoadedFiles) > 0 {
		source := filepath.ToSlash(rt.LoadedFiles[len(rt.LoadedFiles)-1])
		h.SystemRule = strings.Contains(source, "/system/")
	}
	if rt.CurrentSourceFile != "" {
		h.Source = fmt.Sprintf("%s#%d", rt.CurrentSourceFile, rt.CurrentSourceHookIdx)
		rt.CurrentSourceHookIdx++
	}
	id := rt.Game.Hooks.Register(h)
	for _, cid := range h.OrderIDs {
		if cid >= 0 {
			d := &rt.Game.BuffDefinitions[rt.Game.Counters[cid].BuffIndex]
			d.HookIDs = append(d.HookIDs, id)
		}
	}
	return id
}

func (rt *Runtime) builtinRegisterOnTagWrite(args []Value) (Value, error) {
	tag, _ := ToInt(args[0])
	hookType, _ := args[1].(string)
	opVal, _ := ToInt(args[2])
	var opts *Table
	if len(args) == 5 {
		opts, _ = args[3].(*Table)
	}
	fn, _ := args[len(args)-1].(*Closure)
	op := engine.Op(opVal)

	entries := rt.Counters.TagGroups[tag]
	for _, e := range entries {
		ref := e.Ref
		if err := rt.registerWriteHooksForProxy(ref, hookType, op, fn, ref, opts); err != nil {
			return nil, err
		}
	}
	return nil, nil
}
