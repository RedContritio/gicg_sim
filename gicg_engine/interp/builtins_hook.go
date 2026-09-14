package interp

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
)

// Internal hook closure machinery: makeHookFn / makeWriteHookFn wrap
// Lua closures as engine.HookFn callbacks; callClosure is the shared
// frame-push helper; registerHookFunctions wires the DSL on_* names
// to the underlying engine hook types; charBySlotTable/Row back the
// rt._chars table lookups from DSL.

func (rt *Runtime) makeHookFn(cl *Closure, passRef Value) engine.HookFn {
	// Note: the rt captured here is the runtime that was active at DSL
	// load time. When this hook fires on a clone's game, we must resolve
	// the clone's runtime (g.Extra) rather than use the captured rt.
	// The closure body (cl) is shared static DSL code, so it's safe to
	// execute under any runtime.
	return func(g *engine.Game, ctx *engine.EventContext) {
		activeRT, ok := g.Extra.(*Runtime)
		if !ok || activeRT == nil {
			g.FailRule(fmt.Errorf("DSL hook requires an attached runtime"), ctx.CurrentHookID)
		}
		prevCtx := activeRT.CurrentContextPlayer
		// Panic-safe restore. callClosure catches DSL errors via
		// lastError but Go-level panics (nil deref, oob index in a
		// builtin, etc.) propagate — without defer the prevCtx leaks
		// into the next event's hook, corrupting context resolution.
		defer func() {
			activeRT.CurrentContextPlayer = prevCtx
		}()
		if ctx.ActorPlayer >= 0 {
			activeRT.CurrentContextPlayer = ctx.ActorPlayer
		}
		if ctx.BuffID != 0 {
			if owner := g.BuffOwner(ctx.BuffID); owner[0] >= 0 {
				activeRT.CurrentContextPlayer = owner[0]
			}
		}
		ctxProxy := &CtxProxy{Ctx: ctx}
		args := []Value{ctxProxy}
		if passRef != nil {
			args = append(args, passRef)
		}
		activeRT.callClosure(cl, args)
		if activeRT.lastError != nil && activeRT.traceEnabled {
			fmt.Printf("  [TRACE] hook error: %v\n", activeRT.lastError)
		}
	}
}

// makeWriteHookFn is the write-hook-specific variant of makeHookFn.
//
// Write hook semantics: "something wrote to counter N". The most
// useful runtime context is the OWNER of counter N — not ctx.ActorPlayer
// (which under a shield-absorption flow is the attacker, but the counter
// being written belongs to the defender).
//
// Resolution source: g.GetCounterChar(counterID) — populated by
// RegisterCounterChar at declare time. Per-binding Self/ActiveStatus:
// returns [p, c]. PerPlayer: returns [p, -1]. PerChar: returns [p, c]
// for the specific counter. Global / shared-load Self without owner
// binding: returns [-1, -1], in which case we fall back to ActorPlayer
// to preserve the current behavior for counters that legitimately
// have no owner.
//
// This makes the access "active:get()" inside e.g. 刺刺猫爪's
// on_after_write(猫爪护盾, Sub) read the shield owner's Self value
// rather than the attacker's — which is the semantically correct
// answer and unblocks shared-load talent cards in mirror matches
// (see B plan in docs/decisions/talent_mirror.md).
func (rt *Runtime) makeWriteHookFn(cl *Closure, passRef Value, counterID int) engine.HookFn {
	return func(g *engine.Game, ctx *engine.EventContext) {
		activeRT, ok := g.Extra.(*Runtime)
		if !ok || activeRT == nil {
			g.FailRule(fmt.Errorf("DSL write hook requires an attached runtime"), ctx.CurrentHookID)
		}
		prevCtxP := activeRT.CurrentContextPlayer
		prevOwnerP := activeRT.CurrentOwnerPlayer
		prevOwnerC := activeRT.CurrentOwnerChar
		// Panic-safe restore — matches makeHookFn rationale above.
		defer func() {
			activeRT.CurrentContextPlayer = prevCtxP
			activeRT.CurrentOwnerPlayer = prevOwnerP
			activeRT.CurrentOwnerChar = prevOwnerC
		}()

		owner := g.GetCounterChar(counterID)
		if owner[0] >= 0 {
			activeRT.CurrentContextPlayer = owner[0]
			activeRT.CurrentOwnerPlayer = owner[0]
			if owner[1] >= 0 {
				activeRT.CurrentOwnerChar = owner[1]
			}
		} else if ctx.ActorPlayer >= 0 {
			activeRT.CurrentContextPlayer = ctx.ActorPlayer
		}

		ctxProxy := &CtxProxy{Ctx: ctx}
		args := []Value{ctxProxy}
		if passRef != nil {
			ref := passRef
			if cp, ok := passRef.(*CounterProxy); ok && ctx.WriteBuffID != 0 {
				copy := *cp
				copy.InstanceID = ctx.WriteBuffID
				ref = &copy
			}
			args = append(args, ref)
		}
		activeRT.callClosure(cl, args)
		if activeRT.lastError != nil && activeRT.traceEnabled {
			fmt.Printf("  [TRACE] hook error: %v\n", activeRT.lastError)
		}
	}
}

// MakeHookFnForTest exposes makeHookFn for cross-package tests
// (gicg_engine/tests). Production callers use the (unexported)
// makeHookFn directly via the hook-registration builtins.
func MakeHookFnForTest(rt *Runtime, cl *Closure, passRef Value) engine.HookFn {
	return rt.makeHookFn(cl, passRef)
}

// MakeWriteHookFnForTest exposes makeWriteHookFn for cross-package tests.
func MakeWriteHookFnForTest(rt *Runtime, cl *Closure, passRef Value, counterID int) engine.HookFn {
	return rt.makeWriteHookFn(cl, passRef, counterID)
}

func (rt *Runtime) callClosure(cl *Closure, args []Value) {
	previous := rt.currentHookContext
	defer func() { rt.currentHookContext = previous }()
	if len(args) > 0 {
		if ctx, ok := args[0].(*CtxProxy); ok {
			rt.currentHookContext = ctx.Ctx
		}
	}
	callEnv := NewEnv(cl.Env)
	for i, param := range cl.Params {
		if i < len(args) {
			callEnv.SetLocal(param, args[i])
		} else {
			callEnv.SetLocal(param, nil)
		}
	}
	err := rt.Interp.ExecChunk(rt, cl.Body, callEnv)
	if _, ok := err.(errReturn); ok {
		rt.lastError = nil
		return
	}
	rt.lastError = err
	if err != nil {
		hookID := -1
		if len(args) > 0 {
			if ctx, ok := args[0].(*CtxProxy); ok {
				hookID = ctx.Ctx.CurrentHookID
			}
		}
		rt.Game.FailRule(err, hookID)
	}
}

func (rt *Runtime) registerHookFunctions() {
	g := rt.Interp.Global

	hookTypes := map[string]engine.HookType{
		// ADR-0019 §B.5 strict damage 流水线
		"on_damage_type":        engine.HookDamageType,
		"on_damage_add":         engine.HookDamageAdd,
		"on_damage_mul":         engine.HookDamageMul,
		"on_reaction_damage":    engine.HookReactionDamage,
		"on_damage_reduce_buff": engine.HookDamageReduceBuff,
		"on_shield_absorb":      engine.HookShieldAbsorb,
		"on_damage_immunity":    engine.HookDamageImmunity,
		"on_after_damage":       engine.HookAfterDamage,
		"on_after_reaction":     engine.HookAfterReaction,

		"on_before_heal":           engine.HookBeforeHeal,
		"on_after_heal":            engine.HookAfterHeal,
		"on_before_energy_gain":    engine.HookBeforeEnergyGain,
		"on_after_energy_gain":     engine.HookAfterEnergyGain,
		"on_before_energy_consume": engine.HookBeforeEnergyConsume,
		"on_after_energy_consume":  engine.HookAfterEnergyConsume,
		"on_action_check":          engine.HookActionCheck,
		"on_action_prepare":        engine.HookActionPrepare,
		"on_skill_use":             engine.HookSkillUse,
		"on_card_play":             engine.HookCardPlay,
		"on_switch":                engine.HookSwitch,
		"on_before_turn_flip":      engine.HookBeforeTurnFlip,
		"on_tune":                  engine.HookOnTune,
		"on_round_start":           engine.HookRoundStart,
		"on_round_end":             engine.HookRoundEnd,
		"on_round_end_post_summon": engine.HookRoundEndPostSummon,
		"on_round_end_decay":       engine.HookRoundEndDecay,
		"on_round_end_final":       engine.HookRoundEndFinal,
		"on_death":                 engine.HookDeath,
		"on_revive":                engine.HookRevive,
		"on_support_remove":        engine.HookSupportRemove,
	}

	for name, ht := range hookTypes {
		ht := ht // capture
		g.SetLocal(name, GoFunc(func(rt *Runtime, args []Value) (Value, error) {
			// Two forms: on_xxx(fn) or on_xxx(priority, fn)
			var priority int
			var order Value
			var targetOrder bool
			var fn *Closure
			if len(args) == 1 {
				fn, _ = args[0].(*Closure)
			} else {
				if opts, ok := args[0].(*Table); ok {
					priority, _ = ToInt(opts.Fields["priority"])
					order = opts.Fields["order"]
					if v, ok := opts.Fields["order_on"]; ok {
						if v != "target" {
							return nil, fmt.Errorf("invalid order_on")
						}
						targetOrder = true
					}
				} else {
					priority, _ = ToInt(args[0])
				}
				fn, _ = args[1].(*Closure)
			}
			if fn == nil {
				return nil, fmt.Errorf("%s: expected function argument", name)
			}
			hookFn := rt.makeHookFn(fn, nil)
			h := engine.Hook{
				Type:            ht,
				Fn:              hookFn,
				OwnerPlayer:     rt.CurrentOwnerPlayer,
				OwnerChar:       rt.CurrentOwnerChar,
				Priority:        priority,
				CounterAccess:   hookCounterAccess(fn),
				SkillReferences: rt.hookSkillReferences(fn),
				BodyAny:         fn.Body, // *Chunk; engine treats as opaque
			}
			if order != nil {
				var err error
				h.OrderCounter, h.OrderIDs, err = rt.hookOrder(order, ht)
				if err != nil {
					return nil, err
				}
			}
			if targetOrder {
				if h.OrderCounter == nil {
					return nil, fmt.Errorf("order_on requires order")
				}
				h.OrderTarget = true
				resolve := h.OrderCounter
				h.OrderCounter = func(ctx *engine.EventContext) int {
					copy := *ctx
					copy.ActorPlayer, copy.ActorChar = ctx.TargetPlayer, ctx.TargetChar
					return resolve(&copy)
				}
			}
			id := rt.registerHook(h)
			return id, nil
		}))
	}
}

// charBySlotTable implements IndexProvider: _char_by_slot[p] returns
// a charBySlotRow bound to player p. Accessing [p][c] on the row
// returns the CharProxy for (p, c), or nil if unbound.
type charBySlotTable struct {
	rt *Runtime
}

func (t *charBySlotTable) GetIndex(key Value) (Value, error) {
	p, ok := ToInt(key)
	if !ok || p < 0 || p > 1 {
		return nil, nil
	}
	return &charBySlotRow{rt: t.rt, player: p}, nil
}

type charBySlotRow struct {
	rt     *Runtime
	player int
}

func (r *charBySlotRow) GetIndex(key Value) (Value, error) {
	c, ok := ToInt(key)
	if !ok || c < 0 || c >= MaxChars {
		return nil, nil
	}
	slot := r.rt.Chars.BySlot[r.player][c]
	if slot == nil {
		return nil, nil
	}
	return &CharProxy{Entry: slot}, nil
}
