package tests

// TestDeclareShieldSpike — ADR-0019 §B.4 spike。
// 验证 declare_shield(name, scope, count, opts) 一行宏:
//   1. 创建带 Tag.Shield 的 counter
//   2. 自动注册 on_damage_reduce hook (Piercing skip + min consume + delta)
//   3. 多 stack 护盾正确消耗(N=3 stack 受 5 dmg → 0 stack + dmg 剩 2)

import (
	"testing"

	"gicg_mono/gicg_engine/interp"

	engine "gicg_mono/gicg_engine"
)

func TestDeclareShieldSpike(t *testing.T) {
	env := NewGameWithDeck(t, []string{"墨客"}, []string{"墨客"})
	sandbox := interp.NewEnv(env.RT.Interp.Global)
	g := env.G

	// declare_shield 创建 PerPlayer scope 护盾,初始 0
	src := `
declare_shield("test_shield", Scope.PerPlayer, 0, { max = 10 })
local s = get_counter("test_shield", Scope.PerPlayer)
test_shield_init = s:get_at(0)  -- expect 0 for P0
`
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src), sandbox); err != nil {
		t.Fatalf("declare_shield: %v", err)
	}

	// Find counter ID
	var shieldID int = -1
	for id, name := range g.CounterNames {
		if name == "test_shield" {
			shieldID = id
			break
		}
	}
	if shieldID < 0 {
		t.Fatalf("test_shield counter 未声明")
	}

	// Set P1 shield = 3 stacks (target P1 — 受打的人)
	// PerPlayer scope: counter ID 是 player-keyed,需要通过 PerPlayerProxy 设
	src2 := `
local s = get_counter("test_shield", Scope.PerPlayer)
s:set_at(1, 3)  -- P1 shield = 3
`
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src2), sandbox); err != nil {
		t.Fatalf("set shield: %v", err)
	}

	// Trigger 5 物理 damage to P1 char 0 → 护盾吸 3 + 实际 2 dmg
	p1HpID := env.RT.Chars.BySlot[1][0].HPCounterID
	hpBefore := g.Counters[p1HpID].Value

	g.PushEvent(engine.EventFrame{Player: 0, Char: 0, ActionCtx: engine.ActUseSkill})
	g.DealDamage(p1HpID, engine.ElemPhysical, 5, engine.DamageOpts{
		ActorPlayer: 0, ActorChar: 0,
	})
	g.PopEvent()

	hpAfter := g.Counters[p1HpID].Value
	hpDelta := hpBefore - hpAfter
	if hpDelta != 2 {
		t.Errorf("HP delta = %d, want 2 (5 dmg - 3 shield)", hpDelta)
	}

	// 检查 shield 应消耗到 0
	src3 := `
local s = get_counter("test_shield", Scope.PerPlayer)
shield_remaining = s:get_at(1)
`
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src3), sandbox); err != nil {
		t.Fatalf("read shield: %v", err)
	}
	v, _ := sandbox.Get("shield_remaining")
	got, _ := toIntForShield(v)
	if got != 0 {
		t.Errorf("shield remaining = %d, want 0", got)
	}

	// Test Piercing skip — 护盾 set 回 5,Piercing 5 dmg 应直接扣 5,护盾不动
	src4 := `
local s = get_counter("test_shield", Scope.PerPlayer)
s:set_at(1, 5)
`
	env.RT.Interp.ExecFile(env.RT, []byte(src4), sandbox)

	hpBefore = g.Counters[p1HpID].Value
	g.PushEvent(engine.EventFrame{Player: 0, Char: 0, ActionCtx: engine.ActUseSkill})
	g.DealDamage(p1HpID, engine.ElemPiercing, 3, engine.DamageOpts{
		ActorPlayer: 0, ActorChar: 0,
	})
	g.PopEvent()

	hpAfter = g.Counters[p1HpID].Value
	if hpBefore-hpAfter != 3 {
		t.Errorf("Piercing dmg HP delta = %d, want 3 (Piercing skip 护盾)", hpBefore-hpAfter)
	}

	src5 := `
local s = get_counter("test_shield", Scope.PerPlayer)
shield_after_piercing = s:get_at(1)
`
	env.RT.Interp.ExecFile(env.RT, []byte(src5), sandbox)
	v2, _ := sandbox.Get("shield_after_piercing")
	got2, _ := toIntForShield(v2)
	if got2 != 5 {
		t.Errorf("shield after Piercing = %d, want 5 (未消耗)", got2)
	}
}

func toIntForShield(v any) (int, bool) {
	switch x := v.(type) {
	case int:
		return x, true
	case int64:
		return int(x), true
	case float64:
		return int(x), true
	}
	return 0, false
}
