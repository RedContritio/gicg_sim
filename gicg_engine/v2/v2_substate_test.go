package enginev2

import "testing"

// A26 multi-instance substate (千织 3-of-4 召唤物挑选)
func TestA26MultiInstanceSubstate(t *testing.T) {
	reg := NewSubstateRegistry()
	reg.DeclareSubstate(&SubstateTemplate{
		Name: "qianzhi_pick",
		StateSchema: []SubstateField{
			{Name: "candidates", Kind: FieldCollection, MaxItems: 4, ItemOwnership: "shared"},
			{Name: "picked_idx", Kind: FieldScalar, InitInt: -1, MinInt: -1, MaxInt: 3},
		},
		LegalActions: func(inst *SubstateInstance) []SubstateAction {
			actions := []SubstateAction{}
			c := inst.Collections["candidates"]
			for i := 0; i < c.Len(); i++ {
				actions = append(actions, SubstateAction{Kind: SubstateActionSelect, SelectedIdx: i})
			}
			return actions
		},
		OnAction: func(inst *SubstateInstance, action SubstateAction) {
			if action.Kind == SubstateActionSelect {
				inst.Scalars["picked_idx"].Value = action.SelectedIdx
			}
		},
	})

	// 实例 1: [a, b, c]
	inst1 := reg.EnterSubstate("qianzhi_pick", &SubstateInitData{
		Candidates: []Item{
			&SummonRef{Ref: 1, Element: ElementFire},
			&SummonRef{Ref: 2, Element: ElementIce},
			&SummonRef{Ref: 3, Element: ElementWater},
		},
	})
	if inst1.Collections["candidates"].Len() != 3 {
		t.Fatalf("inst1 candidates expected 3, got %d", inst1.Collections["candidates"].Len())
	}
	reg.Templates["qianzhi_pick"].OnAction(inst1, SubstateAction{Kind: SubstateActionSelect, SelectedIdx: 1})
	if inst1.Scalars["picked_idx"].Value != 1 {
		t.Errorf("inst1 picked_idx expected 1, got %d", inst1.Scalars["picked_idx"].Value)
	}
	reg.ExitSubstate(inst1, &SubstateExitData{
		PickedItems: []Item{&SummonRef{Ref: 2}},
	})

	// 实例 2: [x, y, z, w] — 验证 recycle pool dirty reset
	inst2 := reg.EnterSubstate("qianzhi_pick", &SubstateInitData{
		Candidates: []Item{
			&SummonRef{Ref: 11}, &SummonRef{Ref: 12},
			&SummonRef{Ref: 13}, &SummonRef{Ref: 14},
		},
	})
	if inst2.Collections["candidates"].Len() != 4 {
		t.Errorf("inst2 candidates expected 4, got %d", inst2.Collections["candidates"].Len())
	}
	if inst2.Scalars["picked_idx"].Value != -1 {
		t.Errorf("inst2 picked_idx expected -1 (recycle reset), got %d", inst2.Scalars["picked_idx"].Value)
	}
}

// A26 concurrent instances (不互相污染)
func TestA26ConcurrentInstances(t *testing.T) {
	reg := NewSubstateRegistry()
	reg.DeclareSubstate(&SubstateTemplate{
		Name: "rerolling",
		StateSchema: []SubstateField{
			{Name: "attempts_left", Kind: FieldScalar, InitInt: 2, MinInt: 0, MaxInt: 2},
		},
	})

	inst1 := reg.EnterSubstate("rerolling", nil)
	inst2 := reg.EnterSubstate("rerolling", nil)

	if inst1 == inst2 {
		t.Fatalf("两个 enter 应返回不同 instance, got same")
	}
	inst1.Scalars["attempts_left"].Value = 1
	if inst2.Scalars["attempts_left"].Value != 2 {
		t.Errorf("inst2 attempts 被 inst1 污染: %d", inst2.Scalars["attempts_left"].Value)
	}
}
