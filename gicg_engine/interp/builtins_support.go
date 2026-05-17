package interp

import (
	engine "gicg_mono/gicg_engine"
)

// Support zone DSL builtins:
//   - remove_support(player, card_ref) — splice from Supports, push to
//     Discard, fire HookSupportRemove. No-op if card_ref absent (DSL
//     callers may invoke multiple times to be safe, e.g. dual triggers).
//   - count_support(player) — return current Supports length. For
//     future reactive conditions ("our support zone has N cards").
//
// HookSupportRemove fires AFTER the splice + Discard push, so any DSL
// on_support_remove hook observes the canonical post-state (the card
// is no longer in Supports and is already in Discard).
func (rt *Runtime) registerSupportBuiltins() {
	g := rt.Interp.Global

	g.SetLocal("remove_support", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		p, _ := ToInt(args[0])
		var cardRef int
		switch v := args[1].(type) {
		case *CardRef:
			cardRef = v.Ref
		case int:
			cardRef = v
		}
		rp := rt.ResolvePlayer(p)
		if rp < 0 || rp > 1 {
			return nil, nil
		}
		sup := rt.Game.Players[rp].Supports
		for i, s := range sup {
			if s.Ref == cardRef {
				rt.Game.Players[rp].Supports = append(sup[:i], sup[i+1:]...)
				rt.Game.Players[rp].Discard = append(
					rt.Game.Players[rp].Discard,
					engine.CardInst{Ref: cardRef, DrawnAtRound: rt.Game.Round},
				)
				ctx := &engine.EventContext{ActorPlayer: rp, CardRef: cardRef}
				rt.Game.FireEventHooks(engine.HookSupportRemove, ctx)
				return nil, nil
			}
		}
		return nil, nil
	}))

	g.SetLocal("count_support", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		p, _ := ToInt(args[0])
		rp := rt.ResolvePlayer(p)
		if rp < 0 || rp > 1 {
			return 0, nil
		}
		return len(rt.Game.Players[rp].Supports), nil
	}))
}
