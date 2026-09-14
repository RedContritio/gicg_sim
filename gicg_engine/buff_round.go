package engine

import "sort"

type roundBuffCall struct {
	buffHookCall
	player, char int
	summon       bool
}

// Round stages and priorities remain separate. Ordinary buffs use global
// creation order. Summons use ending-player order, then creation order.
// Reorder only summon slots so mixed stages cannot perturb ordinary FIFO.
func (g *Game) scheduleRoundHooks(kind HookType, order []int) []roundBuffCall {
	var calls []roundBuffCall
	for _, h := range g.Hooks.GetEventHooks(kind) {
		if h.OrderCounter == nil {
			players := order
			if h.OwnerPlayer != FilterAny {
				players = []int{h.OwnerPlayer}
			}
			for _, p := range players {
				calls = append(calls, roundBuffCall{buffHookCall{hook: h, rank: -1}, p, h.OwnerChar, false})
			}
			continue
		}
		for rank, b := range g.Buffs {
			d := g.BuffDefinitions[b.Definition]
			owner := g.GetCounterChar(d.CounterID)
			expectedOwner := h.OwnerPlayer
			if h.OrderTarget && expectedOwner >= 0 {
				expectedOwner = 1 - expectedOwner
			}
			if expectedOwner != FilterAny && expectedOwner != owner[0] {
				continue
			}
			for _, id := range h.OrderIDs {
				if id == d.CounterID {
					calls = append(calls, roundBuffCall{buffHookCall{h, b.ID, rank}, owner[0], owner[1], d.Summon})
					break
				}
			}
		}
	}
	sort.SliceStable(calls, func(i, j int) bool {
		if calls[i].hook.Priority != calls[j].hook.Priority {
			return calls[i].hook.Priority > calls[j].hook.Priority
		}
		return calls[i].rank < calls[j].rank
	})
	playerRank := map[int]int{}
	for i, p := range order {
		playerRank[p] = i
	}
	for start := 0; start < len(calls); {
		end := start + 1
		for end < len(calls) && calls[end].hook.Priority == calls[start].hook.Priority {
			end++
		}
		var slots []int
		var summons []roundBuffCall
		for i := start; i < end; i++ {
			if calls[i].summon {
				slots = append(slots, i)
				summons = append(summons, calls[i])
			}
		}
		sort.SliceStable(summons, func(i, j int) bool {
			return playerRank[summons[i].player] < playerRank[summons[j].player]
		})
		for i, slot := range slots {
			calls[slot] = summons[i]
		}
		start = end
	}
	return calls
}

func (g *Game) FirePerPlayerHooks(kind HookType, ctx *EventContext, order []int) {
	g.publicRound(kind)
	for _, call := range g.scheduleRoundHooks(kind, order) {
		if !call.hook.Enabled || (call.instance != 0 && g.buffByID(call.instance) == nil) {
			continue
		}
		g.fireRoundBuff(call, ctx)
		if g.Phase == PhaseGameOver {
			return
		}
	}
}

func (g *Game) fireRoundBuff(call roundBuffCall, ctx *EventContext) {
	oldP, oldC := ctx.ActorPlayer, ctx.ActorChar
	ctx.ActorPlayer, ctx.ActorChar = call.player, call.char
	g.PushEvent(EventFrame{Player: call.player, Char: call.char})
	defer func() { g.PopEvent(); ctx.ActorPlayer, ctx.ActorChar = oldP, oldC }()
	g.invokeBuffHook(call.buffHookCall, ctx)
	g.DrainDeferred()
}
