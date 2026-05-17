package interp

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
)

// CtxProxy exposes the engine's EventContext to DSL callbacks via
// field access (ctx.value, ctx.actor_player, …). Read-only for most
// fields; the mutable subset listed in SetField is what hook bodies
// are allowed to override (e.g. ctx.value += 2 in a damage_boost).

type CtxProxy struct {
	Ctx *engine.EventContext
}

func (cp *CtxProxy) GetField(rt *Runtime, field string) (Value, error) {
	ctx := cp.Ctx
	switch field {
	case "value":
		return ctx.Value, nil
	case "element":
		return int(ctx.Element), nil
	case "actor_player":
		return ctx.ActorPlayer, nil
	case "actor_char":
		return ctx.ActorChar, nil
	case "target_player":
		return ctx.TargetPlayer, nil
	case "target_char":
		return ctx.TargetChar, nil
	case "skill_index":
		// Return the SkillRef pointer so DSL comparisons are by identity
		if ref, ok := rt.Skills.ByID[ctx.SkillIndex]; ok {
			return ref, nil
		}
		return nil, nil
	case "card_ref":
		if ref, ok := rt.Cards.ByRef[ctx.CardRef]; ok {
			return ref, nil
		}
		return nil, nil
	case "action_kind":
		return int(ctx.ActionKind), nil
	case "action_context":
		return int(ctx.ActionCtx), nil
	case "hand_index":
		return ctx.HandIndex, nil
	case "switch_char":
		return ctx.SwitchChar, nil
	case "source":
		return int(ctx.Source), nil
	case "playable":
		return ctx.Playable, nil
	case "skip_reaction":
		return ctx.SkipReaction, nil
	case "hit":
		return ctx.Hit, nil
	case "cancelled":
		return ctx.Cancelled, nil
	case "battle_action":
		return ctx.BattleAction, nil
	case "need_target":
		return ctx.NeedTarget, nil
	case "target_mode":
		return ctx.TargetMode, nil
	case "energy_cost":
		return ctx.EnergyCost, nil
	case "paid":
		return ctx.Paid, nil
	case "is_specialty":
		return ctx.IsSpecialty, nil
	case "reaction_kind":
		// ADR-0019 §B.3: typed reaction ID (0 = ReactionNone).
		return ctx.ReactionKind, nil
	case "absorbed":
		// ADR-0019 §B.5: damage 管线 reduce 阶段后 ctx.Absorbed = preShieldValue
		// - finalValue。on_after_damage 读取实现以逸待劳类反击 idiom。
		return ctx.Absorbed, nil
	default:
		return nil, nil // unknown fields return nil
	}
}

func (cp *CtxProxy) SetField(rt *Runtime, field string, val Value) error {
	ctx := cp.Ctx
	switch field {
	case "value":
		ctx.Value, _ = ToInt(val)
	case "element":
		v, _ := ToInt(val)
		ctx.Element = engine.Element(v)
	case "playable":
		ctx.Playable = ToBool(val)
	case "skip_reaction":
		ctx.SkipReaction = ToBool(val)
	case "cancelled":
		ctx.Cancelled = ToBool(val)
	case "battle_action":
		ctx.BattleAction = ToBool(val)
	case "need_target":
		ctx.NeedTarget = ToBool(val)
	case "target_mode":
		ctx.TargetMode, _ = ToInt(val)
	case "energy_cost":
		ctx.EnergyCost, _ = ToInt(val)
	case "paid":
		ctx.Paid = ToBool(val)
	default:
		return fmt.Errorf("CtxProxy: cannot set field %q", field)
	}
	return nil
}
