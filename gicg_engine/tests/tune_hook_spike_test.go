package tests

// TestTuneHookSpike — ADR-0019 §A.4 / dsl_gaps D3 — 调和 hook
// 验证 DSL on_tune hook 在 ActionTune 执行时被 fire,且 ctx 携带
// 正确的 card_ref + actor_player 数据。
//
// 桓那兰那 (6603 "调和此牌时 X") / 5488_换班时间 类卡的实施基础。

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestTuneHookSpike(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	g.Players[0].ActiveChar = 0
	env.SetDice(0, map[int]int{
		engine.DiceColorIce:   1,
		engine.DiceColorWater: 2,
	})

	type capture struct {
		actor   int
		cardRef int
	}
	var captures []capture
	g.Hooks.Register(engine.Hook{
		Type:     engine.HookOnTune,
		Priority: 1000,
		Fn: func(_ *engine.Game, ctx *engine.EventContext) {
			captures = append(captures, capture{actor: ctx.ActorPlayer, cardRef: ctx.CardRef})
		},
	})

	expectedCardRef := g.Players[0].Hand[0].Ref

	// Find the tune action
	actions := g.GetLegalActions()
	tuneIdx := -1
	for i, a := range actions {
		if a.Kind == engine.ActionTune && a.Index == 0 && a.TuneSourceColor == engine.DiceColorIce {
			tuneIdx = i
			break
		}
	}
	if tuneIdx < 0 {
		t.Fatalf("no tune action found (legal actions: %d)", len(actions))
	}

	env.Step(tuneIdx)

	if len(captures) != 1 {
		t.Fatalf("expected 1 on_tune fire, got %d: %+v", len(captures), captures)
	}
	c := captures[0]
	if c.actor != 0 {
		t.Errorf("ctx.actor_player = %d, want 0", c.actor)
	}
	if c.cardRef != expectedCardRef {
		t.Errorf("ctx.card_ref = %d, want %d (P0 Hand[0])", c.cardRef, expectedCardRef)
	}

	// Test 2: DSL on_tune via lua — verify builtin registered + tokenizer accepts
	// 用 inline DSL register 个 hook,确认 on_tune 在 lua 端可解析
	src := `
local fired_count = declare_counter("on_tune_fire_count", Scope.Global, 0, { min = 0, max = 100 })
on_tune(function(ctx)
  fired_count:set(fired_count:get() + 1)
end)
`
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env.RT.Interp.Global); err != nil {
		t.Fatalf("DSL on_tune register: %v", err)
	}
	var fireCntID int = -1
	for id, name := range g.CounterNames {
		if name == "on_tune_fire_count" {
			fireCntID = id
			break
		}
	}
	if fireCntID < 0 {
		t.Fatalf("on_tune_fire_count counter 未注册")
	}

	// 重置 dice + 再次 tune (hand 还有牌)
	env.SetDice(0, map[int]int{
		engine.DiceColorIce:   1,
		engine.DiceColorWater: 2,
	})
	if len(g.Players[0].Hand) == 0 {
		t.Skip("hand empty, skip 2nd tune")
		return
	}
	actions = g.GetLegalActions()
	tuneIdx = -1
	for i, a := range actions {
		if a.Kind == engine.ActionTune && a.TuneSourceColor == engine.DiceColorIce {
			tuneIdx = i
			break
		}
	}
	if tuneIdx < 0 {
		t.Skip("no tune action, skip 2nd tune verification")
		return
	}
	env.Step(tuneIdx)
	if g.Counters[fireCntID].Value != 1 {
		t.Errorf("DSL on_tune fired %d times, want 1", g.Counters[fireCntID].Value)
	}
}
