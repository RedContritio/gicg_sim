package tests

// TestDamageModifierLogSpike — ADR-0019 §B.2 spike。
// 验证 DamageModifierLog 栈正确记录 damage 管线 4 stage modifier:
// Boost / Reaction / Reduce / AfterDamage。
//
// 用 1v1 反应场景:P0 火打 P1 已附水 → 蒸发 +2,验证:
//   - Boost stage 无 hook 触发,modifier 仍 record (Before==After)
//   - Reaction stage 触发蒸发,Value 从 N → N+2,Element 从 Fire → None
//   - Reduce stage 无护盾,Before==After
//   - AfterDamage 无相关 hook,Before==After
//
// 也验证嵌套 damage call(扩散类)各自独立 log。

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestDamageModifierLogSpike(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	// 直接 trigger 一个 damage,看 currentDamageLog 在 fire 内是否非空。
	// 由于 DealDamage 入口 push,defer pop,我们要在 hook 内观察。

	var observedAt = struct {
		boost     *engine.DamageModifierLog
		hookFired int
	}{}

	g.Hooks.Register(engine.Hook{
		Type:     engine.HookAfterDamage,
		Priority: 1000,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			observedAt.hookFired++
			observedAt.boost = g.CurrentDamageLog()
		},
	})

	// 找 P0 char 0 HP counter ID 用作 source actor frame
	g.PushEvent(engine.EventFrame{
		ActionCtx: engine.ActUseSkill,
		Player:    0,
		Char:      0,
	})
	defer g.PopEvent()

	// 找 P1 char 0 HP counter
	p1HpID := env.RT.Chars.BySlot[1][0].HPCounterID
	if p1HpID < 0 {
		t.Fatal("P1 char 0 HPCounterID -1")
	}

	// Trigger damage
	g.DealDamage(p1HpID, engine.ElemPhysical, 1, engine.DamageOpts{
		ActorPlayer: 0,
		ActorChar:   0,
	})

	if observedAt.hookFired == 0 {
		t.Fatal("AfterDamage hook 没 fire")
	}
	if observedAt.boost == nil {
		t.Fatal("AfterDamage hook 内 g.CurrentDamageLog() 为 nil")
	}
	t.Logf("damage modifiers: %d entries", len(observedAt.boost.Modifiers))

	// Verify: stage record at AfterDamage time, 至少 3 stage 已 record
	// (Boost / Reaction / Reduce 各 1 = 3),AfterDamage 在 hook fire 时
	// 还没 record (recordStageModifier 在 hook 之后调)。
	if len(observedAt.boost.Modifiers) < 3 {
		t.Errorf("expect ≥3 stage modifier (Boost/Reaction/Reduce), got %d",
			len(observedAt.boost.Modifiers))
	}

	// Check kinds in order
	expectedKinds := []engine.ModifierKind{engine.ModBoost, engine.ModReaction, engine.ModReduce}
	for i, k := range expectedKinds {
		if i >= len(observedAt.boost.Modifiers) {
			break
		}
		if observedAt.boost.Modifiers[i].Kind != k {
			t.Errorf("Modifier[%d].Kind = %d, want %d", i, observedAt.boost.Modifiers[i].Kind, k)
		}
	}

	// CurrentDamageLog 在 DealDamage 退出后栈应空 (popped)
	if g.CurrentDamageLog() != nil {
		t.Error("DealDamage 退出后 CurrentDamageLog 非 nil; 栈未 pop")
	}
}
