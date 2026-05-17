package enginev2

import "testing"

// A28 obs encoder: 验证 mask + L3 transitions + game meta + PDR exposure。
//
// 场景:
// - p0 自己 hp/hand visible (own)
// - p1 (敌方) hp visible (公开 hp), hand hidden (size only)
// - SystemOwner dice pool visible 给两方
// - LastTransitions 含 1 entry (主 dmg)
// - PDR hold 时 DecisionSpec 暴露给 obs.PendingDecision
func TestA28EncodeObsBasicMask(t *testing.T) {
	g := NewGame()
	g.Round = 3
	g.Turn = 0
	g.Phase = PhaseAction

	p0Hp := g.DeclareScalar("p0_hp", 8, 0, 10, Owner{Player: 0, Char: 0})
	p0Hp.Tag = TagHP
	p1Hp := g.DeclareScalar("p1_hp", 6, 0, 10, Owner{Player: 1, Char: 0})
	p1Hp.Tag = TagHP

	p0Hand := g.DeclareCollection("p0_hand", 5, Owner{Player: 0, Char: -1}, "instance")
	p0Hand.HiddenFrom = HiddenFrom{1}
	p0Hand.Append(&CardRef{Ref: 100, CostTotal: 2, Kind: CardKindEvent})
	p0Hand.Append(&CardRef{Ref: 101, CostTotal: 1, Kind: CardKindEquipment})

	p1Hand := g.DeclareCollection("p1_hand", 5, Owner{Player: 1, Char: -1}, "instance")
	p1Hand.HiddenFrom = HiddenFrom{0}
	p1Hand.Append(&CardRef{Ref: 200, CostTotal: 3, Kind: CardKindSupport})

	// dice 在共享区, 但实际 GICG dice 是按 player owned;这里简化作 shared 测 SystemOwner
	_ = g.DeclareCollection("dice_pool", 16, SystemOwner(), "shared")

	// 模拟一次主 dmg transition
	g.AppendTransition(TransitionEntry{
		SubAction: SubActionDealDamage, Element: ElementFire,
		TriggerSource: TriggerPlayerAction,
		Actor:         Owner{Player: 0, Char: 0},
		Target:        Owner{Player: 1, Char: 0},
		Value:         3,
	})

	// p0 视角 obs
	obs0 := EncodeObs(g, 0, nil)
	if obs0.Round != 3 || obs0.Turn != 0 || obs0.Phase != PhaseAction {
		t.Errorf("game meta wrong: round=%d turn=%d phase=%d", obs0.Round, obs0.Turn, obs0.Phase)
	}
	if obs0.ViewerPlayer != 0 {
		t.Errorf("ViewerPlayer wrong")
	}
	// p0 自己: hp visible + hand visible
	foundOwnHp := false
	for _, s := range obs0.ScalarsSelf {
		if s.Name == "p0_hp" {
			foundOwnHp = true
			if !s.Visible || s.Value != 8 {
				t.Errorf("p0 own hp 应 visible=true value=8, got visible=%v value=%d", s.Visible, s.Value)
			}
		}
	}
	if !foundOwnHp {
		t.Errorf("p0 obs.ScalarsSelf 应含 p0_hp")
	}

	// p0 看 p1 hp: visible (公开 hp)
	foundEnemyHp := false
	for _, s := range obs0.ScalarsEnemy {
		if s.Name == "p1_hp" {
			foundEnemyHp = true
			if !s.Visible || s.Value != 6 {
				t.Errorf("p1 hp 对 p0 应 visible=true value=6, got visible=%v value=%d", s.Visible, s.Value)
			}
		}
	}
	if !foundEnemyHp {
		t.Errorf("p0 obs.ScalarsEnemy 应含 p1_hp")
	}

	// p0 看 p1 hand: hidden (size 公开 = 1, items=nil)
	foundEnemyHand := false
	for _, c := range obs0.CollectionsEnemy {
		if c.Name == "p1_hand" {
			foundEnemyHand = true
			if c.Visible {
				t.Errorf("p1_hand 对 p0 应 hidden, got Visible=true")
			}
			if c.Size != 1 {
				t.Errorf("p1_hand size 应公开 = 1, got %d", c.Size)
			}
			if c.Items != nil {
				t.Errorf("p1_hand hidden 时 Items 应 nil, got %v", c.Items)
			}
		}
	}
	if !foundEnemyHand {
		t.Errorf("p0 obs.CollectionsEnemy 应含 p1_hand")
	}

	// p0 看自己 hand: visible + Items 含 typed CardObs
	foundOwnHand := false
	for _, c := range obs0.CollectionsSelf {
		if c.Name == "p0_hand" {
			foundOwnHand = true
			if !c.Visible {
				t.Errorf("p0_hand 应 visible 给自己")
			}
			if len(c.Items) != 2 {
				t.Errorf("p0_hand items=2, got %d", len(c.Items))
			}
			// 验证 typed Item
			if c.Items[0].Kind != ItemKindCard || c.Items[0].Card == nil {
				t.Errorf("item[0] 应 typed CardObs")
			}
			if c.Items[0].Card.Ref != 100 || c.Items[0].Card.CostTotal != 2 {
				t.Errorf("item[0] 内容错: %v", c.Items[0].Card)
			}
		}
	}
	if !foundOwnHand {
		t.Errorf("p0 obs.CollectionsSelf 应含 p0_hand")
	}

	// SystemOwner dice pool 进 ScalarsShared / CollectionsShared
	foundSharedDice := false
	for _, c := range obs0.CollectionsShared {
		if c.Name == "dice_pool" {
			foundSharedDice = true
		}
	}
	if !foundSharedDice {
		t.Errorf("dice_pool (SystemOwner) 应进 obs.CollectionsShared")
	}

	// L3 transitions (全 public)
	if len(obs0.LastTransitions) != 1 {
		t.Fatalf("expected 1 transition in obs, got %d", len(obs0.LastTransitions))
	}
	te := obs0.LastTransitions[0]
	if te.Element != ElementFire || te.TriggerSource != TriggerPlayerAction {
		t.Errorf("transition typed fields 错")
	}
	if te.Value != 3 || te.Actor.Player != 0 {
		t.Errorf("transition value/actor 错")
	}

	// p1 视角对照: p0_hand 应 hidden, p1_hand 应 visible
	obs1 := EncodeObs(g, 1, nil)
	for _, c := range obs1.CollectionsEnemy {
		if c.Name == "p0_hand" && c.Visible {
			t.Errorf("p0_hand 对 p1 应 hidden")
		}
	}
	for _, c := range obs1.CollectionsSelf {
		if c.Name == "p1_hand" && !c.Visible {
			t.Errorf("p1_hand 对 p1 应 visible")
		}
	}
}

// PDR hold 时 obs.PendingDecision 暴露 typed DecisionSpec
func TestA28EncodeObsWithPDRHold(t *testing.T) {
	g := NewGame()
	hand := g.DeclareCollection("p1_hand", 5, Owner{Player: 1, Char: -1}, "instance")
	hand.Append(&CardRef{Ref: 1})
	hand.Append(&CardRef{Ref: 2})

	spec := &DecisionSpec{
		Kind:             DecisionSelectFromCollection,
		SourceCollection: hand,
		SelectCount:      1,
	}
	held := &HeldCtx{DecisionSpec: spec, ResumePhase: PhasePropose}

	obs := EncodeObs(g, 1, held)
	if obs.PendingDecision == nil {
		t.Fatalf("expected PendingDecision in obs")
	}
	if obs.PendingDecision.Kind != DecisionSelectFromCollection {
		t.Errorf("PendingDecision Kind 错: %v", obs.PendingDecision.Kind)
	}
	if obs.PendingDecision.SourceCollection != hand {
		t.Errorf("PendingDecision SourceCollection 应 = hand")
	}
}

// Destroyed 容器仍出现在 obs (tombstone), Destroyed=true
func TestA28EncodeObsDestroyedTombstone(t *testing.T) {
	g := NewGame()
	durability := g.DeclareScalar("equip_dur", 0, 0, 2, Owner{Player: 0, Char: 0})
	durability.Destroyed = true

	obs := EncodeObs(g, 0, nil)
	found := false
	for _, s := range obs.ScalarsSelf {
		if s.Name == "equip_dur" {
			found = true
			if !s.Destroyed {
				t.Errorf("destroyed scalar 应 Destroyed=true 进 obs")
			}
		}
	}
	if !found {
		t.Errorf("destroyed scalar 应仍在 obs (RL 知道这件装备坏了)")
	}
}
