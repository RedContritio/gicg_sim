package interp

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
)

// Damage/heal actions, target resolution and active-character helpers.

func (rt *Runtime) builtinDealDamage(args []Value) (Value, error) {
	target, _ := ToInt(args[0])
	elemVal, _ := ToInt(args[1])
	value, _ := ToInt(args[2])

	elem := engine.Element(elemVal)

	// 4th arg (opts table) may carry `source = Source.X` to override the
	// event-stack source — DSL pattern e.g. {source=Source.Status} so that
	// hooks gated on `ctx.source == Source.Skill` don't recursively
	// re-trigger themselves from the nested damage event. Before this fix
	// (review of pilot replay sid3 case B), args[3] was silently dropped
	// → nested deal_damage inherited the outer skill source → on_after_damage
	// hooks like 墨客泼墨 recursed until MaxDepth / target death (5 swim
	// attacks vs 泼墨=2 expected). Affected DSL: 墨客_水龙吟 / 蝶鳞 /
	// 星愿 / 以逸待劳 / 玄冰 / 以牙还牙 / 歼灭机关_技能 (11+ files).
	source := engine.SrcNone
	var actor *CharProxy
	var targetCounter *PerCharProxy
	otherCharacters := false
	if len(args) > 3 && args[3] != nil {
		if opts, ok := args[3].(*Table); ok && opts != nil {
			if v, ok := opts.Fields["other_characters"]; ok {
				var valid bool
				otherCharacters, valid = v.(bool)
				if !valid {
					return nil, fmt.Errorf("other_characters requires boolean")
				}
			}
			if v, ok := opts.Fields["actor"]; ok {
				var valid bool
				actor, valid = v.(*CharProxy)
				if !valid || actor == nil || actor.Entry == nil {
					return nil, fmt.Errorf("deal_damage actor requires a character")
				}
			}
			if v, ok := opts.Fields["target_counter"]; ok {
				var valid bool
				targetCounter, valid = v.(*PerCharProxy)
				if !valid || targetCounter == nil || targetCounter.RefKind != RefKindNone {
					return nil, fmt.Errorf("deal_damage target_counter requires a numeric PerChar counter")
				}
			}
			if v, ok := opts.Fields["source"]; ok {
				si, _ := ToInt(v)
				source = engine.Source(si)
			}
		}
	}

	if actor != nil {
		frame := rt.Game.MustCurrentEvent("deal_damage actor")
		frame.Player, frame.Char = actor.Entry.PlayerIdx, actor.Entry.CharIdx
		rt.Game.PushEvent(frame)
		defer rt.Game.PopEvent()
	}
	hpIDs := rt.resolveTargetHP(target)
	if ch, ok := args[0].(*CharProxy); ok {
		hpIDs = nil
		if rt.Game.Players[ch.Entry.PlayerIdx].Chars[ch.Entry.CharIdx].Alive {
			hpIDs = []int{ch.Entry.HPCounterID}
		}
	}
	if otherCharacters {
		ch, ok := args[0].(*CharProxy)
		if !ok || ch == nil || ch.Entry == nil {
			return nil, fmt.Errorf("other_characters requires a character target")
		}
		hpIDs = rt.otherCharacterHP(ch)
	}
	if targetCounter != nil {
		hpIDs = rt.filterDamageTargets(hpIDs, targetCounter)
	}
	for _, hpID := range hpIDs {
		rt.Game.DealDamage(hpID, elem, value, engine.DamageOpts{
			Source:      source,
			ActorPlayer: -1,
			ActorChar:   -1,
		})
		if rt.Game.Phase == engine.PhaseGameOver {
			break
		}
	}
	return nil, nil
}

func (rt *Runtime) builtinDeferFn(args []Value) (Value, error) {
	fn, _ := args[0].(*Closure)
	// Snapshot runtime context at defer-QUEUE time. Dynamic resolvers
	// inside the fn body (e.g. Target.EnemyActive, Player.Own, Self
	// counter lookup) resolve via CurrentContextPlayer /
	// CurrentOwnerPlayer/Char. Without this snapshot, DrainDeferred
	// firing later in the event stack would see whatever values are
	// current at fire time — typically a different hook's context,
	// or the restored outer context (−1) — silently retargeting the
	// deferred effect to the wrong player. Observed in card DSL like
	// 以逸待劳.lua where defer_fn(deal_damage(Target.EnemyActive, ...))
	// relies on CurrentContextPlayer being the queuing hook's owner.
	queuedCtxPlayer := rt.CurrentContextPlayer
	queuedOwnerPlayer := rt.CurrentOwnerPlayer
	queuedOwnerChar := rt.CurrentOwnerChar
	rt.Game.Defer(func(g *engine.Game) {
		prevCtx := rt.CurrentContextPlayer
		prevOwnerP := rt.CurrentOwnerPlayer
		prevOwnerC := rt.CurrentOwnerChar
		rt.CurrentContextPlayer = queuedCtxPlayer
		rt.CurrentOwnerPlayer = queuedOwnerPlayer
		rt.CurrentOwnerChar = queuedOwnerChar
		defer func() {
			rt.CurrentContextPlayer = prevCtx
			rt.CurrentOwnerPlayer = prevOwnerP
			rt.CurrentOwnerChar = prevOwnerC
		}()
		rt.callClosure(fn, nil)
	})
	return nil, nil
}

func (rt *Runtime) builtinGetActiveChar(args []Value) (Value, error) {
	p, _ := ToInt(args[0])
	rp := rt.ResolvePlayer(p)
	return rt.Game.Players[rp].ActiveChar, nil
}

func (rt *Runtime) builtinSetActiveChar(args []Value) (Value, error) {
	p, _ := ToInt(args[0])
	c, _ := ToInt(args[1])
	rp := rt.ResolvePlayer(p)
	rt.Game.ForceSwitchTo(rp, c)
	return nil, nil
}

func (rt *Runtime) builtinGetNextChar(args []Value) (Value, error) {
	p, _ := ToInt(args[0])
	c, _ := ToInt(args[1])
	rp := rt.ResolvePlayer(p)
	// Find next alive char after c
	pl := &rt.Game.Players[rp]
	n := len(pl.Chars)
	for i := 1; i < n; i++ {
		idx := (c + i) % n
		if pl.Chars[idx].Alive {
			return idx, nil
		}
	}
	return c, nil // no other alive
}

func (rt *Runtime) builtinContextPlayer(args []Value) (Value, error) {
	return rt.CurrentContextPlayer, nil
}

func (rt *Runtime) builtinForceSwitchNext(args []Value) (Value, error) {
	p, _ := ToInt(args[0])
	rp := rt.ResolvePlayer(p)
	// Find next alive char and set as active
	pl := &rt.Game.Players[rp]
	n := len(pl.Chars)
	for i := 1; i < n; i++ {
		idx := (pl.ActiveChar + i) % n
		if pl.Chars[idx].Alive {
			rt.Game.ForceSwitchTo(rp, idx)
			break
		}
	}
	return nil, nil
}

func (rt *Runtime) builtinCancel(args []Value) (Value, error) {
	if rt.currentHookContext == nil {
		return nil, fmt.Errorf("cancel: no active hook context")
	}
	rt.currentHookContext.Cancelled = true
	return nil, nil
}

// --- Target Resolution ---

func (rt *Runtime) resolveTargetHP(target int) []int {
	g := rt.Game
	// 目标解析必须有事件帧(含 CardTarget:卡目标解析只发生在 card-play
	// 帧内)。空栈 = 无帧 hook 误调伤害类 builtin,fail loud。
	cur := g.MustCurrentEvent("resolveTargetHP")
	actorPlayer := cur.Player

	switch target {
	case 1: // EnemyActive
		enemy := 1 - actorPlayer
		active := g.Players[enemy].ActiveChar
		entry := rt.Chars.BySlot[enemy][active]
		if entry != nil {
			return []int{entry.HPCounterID}
		}
	case 2: // EnemyAll
		enemy := 1 - actorPlayer
		var ids []int
		for c, entry := range rt.Chars.BySlot[enemy] {
			if entry != nil && g.Players[enemy].Chars[c].Alive {
				ids = append(ids, entry.HPCounterID)
			}
		}
		return ids
	case 3: // OwnAll
		var ids []int
		for c, entry := range rt.Chars.BySlot[actorPlayer] {
			if entry != nil && g.Players[actorPlayer].Chars[c].Alive {
				ids = append(ids, entry.HPCounterID)
			}
		}
		return ids
	case 4: // EnemyNonActive
		enemy := 1 - actorPlayer
		active := g.Players[enemy].ActiveChar
		var ids []int
		for c, entry := range rt.Chars.BySlot[enemy] {
			if entry != nil && c != active && g.Players[enemy].Chars[c].Alive {
				ids = append(ids, entry.HPCounterID)
			}
		}
		return ids
	case 5: // OwnActive
		active := g.Players[actorPlayer].ActiveChar
		entry := rt.Chars.BySlot[actorPlayer][active]
		if entry != nil {
			return []int{entry.HPCounterID}
		}
	case 6: // CardTarget
		p, c := g.CardTarget()
		entry := rt.Chars.BySlot[p][c]
		if entry != nil {
			return []int{entry.HPCounterID}
		}
	}
	return nil
}

// --- Death check ---

func (rt *Runtime) registerDeathCheck(charEntry *CharEntry, playerIdx, charIdx int) {
	hpID := charEntry.HPCounterID
	aliveID := charEntry.AliveCounterID

	rt.registerHook(engine.Hook{
		Type:      engine.HookAfterWrite,
		CounterID: hpID,
		Op:        engine.OpSub,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			if g.Counters[hpID].Value > 0 {
				return
			}
			g.SetAlive(playerIdx, charIdx, false)
			// Writing alive counter 1→0 triggers the alive transition hook
			// which fires HookDeath → DSL handlers (element clearing,
			// alive_count decrement, etc.) all live in system/*.lua now.
			if aliveID >= 0 {
				g.WriteCounter(aliveID, engine.OpSet, 0)
			}
			// Request forced switch ONLY when the dying char was the
			// active one. Non-active deaths must NOT queue a switch —
			// the owner keeps playing with their current active, and
			// queuing a pointless Switch there led to a deadlock when
			// a multi-target wipe killed all non-actives leaving only
			// the active alive: forcedSwitchActions then excludes the
			// active and returns an empty list, leaving the engine in
			// phase=Action with no legal moves. Reproducer:
			// tools/diag_long_episode.py --seed 2067 (pre-fix).
			if g.Phase != engine.PhaseGameOver &&
				g.Players[playerIdx].ActiveChar == charIdx {
				g.DeferAction(&engine.Action{
					Kind:      engine.ActionSwitch,
					PlayerIdx: playerIdx,
					Forced:    true,
				})
			}
		},
	})
}

// --- Hook helpers ---
