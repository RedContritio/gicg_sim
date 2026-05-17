package enginev2

import "testing"

// e2e 反应链综合 (A2+A4+A7'+A13+A21)。
// 场景: p1 hp=10, 已附水 (water_aura=1). p0 火元素技能攻击 p1 base 2 dmg.
// reaction hook (火+水=vaporize): +2 dmg + 清水附着.
// 万叶天赋 (after reaction/*): vaporize 反应额外 +1 dmg.
// 最终: hp = 10 - 2 - 2 - 1 = 5; reward DamageDealt[p0]=5; water_aura=0.
// provenance 链应含 reaction/vaporize + kazuha/swirl_boost.
func TestE2EReactionChain(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("hp_p1", 10, 0, 10, Owner{Player: 1, Char: 0})
	hp.Tag = TagHP
	waterAura := g.DeclareScalar("water_aura_p1c0", 1, 0, 1, Owner{Player: 1, Char: 0})

	e := NewEngine(g)
	rap := &RewardAccumPair{*NewRewardAccum(), *NewRewardAccum()}

	// declared marker (typed, owner-bound)
	vaporizeMarker := &MarkerRef{Name: "vaporize", Owner: SystemOwner()}

	e.RegisterHook(&HookSpec{
		Name: "reaction/vaporize", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		Fn: func(ctx *Ctx) {
			if ctx.Element != ElementFire || waterAura.Value <= 0 {
				return
			}
			ctx.Propose(Proposal{
				Kind: PropValueDelta, Scalar: hp, Delta: -2,
				Owner: Owner{Player: 0, Char: 0},
			})
			ctx.Propose(Proposal{
				Kind: PropValueDelta, Scalar: waterAura, Delta: -1,
				Owner: Owner{Player: 0, Char: 0},
			})
			ctx.Propose(Proposal{Kind: PropMarker, Marker: vaporizeMarker})
		},
	})

	e.RegisterHook(&HookSpec{
		Name: "kazuha/swirl_boost", SubAction: subActionPtr(SubActionDealDamage), Phase: PhaseResolve,
		After: []string{"reaction/*"},
		Fn: func(ctx *Ctx) {
			if !ctx.HasMarker(vaporizeMarker) {
				return
			}
			ctx.Propose(Proposal{
				Kind: PropValueDelta, Scalar: hp, Delta: -1,
				Owner: Owner{Player: 0, Char: 0},
			})
		},
	})

	ctx := &Ctx{Game: g, SubAction: SubActionDealDamage, Element: ElementFire,
		TriggerSource: TriggerPlayerAction,
		Actor:         Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 2}
	ctx.Propose(Proposal{
		Kind: PropValueDelta, Scalar: hp, Delta: -2,
		Owner: Owner{Player: 0, Char: 0},
	})

	count, _ := e.FireSubAction(ctx)
	rap.AccumulateAfterCommit(ctx)

	if hp.Value != 5 {
		t.Errorf("expected hp=5 (10-2-2-1), got %d", hp.Value)
	}
	if waterAura.Value != 0 {
		t.Errorf("expected water_aura=0, got %d", waterAura.Value)
	}
	if rap[0].DamageDealt != 5 {
		t.Errorf("expected DamageDealt[p0]=5, got %d", rap[0].DamageDealt)
	}
	if rap[1].DamageReceived != 5 {
		t.Errorf("expected DamageReceived[p1]=5, got %d", rap[1].DamageReceived)
	}
	if count == 0 {
		t.Errorf("expected non-zero commit count")
	}

	hasReactionEntry := false
	hasKazuhaEntry := false
	for _, p := range ctx.Provenance {
		if p.HookName == "reaction/vaporize" {
			hasReactionEntry = true
		}
		if p.HookName == "kazuha/swirl_boost" {
			hasKazuhaEntry = true
		}
	}
	if !hasReactionEntry {
		t.Errorf("provenance missing reaction/vaporize")
	}
	if !hasKazuhaEntry {
		t.Errorf("provenance missing kazuha/swirl_boost")
	}
}
