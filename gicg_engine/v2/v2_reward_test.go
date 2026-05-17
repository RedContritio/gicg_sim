package enginev2

import "testing"

// A13 reward attribution at commit
func TestA13RewardAttributionAtCommit(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("hp_p1", 10, 0, 10, Owner{Player: 1, Char: 0})
	hp.Tag = TagHP
	e := NewEngine(g)
	rap := &RewardAccumPair{*NewRewardAccum(), *NewRewardAccum()}

	ctx := &Ctx{Game: g, SubAction: SubActionDealDamage, TriggerSource: TriggerPlayerAction,
		Actor: Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 3}
	ctx.Propose(Proposal{
		Kind: PropValueDelta, Scalar: hp, Delta: -3,
		Owner: Owner{Player: 0, Char: 0},
	})
	count, _ := e.FireSubAction(ctx)
	if count == 0 {
		t.Fatalf("expected commit")
	}

	rap.AccumulateAfterCommit(ctx)

	if rap[0].DamageDealt != 3 {
		t.Errorf("expected DamageDealt[p0]=3, got %d", rap[0].DamageDealt)
	}
	if rap[1].DamageReceived != 3 {
		t.Errorf("expected DamageReceived[p1]=3, got %d", rap[1].DamageReceived)
	}
}

// A13 rollback 不累加 reward (transactional 一致性)
func TestA13RollbackNoReward(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("hp_p1", 10, 0, 10, Owner{Player: 1, Char: 0})
	hp.Tag = TagHP
	e := NewEngine(g)
	rap := &RewardAccumPair{*NewRewardAccum(), *NewRewardAccum()}

	e.RegisterHook(&HookSpec{
		Name: "boost/x", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		Fn: func(ctx *Ctx) {
			ctx.Propose(Proposal{
				Kind: PropValueDelta, Scalar: hp, Delta: -1,
				Owner: Owner{Player: 0, Char: 0},
			})
		},
	})
	e.RegisterHook(&HookSpec{
		Name: "immune/x", SubAction: subActionPtr(SubActionDealDamage), Phase: PhaseResolve,
		After: []string{"boost/x"},
		Fn: func(ctx *Ctx) {
			for _, p := range ctx.Proposals {
				if p.Kind == PropValueDelta && p.Scalar == hp {
					p.Rejected = true
				}
			}
		},
	})

	ctx := &Ctx{Game: g, SubAction: SubActionDealDamage, TriggerSource: TriggerPlayerAction,
		Actor: Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 5}
	ctx.Propose(Proposal{
		Kind: PropValueDelta, Scalar: hp, Delta: -5,
		Owner: Owner{Player: 0, Char: 0},
	})
	e.FireSubAction(ctx)
	rap.AccumulateAfterCommit(ctx)

	if rap[0].DamageDealt != 0 {
		t.Errorf("expected DamageDealt[p0]=0 (all rejected), got %d", rap[0].DamageDealt)
	}
	if hp.Value != 10 {
		t.Errorf("expected hp=10 (immune), got %d", hp.Value)
	}
}
