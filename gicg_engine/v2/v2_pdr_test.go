package enginev2

import "testing"

// A30 PDR-sync-with-hold (#10 勘探钻机 fundamental flaw 解)。
// 全 typed: DecisionSpec(SelectFromCollection) → DecisionResult(SelectedIndices)。
func TestPDRSyncWithHold_KantanDrillScenario(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("hp_p1", 10, 0, 10, Owner{Player: 1, Char: 0})
	hand := g.DeclareCollection("hand_p1", 5, Owner{Player: 1, Char: -1}, "instance")
	hand.Append(&CardRef{Ref: 1, Kind: CardKindEvent})
	hand.Append(&CardRef{Ref: 2, Kind: CardKindEvent})
	hand.Append(&CardRef{Ref: 3, Kind: CardKindEvent})
	solidarity := g.DeclareScalar("solidarity", 0, 0, 99, Owner{Player: 1, Char: 0})

	e := NewEngine(g)

	// 勘探钻机 propose hook: 受伤时若手牌非空, 启动 PDR 询问"弃哪张?"
	e.RegisterHook(&HookSpec{
		Name: "drill/discard_block_request", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		Fn: func(ctx *Ctx) {
			if ctx.Target.Player != 1 || hand.Len() == 0 {
				return
			}
			ctx.RequestDecisionSync(&DecisionSpec{
				Kind: DecisionSelectFromCollection, SourceCollection: hand, SelectCount: 1,
			})
		},
	})

	// resolve hook: 读 ctx.DecisionResult, propose discard + reduce 1 dmg + +1 团结
	e.RegisterHook(&HookSpec{
		Name: "drill/discard_block_apply", SubAction: subActionPtr(SubActionDealDamage), Phase: PhaseResolve,
		After: []string{"drill/discard_block_request"},
		Fn: func(ctx *Ctx) {
			if ctx.DecisionResult == nil || ctx.DecisionResult.Kind != DecisionSelectFromCollection {
				return
			}
			indices := ctx.DecisionResult.SelectedIndices
			if len(indices) == 0 {
				return
			}
			pickedIdx := indices[0]
			ctx.Propose(Proposal{Kind: PropCollectionRemoveAt, Collection: hand, Position: pickedIdx})
			for _, p := range ctx.Proposals {
				if p.Kind == PropValueDelta && p.Scalar == hp && p.Delta < 0 {
					p.Delta++
				}
			}
			ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: solidarity, Delta: 1})
		},
	})

	ctx := &Ctx{
		Game: g, SubAction: SubActionDealDamage, TriggerSource: TriggerPlayerAction,
		Actor: Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 3,
	}
	ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -3})

	count, _, held := e.FireSubActionWithHeldSupport(ctx)
	if held == nil {
		t.Fatalf("expected held ctx (PDR pending), got nil")
	}
	if count != 0 {
		t.Fatalf("expected 0 commit before PDR resolved, got %d", count)
	}
	if held.DecisionSpec.Kind != DecisionSelectFromCollection {
		t.Errorf("expected DecisionSpec.Kind=SelectFromCollection, got %v", held.DecisionSpec.Kind)
	}

	// RL agent 选 idx=1 (弃 card_b)
	held.DecisionResult = &DecisionResult{
		Kind: DecisionSelectFromCollection, SelectedIndices: []int{1},
	}
	count, _, held = e.ResumeHeldCtx(held)

	if held != nil {
		t.Fatalf("expected resume to complete (no held), got held")
	}
	if count == 0 {
		t.Fatalf("expected commit after resume")
	}
	if hp.Value != 8 {
		t.Errorf("expected hp=8 (10 - (3-1)), got %d", hp.Value)
	}
	if hand.Len() != 2 {
		t.Errorf("expected hand=2 cards, got %d", hand.Len())
	}
	if solidarity.Value != 1 {
		t.Errorf("expected solidarity=1, got %d", solidarity.Value)
	}
}
