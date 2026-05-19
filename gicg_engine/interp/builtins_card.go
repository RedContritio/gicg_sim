package interp

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
)

// Card-family builtins: declare_card, get_card, add_card.
// registerCardHooks (engine-side canonical hook + action_prepare +
// play dispatcher) lives at the tail of the same file.

func (rt *Runtime) builtinDeclareCard(args []Value) (Value, error) {
	name, _ := args[0].(string)

	// New signature: declare_card(name, cost_table, opts?)
	// cost_table = { dices = { any = N, ... }, energy = N }
	// opts = { target = ..., battle_action = ..., requires_weapon = ...,
	//          requires_char = ... }
	var cost engine.Cost
	if len(args) > 1 && args[1] != nil {
		if t, ok := args[1].(*Table); ok {
			cost = parseCost(t)
		}
	}

	battleAction := false
	targetMode := 0
	requiresWeapon := 0
	requiresChar := ""
	slot := SlotNone

	if len(args) > 2 && args[2] != nil {
		opts, _ := args[2].(*Table)
		if opts != nil {
			if v, ok := opts.Fields["battle_action"]; ok {
				battleAction = ToBool(v)
			}
			if v, ok := opts.Fields["target"]; ok {
				switch s, _ := v.(string); s {
				case "own":
					targetMode = 1
				case "enemy":
					targetMode = 2
				default:
					targetMode, _ = ToInt(v)
				}
			}
			if v, ok := opts.Fields["requires_weapon"]; ok {
				requiresWeapon, _ = ToInt(v)
			}
			if v, ok := opts.Fields["requires_char"]; ok {
				requiresChar, _ = v.(string)
			}
			if v, ok := opts.Fields["slot"]; ok {
				si, _ := ToInt(v)
				slot = CardSlot(si)
			}
		}
	}

	refID := rt.Cards.NextRef
	rt.Cards.NextRef++

	cardRef := &CardRef{
		Ref:            refID,
		Name:           name,
		Cost:           cost,
		BattleAction:   battleAction,
		TargetMode:     targetMode,
		RequiresWeapon: requiresWeapon,
		RequiresChar:   requiresChar,
		Slot:           slot,
	}
	rt.Cards.ByName[name] = cardRef
	rt.Cards.ByRef[refID] = cardRef
	ref := refID

	if rt.Game.CardNames == nil {
		rt.Game.CardNames = make(map[int]string)
	}
	rt.Game.CardNames[ref] = name

	// Shared-load talent binding: subsequent Scope.Self / get_char /
	// get_skill calls in the same file will resolve against this name
	// via ctx at hook-fire time. Only set when we're NOT already in a
	// per-binding char load — per-binding already provides a static
	// owner context, no lazy needed.
	if requiresChar != "" && rt.CurrentOwnerPlayer < 0 {
		rt.CurrentFileTalentOwner = requiresChar
	}

	// Register card action hooks
	rt.registerCardHooks(cardRef)

	return cardRef, nil
}

func (rt *Runtime) builtinGetCard(args []Value) (Value, error) {
	name, _ := args[0].(string)
	entry, ok := rt.Cards.ByName[name]
	if !ok {
		return nil, fmt.Errorf("unresolved_dependency:%s", name)
	}
	return entry, nil
}

func (rt *Runtime) builtinAddCard(args []Value) (Value, error) {
	var cardRef int
	switch v := args[0].(type) {
	case *CardRef:
		cardRef = v.Ref
	case int:
		cardRef = v
	}
	zone := 0 // default Hand
	player := rt.CurrentContextPlayer
	if len(args) > 1 && args[1] != nil {
		zone, _ = ToInt(args[1])
	}
	if len(args) > 2 && args[2] != nil {
		p, _ := ToInt(args[2])
		player = rt.ResolvePlayer(p)
	}
	p := &rt.Game.Players[player]
	// DSL-injected cards (e.g. 刻师傅 generates a 复刻) become "held" at
	// the current round; reward shaping treats this as held=0 on the
	// first opportunity to play, just like a freshly drawn card.
	card := engine.CardInst{Ref: cardRef, DrawnAtRound: rt.Game.Round}
	if zone == 0 { // Hand
		p.Hand = append(p.Hand, card)
		if rt.Game.Log != nil {
			rt.Game.Log.Append(rt.Game, "hand_add", player, -1, map[string]interface{}{
				"card_ref": cardRef,
			})
		}
	} else { // Deck
		p.Deck = append(p.Deck, card)
	}
	return nil, nil
}

// --- Action Builtins ---

func (rt *Runtime) registerCardHooks(entry *CardRef) {
	// action_check: verify weapon/char eligibility
	rt.registerHook(engine.Hook{
		Type: engine.HookActionCheck,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			if ctx.ActionKind != engine.ActionCard || ctx.CardRef != entry.Ref {
				return
			}
			// Check weapon requirement
			if entry.RequiresWeapon > 0 {
				charEntry := rt.Chars.BySlot[ctx.ActorPlayer][ctx.ActorChar]
				if charEntry == nil || charEntry.Weapon != entry.RequiresWeapon {
					ctx.Playable = false
					return
				}
			}
			// Check char requirement
			if entry.RequiresChar != "" {
				charEntry := rt.Chars.BySlot[ctx.ActorPlayer][ctx.ActorChar]
				if charEntry == nil || charEntry.Name != entry.RequiresChar {
					ctx.Playable = false
					return
				}
			}
			// Specialty slot 1-card cap: if active char already has any
			// specialty equipped, reject this Slot.Specialty card.
			// Sentinel -1 = empty (since 0 is a valid card_ref).
			// Replacement (new specialty replaces old) is *not* the GI TCG
			// rule — once equipped, the slot is taken until the underlying
			// state expires (e.g. 夜魂值 to 0 discards 刃轮装束).
			if entry.Slot == SlotSpecialty {
				charEntry := rt.Chars.BySlot[ctx.ActorPlayer][ctx.ActorChar]
				if charEntry != nil && charEntry.SpecialtyCardRef >= 0 {
					ctx.Playable = false
					return
				}
			}
			// Support zone cap (GICG canonical 4): reject if Supports full。
			// 不实现 "替换某槽位" — 满则 5th 卡不可出,与 Specialty 同语义。
			if entry.Slot == SlotSupport {
				if len(g.Players[ctx.ActorPlayer].Supports) >= engine.MaxSupportSlots {
					ctx.Playable = false
					return
				}
			}
		},
	})

	// card_play: record specialty slot occupancy when a Slot.Specialty
	// card resolves. Engine-canonical (not DSL): runs before any DSL
	// on_card_play hook so DSL can read the new state.
	if entry.Slot == SlotSpecialty {
		rt.registerHook(engine.Hook{
			Type:     engine.HookCardPlay,
			Priority: 2000, // before canonical (1000) and DSL (default 0)
			Fn: func(g *engine.Game, ctx *engine.EventContext) {
				if ctx.CardRef != entry.Ref {
					return
				}
				charEntry := rt.Chars.BySlot[ctx.ActorPlayer][ctx.ActorChar]
				if charEntry != nil {
					charEntry.SpecialtyCardRef = entry.Ref
				}
			},
		})
	}

	// card_play: push to support zone when a Slot.Support card resolves.
	// Priority 2000 runs before canonical (1000) and DSL (default 0), so
	// DSL on_card_play hooks see Supports already containing the new card.
	if entry.Slot == SlotSupport {
		rt.registerHook(engine.Hook{
			Type:     engine.HookCardPlay,
			Priority: 2000,
			Fn: func(g *engine.Game, ctx *engine.EventContext) {
				if ctx.CardRef != entry.Ref {
					return
				}
				g.Players[ctx.ActorPlayer].Supports = append(
					g.Players[ctx.ActorPlayer].Supports,
					engine.SupportInst{Ref: entry.Ref, ActivatedAt: g.Round},
				)
			},
		})
	}

	// action_prepare: set battle_action and target_mode flags
	rt.registerHook(engine.Hook{
		Type: engine.HookActionPrepare,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			if ctx.ActionKind != engine.ActionCard || ctx.CardRef != entry.Ref {
				return
			}
			ctx.BattleAction = entry.BattleAction
			if entry.TargetMode > 0 {
				ctx.NeedTarget = true
				ctx.TargetMode = entry.TargetMode
			}
		},
	})

	// card_play: canonical hook for the pointer-net (see registerSkillHooks).
	// No side effects — dice are paid by engine's PayDice before this fires.
	hookID := rt.registerHook(engine.Hook{
		Type:     engine.HookCardPlay,
		Priority: 1000,
		Repr:     engine.CanonicalHookRepr{Marker: int16(entry.Ref)},
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			// intentionally empty: canonical hook exists for policy head
			// embedding lookup, not for gameplay side effects
		},
	})
	if rt.Game.CanonicalCardHooks == nil {
		rt.Game.CanonicalCardHooks = make(map[int]int)
	}
	rt.Game.CanonicalCardHooks[entry.Ref] = hookID
}
