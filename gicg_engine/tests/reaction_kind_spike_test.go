package tests

// TestReactionKindSpike — ADR-0019 §B.3a spike。
// 验证:
//   1. declare_reaction 注册 + idempotent (重复 declare 同名 return 同 ID)
//   2. ReactionRegistry name → ID + ReactionNames ID → name 反查
//   3. 蒸发反应触发后 ctx.reaction_kind == Vaporize ID
//   4. 非反应伤害 ctx.reaction_kind == 0 (ReactionNone)

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestReactionKindSpike(t *testing.T) {
	env := NewGameWithDeck(t, []string{"墨客"}, []string{"墨客"})
	g := env.G

	// 8 reactions 加载后,registry 应已注册
	expectedNames := []string{
		"Vaporize", "Melt", "Overload", "Superconduct",
		"ElectroCharged", "Frozen", "Shatter", "Crystallize",
	}
	for _, name := range expectedNames {
		id, ok := g.ReactionRegistry[name]
		if !ok || id == 0 {
			t.Errorf("reaction %q not registered (id=%d ok=%v)", name, id, ok)
		}
	}
	if g.ReactionCount() < 8 {
		t.Errorf("ReactionCount = %d, expect ≥ 8", g.ReactionCount())
	}

	// Idempotent: 重复 declare 同名 → 同 ID
	id1 := g.DeclareReaction("Vaporize")
	id2 := g.DeclareReaction("Vaporize")
	if id1 != id2 {
		t.Errorf("DeclareReaction idempotent fail: id1=%d id2=%d", id1, id2)
	}

	// 反查 ID → name
	if name := g.ReactionName(id1); name != "Vaporize" {
		t.Errorf("ReactionName(%d) = %q, want Vaporize", id1, name)
	}

	// 触发蒸发反应观察 ctx.ReactionKind
	var capturedReactionKind int
	g.Hooks.Register(engine.Hook{
		Type:     engine.HookAfterDamage,
		Priority: 1000,
		Fn: func(_ *engine.Game, ctx *engine.EventContext) {
			capturedReactionKind = ctx.ReactionKind
		},
	})

	// 找 P1 char 0 HP + 水附着 counter
	p1HpID := env.RT.Chars.BySlot[1][0].HPCounterID
	if p1HpID < 0 {
		t.Fatal("P1 HP counter -1")
	}

	// 找水附着 counter — 通过 g.CounterNames 反查
	var waterAuraID int = -1
	for id, name := range g.CounterNames {
		if name == "水元素附着" {
			waterAuraID = id
			break
		}
	}
	if waterAuraID < 0 {
		t.Skip("水元素附着 counter 未声明,跳过 reaction 触发子测;基础 registry 已 PASS")
	}

	// 找 P1 char 0 的 PerChar 水附着 — 实际反查复杂,直接遍历 counterCharMap
	// 简化:set 所有水附着到 1(覆盖目标)
	// 暴力法:直接对 P1 char 0 的 PerChar 水附着 counter id 写,先找
	// 实际我们用 lua DSL 写 set:
	src := `
local water = get_counter("水元素附着", Scope.PerChar)
water:set_at(1, 0, 1)
`
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env.RT.Interp.Global); err != nil {
		t.Fatalf("set water aura: %v", err)
	}

	// Trigger fire damage on P1 char 0 (蒸发触发)
	g.PushEvent(engine.EventFrame{
		ActionCtx: engine.ActUseSkill,
		Player:    0,
		Char:      0,
	})
	g.DealDamage(p1HpID, engine.ElemFire, 2, engine.DamageOpts{
		ActorPlayer: 0, ActorChar: 0,
	})
	g.PopEvent()

	if capturedReactionKind == 0 {
		t.Errorf("蒸发反应触发后 ctx.ReactionKind = 0 (ReactionNone), 期望 Vaporize ID=%d",
			g.ReactionRegistry["Vaporize"])
	}
	if capturedReactionKind != g.ReactionRegistry["Vaporize"] {
		t.Errorf("ctx.ReactionKind = %d, expect Vaporize=%d",
			capturedReactionKind, g.ReactionRegistry["Vaporize"])
	}

	// 非反应伤害 — P1 char 0 现在水附着已被消耗,纯火伤害无反应
	capturedReactionKind = -1 // sentinel
	g.PushEvent(engine.EventFrame{
		ActionCtx: engine.ActUseSkill,
		Player:    0,
		Char:      0,
	})
	g.DealDamage(p1HpID, engine.ElemPhysical, 1, engine.DamageOpts{
		ActorPlayer: 0, ActorChar: 0,
	})
	g.PopEvent()

	if capturedReactionKind != engine.ReactionNone {
		t.Errorf("无反应伤害 ctx.ReactionKind = %d, expect 0 (ReactionNone)", capturedReactionKind)
	}
}
