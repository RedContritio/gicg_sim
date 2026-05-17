package interp

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
)

// RegisterBuiltins registers all DSL API functions and enum constants.
func (rt *Runtime) RegisterBuiltins() {
	g := rt.Interp.Global

	// --- Utilities ---
	g.SetLocal("min", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		a, _ := ToInt(args[0])
		b, _ := ToInt(args[1])
		if a < b {
			return a, nil
		}
		return b, nil
	}))
	g.SetLocal("max", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		a, _ := ToInt(args[0])
		b, _ := ToInt(args[1])
		if a > b {
			return a, nil
		}
		return b, nil
	}))
	g.SetLocal("MAX_CHARS", MaxChars)

	// _char_by_slot is a two-level dynamic table: _char_by_slot[p][c]
	// returns the CharProxy for the slot at (p, c), or nil if unbound.
	// DSL uses this to look up the current active char's properties
	// (e.g. ._skill_ids for "is this a normal attack" checks) without
	// needing to know the char's name at the call site.
	g.SetLocal("_char_by_slot", &charBySlotTable{rt: rt})

	// --- Enums ---
	rt.registerEnums()

	// --- Counter API ---
	g.SetLocal("declare_counter", GoFunc((*Runtime).builtinDeclareCounter))
	g.SetLocal("create_counter", GoFunc((*Runtime).builtinDeclareCounter)) // alias
	g.SetLocal("declare_shield", GoFunc((*Runtime).builtinDeclareShield))  // ADR-0019 §B.4
	g.SetLocal("get_counter", GoFunc((*Runtime).builtinGetCounter))
	g.SetLocal("get_counter_group", GoFunc((*Runtime).builtinGetCounterGroup))
	g.SetLocal("register_on_tag_write", GoFunc((*Runtime).builtinRegisterOnTagWrite))

	// --- Char API ---
	g.SetLocal("declare_char", GoFunc((*Runtime).builtinDeclareChar))
	g.SetLocal("bind_char", GoFunc((*Runtime).builtinBindChar))
	g.SetLocal("get_char", GoFunc((*Runtime).builtinGetChar))

	// --- Skill API ---
	g.SetLocal("declare_skill", GoFunc((*Runtime).builtinDeclareSkill))
	g.SetLocal("get_skill", GoFunc((*Runtime).builtinGetSkill))
	g.SetLocal("invoke_skill", GoFunc((*Runtime).builtinInvokeSkill))
	g.SetLocal("invoke_skill_silent", GoFunc((*Runtime).builtinInvokeSkillSilent))
	// Prepare-skill / draw_card / add_dice 拆到 builtins_adr0012.go
	rt.registerADR0012Builtins()

	// --- Card API ---
	g.SetLocal("declare_card", GoFunc((*Runtime).builtinDeclareCard))
	g.SetLocal("get_card", GoFunc((*Runtime).builtinGetCard))
	g.SetLocal("add_card", GoFunc((*Runtime).builtinAddCard))

	// --- Support zone API (remove_support / count_support) ---
	rt.registerSupportBuiltins()

	// --- Action API ---
	g.SetLocal("deal_damage", GoFunc((*Runtime).builtinDealDamage))
	g.SetLocal("heal", GoFunc((*Runtime).builtinHeal))
	g.SetLocal("defer_fn", GoFunc((*Runtime).builtinDeferFn))
	g.SetLocal("get_active_char", GoFunc((*Runtime).builtinGetActiveChar))
	g.SetLocal("set_active_char", GoFunc((*Runtime).builtinSetActiveChar))
	g.SetLocal("get_next_char", GoFunc((*Runtime).builtinGetNextChar))
	g.SetLocal("find_char_by_kind", GoFunc((*Runtime).builtinFindCharByKind)) // ADR-0019 §A.2

	// ADR-0019 §B.3 — DSL declare_reaction registry + set_reaction_kind
	g.SetLocal("declare_reaction", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		name, _ := args[0].(string)
		if name == "" {
			return 0, nil
		}
		return rt.Game.DeclareReaction(name), nil
	}))
	g.SetLocal("set_reaction_kind", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		id, _ := ToInt(args[0])
		cur := rt.Game.CurrentEvent()
		_ = cur
		// set_reaction_kind 应当在 HookReactionDamage 内调用,此时 ctx 是
		// 当前 reaction handler 的 reactionCtx (见 damage.go ② 阶段)。
		// 但 reactionCtx 是 damage.go 局部变量,DSL hook 接 ctx 是该
		// reactionCtx;所以 set_reaction_kind 直接写"当前 hook ctx"。
		// 由于 builtin 调用时 ctx 通过 makeHookFn captures 路径传 hook,
		// 我们用 game-level Pending 字段绕一圈:set_reaction_kind 写入
		// rt.Game.PendingReactionKind, damage.go 在 reaction stage 完成
		// 后 copy 到 ctx.ReactionKind。
		rt.Game.PendingReactionKind = id
		return nil, nil
	}))
	g.SetLocal("context_player", GoFunc((*Runtime).builtinContextPlayer))
	g.SetLocal("force_switch_next", GoFunc((*Runtime).builtinForceSwitchNext))
	g.SetLocal("cancel", GoFunc((*Runtime).builtinCancel))
	g.SetLocal("gain_energy", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		proxy, ok := args[0].(*CounterProxy)
		if !ok {
			return nil, fmt.Errorf("gain_energy: arg 1 must be a counter proxy (e.g. char:energy()), got %T", args[0])
		}
		value, _ := ToInt(args[1])
		rt.Game.GainEnergy(proxy.ID, value)
		return nil, nil
	}))
	g.SetLocal("consume_energy", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		proxy, ok := args[0].(*CounterProxy)
		if !ok {
			return nil, fmt.Errorf("consume_energy: arg 1 must be a counter proxy (e.g. char:energy()), got %T", args[0])
		}
		value, _ := ToInt(args[1])
		rt.Game.ConsumeEnergy(proxy.ID, value)
		return nil, nil
	}))

	// --- Extra API ---
	g.SetLocal("set_alive", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		p, _ := ToInt(args[0])
		c, _ := ToInt(args[1])
		alive := ToBool(args[2])
		rt.Game.SetAlive(rt.ResolvePlayer(p), c, alive)
		return nil, nil
	}))
	g.SetLocal("request_switch", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		p, _ := ToInt(args[0])
		rp := rt.ResolvePlayer(p)
		rt.Game.DeferAction(&engine.Action{
			Kind:      engine.ActionSwitch,
			PlayerIdx: rp,
			Forced:    true,
		})
		return nil, nil
	}))
	g.SetLocal("get_turn", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		return rt.Game.Turn, nil
	}))
	g.SetLocal("set_winner", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		w, _ := ToInt(args[0])
		rt.Game.SetWinner(w)
		return nil, nil
	}))
	g.SetLocal("has_card_in_own_hand", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		// Query only the *current context player's* own hand. Cross-player
		// hand-content queries are forbidden by design — they would leak
		// private information across the information-set boundary and
		// corrupt IS-MCTS determinization. See docs/az/decisions.md D9 and
		// docs/az/determinization.md "information set integrity".
		rp := rt.CurrentContextPlayer
		if rp < 0 || rp > 1 {
			return false, nil
		}
		var cardRef int
		switch v := args[0].(type) {
		case *CardRef:
			cardRef = v.Ref
		case int:
			cardRef = v
		}
		for _, c := range rt.Game.Players[rp].Hand {
			if c.Ref == cardRef {
				return true, nil
			}
		}
		return false, nil
	}))
	g.SetLocal("draw_card", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		p, _ := ToInt(args[0])
		count := 1
		if len(args) > 1 && args[1] != nil {
			count, _ = ToInt(args[1])
		}
		rp := rt.ResolvePlayer(p)
		for i := 0; i < count; i++ {
			rt.Game.DrawCard(rp)
		}
		return nil, nil
	}))

	// --- Dice API ---
	g.SetLocal("roll_dice", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		p, _ := ToInt(args[0])
		n, _ := ToInt(args[1])
		rp := rt.ResolvePlayer(p)
		rt.RollDice(rp, n)
		return nil, nil
	}))
	g.SetLocal("clear_dice_pool", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		p, _ := ToInt(args[0])
		rp := rt.ResolvePlayer(p)
		rt.ClearDice(rp)
		return nil, nil
	}))
	g.SetLocal("get_dice_count", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		p, _ := ToInt(args[0])
		color, _ := ToInt(args[1])
		rp := rt.ResolvePlayer(p)
		return rt.GetDiceCount(rp, color), nil
	}))

	// --- Cost modification API ---
	// cost_mod(ctx, slot, delta) — mutate ctx.Cost by delta in the
	// identified CostSlot. Automatically records the currently firing
	// hook ID into ctx.AppliedMods so consumer hooks can later query
	// was_applied(ctx, hook_id) to decide whether to consume a charge.
	// A DSL author who wants "precise consumption" should gate this
	// call behind `if cost_total(ctx) == 0 then return end` so the
	// mod (and the mark) only fire when there's actual cost to modify.
	g.SetLocal("cost_mod", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		cp, _ := args[0].(*CtxProxy)
		if cp == nil || cp.Ctx == nil {
			return nil, nil
		}
		slot, _ := ToInt(args[1])
		delta, _ := ToInt(args[2])
		cp.Ctx.Cost.Mod(engine.CostSlot(slot), delta)
		if cp.Ctx.CurrentHookID >= 0 {
			if cp.Ctx.AppliedMods == nil {
				cp.Ctx.AppliedMods = make(map[int]bool)
			}
			cp.Ctx.AppliedMods[cp.Ctx.CurrentHookID] = true
		}
		return nil, nil
	}))
	// cost_total(ctx) — returns the clamped total of ctx.Cost (negative
	// slots treated as 0). Used as the "gate" for consume-aware
	// discounts: `if cost_total(ctx) == 0 then return end`.
	g.SetLocal("cost_total", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		cp, _ := args[0].(*CtxProxy)
		if cp == nil || cp.Ctx == nil {
			return 0, nil
		}
		return cp.Ctx.Cost.ClampedTotal(), nil
	}))
	// was_applied(ctx, hook_id) — returns true if cost_mod was called
	// from the hook with that ID on this action's candidate-enumeration
	// pass. Discount consumer hooks call this to decide whether to
	// consume their charge.
	g.SetLocal("was_applied", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		cp, _ := args[0].(*CtxProxy)
		if cp == nil || cp.Ctx == nil {
			return false, nil
		}
		hookID, _ := ToInt(args[1])
		if cp.Ctx.AppliedMods == nil {
			return false, nil
		}
		return cp.Ctx.AppliedMods[hookID], nil
	}))

	// --- Write hook API ---
	g.SetLocal("on_before_write", GoFunc((*Runtime).builtinOnBeforeWrite))
	g.SetLocal("on_after_write", GoFunc((*Runtime).builtinOnAfterWrite))

	// --- Event hook API ---
	rt.registerHookFunctions()
}

// registerEnums lives in builtins_enums.go.

// Domain-specific builtin implementations live in sibling files:
//   builtins_counter.go  — counter declare/get/group, write hooks
//   builtins_char.go     — declare/bind/get_char, alive transitions
//   builtins_skill.go    — declare/get/invoke skill + canonical hooks
//   builtins_card.go     — declare/get/add_card + canonical hooks
//   builtins_action.go   — deal_damage, heal, active_char, etc.
//   builtins_hook.go     — makeHookFn, callClosure, on_* dispatch
