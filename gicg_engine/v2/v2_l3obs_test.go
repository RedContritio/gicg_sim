package enginev2

import "testing"

// L3 obs: typed transition log + ring buffer (bounded MaxLastTransitions=16)。
// 验证 RL 可从 obs 唯一推理 last K 步因果 (而不只学行为后效)。
func TestL3ObsLastTransitions(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("hp_p1", 100, 0, 100, Owner{Player: 1, Char: 0})
	hp.Tag = TagHP
	e := NewEngine(g)

	// 跑 3 个 SubActionDealDamage
	for i := 0; i < 3; i++ {
		ctx := &Ctx{Game: g, SubAction: SubActionDealDamage, Element: ElementFire,
			TriggerSource: TriggerPlayerAction,
			Actor:         Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1}
		ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
		e.FireSubAction(ctx)
	}

	if len(g.LastTransitions) != 3 {
		t.Fatalf("expected 3 transitions, got %d", len(g.LastTransitions))
	}
	for i, te := range g.LastTransitions {
		if te.SubAction != SubActionDealDamage {
			t.Errorf("transition %d: SubAction wrong (%v)", i, te.SubAction)
		}
		if te.Element != ElementFire {
			t.Errorf("transition %d: Element wrong (%v)", i, te.Element)
		}
		if te.TriggerSource != TriggerPlayerAction {
			t.Errorf("transition %d: TriggerSource wrong (%v)", i, te.TriggerSource)
		}
		if te.Cancelled {
			t.Errorf("transition %d: should not be cancelled", i)
		}
		if te.Actor.Player != 0 || te.Target.Player != 1 {
			t.Errorf("transition %d: actor/target wrong", i)
		}
	}

	// 跑 20 个 SubActionHeal (超 MaxLastTransitions=16) — 验证 ring buffer drop oldest
	for i := 0; i < 20; i++ {
		ctx := &Ctx{Game: g, SubAction: SubActionHeal,
			TriggerSource: TriggerEngineInternal,
			Actor:         SystemOwner(), Target: Owner{Player: 1, Char: 0}, Value: 0}
		e.FireSubAction(ctx)
	}
	if len(g.LastTransitions) != MaxLastTransitions {
		t.Errorf("expected %d transitions (bounded ring), got %d", MaxLastTransitions, len(g.LastTransitions))
	}
	for i, te := range g.LastTransitions {
		if te.SubAction != SubActionHeal {
			t.Errorf("ring buffer drop oldest 失败: idx=%d kind=%v", i, te.SubAction)
		}
	}
}
