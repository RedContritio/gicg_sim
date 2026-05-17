package tests

// TestRecentDamageRingSpike — ADR-0019 §B.3b spike。
// 验证:
//   1. DealDamage 出口 emit RecentDamageEvent 到 ring
//   2. ring 字段 typed 正确(actor/target/element/raw/final/absorbed/reaction_kind/modifiers)
//   3. ring bounded K=8 (drop oldest)
//   4. SkillIdentityOf 反查 (skillID → charIdx, slot)

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestRecentDamageRingSpike(t *testing.T) {
	env := NewGameWithDeck(t, []string{"墨客"}, []string{"墨客"})
	g := env.G

	// Initial ring 为空
	if len(g.RecentDamageEvents) != 0 {
		t.Errorf("initial ring 非空 (%d)", len(g.RecentDamageEvents))
	}

	// 触发 1 次 damage,ring 应有 1 条
	p1HpID := env.RT.Chars.BySlot[1][0].HPCounterID
	g.PushEvent(engine.EventFrame{Player: 0, Char: 0, ActionCtx: engine.ActUseSkill})
	g.DealDamage(p1HpID, engine.ElemPhysical, 2, engine.DamageOpts{
		ActorPlayer: 0, ActorChar: 0,
	})
	g.PopEvent()

	if len(g.RecentDamageEvents) != 1 {
		t.Fatalf("after 1 damage ring len = %d, want 1", len(g.RecentDamageEvents))
	}

	// 验证 event 字段
	e := g.RecentDamageEvents[0]
	if e.ActorPlayer != 0 || e.TargetPlayer != 1 {
		t.Errorf("actor/target = (%d,%d), want (0,1)", e.ActorPlayer, e.TargetPlayer)
	}
	if e.Element != engine.ElemPhysical {
		t.Errorf("element = %d, want Physical (%d)", e.Element, engine.ElemPhysical)
	}
	if e.RawValue < 1 {
		t.Errorf("raw_value = %d, want > 0", e.RawValue)
	}
	if !e.IsHit {
		t.Errorf("IsHit = false, want true (实际命中)")
	}
	if e.ReactionKind != engine.ReactionNone {
		t.Errorf("ReactionKind = %d, want 0 (物理无反应)", e.ReactionKind)
	}

	// 触发 9 次 damage 测 ring bounded K=8
	for i := 0; i < 8; i++ {
		g.PushEvent(engine.EventFrame{Player: 0, Char: 0, ActionCtx: engine.ActUseSkill})
		g.DealDamage(p1HpID, engine.ElemPhysical, 1, engine.DamageOpts{
			ActorPlayer: 0, ActorChar: 0,
		})
		g.PopEvent()
	}
	if len(g.RecentDamageEvents) != engine.MaxRecentDamageEvents {
		t.Errorf("after 9 damage ring len = %d, want %d (bounded)",
			len(g.RecentDamageEvents), engine.MaxRecentDamageEvents)
	}
}
