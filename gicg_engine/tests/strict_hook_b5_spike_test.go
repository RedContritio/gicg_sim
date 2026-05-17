package tests

// TestStrictHookB5Spike — ADR-0019 §B.5 minimal spike (opt-in 而非 strict)。
// 验证 6 新 hook 时机加入 + DSL 可注册 + dispatch 顺序正确。
//
// strict 拆 4+3 完整路径(删旧 HookDamageBoost / HookDamageReduce + DSL
// 全部 audit 迁移)留后续 session;本 spike 仅落地新时机基础设施 + 验证
// 时机 fire 顺序对齐 ADR §B.5 ADR strict 流水线。

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestStrictHookB5Spike(t *testing.T) {
	env := NewGameWithDeck(t, []string{"墨客"}, []string{"墨客"})
	g := env.G

	// 注册 6 新 hook 时机各 1 hook,记录 fire 顺序
	var fireOrder []string

	g.Hooks.Register(engine.Hook{
		Type: engine.HookDamageType,
		Fn:   func(_ *engine.Game, _ *engine.EventContext) { fireOrder = append(fireOrder, "Type") },
	})
	g.Hooks.Register(engine.Hook{
		Type: engine.HookDamageAdd,
		Fn:   func(_ *engine.Game, _ *engine.EventContext) { fireOrder = append(fireOrder, "Add") },
	})
	g.Hooks.Register(engine.Hook{
		Type: engine.HookDamageMul,
		Fn:   func(_ *engine.Game, _ *engine.EventContext) { fireOrder = append(fireOrder, "Mul") },
	})
	g.Hooks.Register(engine.Hook{
		Type: engine.HookDamageReduceBuff,
		Fn:   func(_ *engine.Game, _ *engine.EventContext) { fireOrder = append(fireOrder, "ReduceBuff") },
	})
	g.Hooks.Register(engine.Hook{
		Type: engine.HookShieldAbsorb,
		Fn:   func(_ *engine.Game, _ *engine.EventContext) { fireOrder = append(fireOrder, "ShieldAbsorb") },
	})
	g.Hooks.Register(engine.Hook{
		Type: engine.HookDamageImmunity,
		Fn:   func(_ *engine.Game, _ *engine.EventContext) { fireOrder = append(fireOrder, "Immunity") },
	})
	g.Hooks.Register(engine.Hook{
		Type: engine.HookAfterDamage,
		Fn:   func(_ *engine.Game, _ *engine.EventContext) { fireOrder = append(fireOrder, "After") },
	})

	// 触发 1 物理伤害(非 piercing,所有 reduce 阶段都 fire)
	p1HpID := env.RT.Chars.BySlot[1][0].HPCounterID
	g.PushEvent(engine.EventFrame{Player: 0, Char: 0, ActionCtx: engine.ActUseSkill})
	g.DealDamage(p1HpID, engine.ElemPhysical, 2, engine.DamageOpts{
		ActorPlayer: 0, ActorChar: 0,
	})
	g.PopEvent()

	// 期望顺序对齐 ADR §B.5 strict 流水线 (旧 Boost/Reduce 已删):
	//   Type → Add → Mul → ReduceBuff → ShieldAbsorb → Immunity → After
	expected := []string{"Type", "Add", "Mul",
		"ReduceBuff", "ShieldAbsorb", "Immunity", "After"}

	if len(fireOrder) != len(expected) {
		t.Errorf("fire 顺序长度 = %d, want %d (%v)", len(fireOrder), len(expected), fireOrder)
		return
	}
	for i, want := range expected {
		if fireOrder[i] != want {
			t.Errorf("fire[%d] = %q, want %q (full: %v)", i, fireOrder[i], want, fireOrder)
		}
	}
}
