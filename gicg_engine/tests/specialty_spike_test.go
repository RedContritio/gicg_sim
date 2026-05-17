package tests

// TestSpecialtySpike — ADR-0012 specialty 槽位机制验证。
//
// 注入驰轮车·疾驰 到 P0 手牌(用 SetPlayerHand 跳过"产手牌选择"机制
// — 那是 future ADR 范围),然后:
//   1. P0 打第 1 张 → 玛薇卡 SpecialtyCardRef 被设置 + add_dice 加 2 omni
//   2. 注入第 2 张 → on_action_check 应判 Playable=false(槽满)
//   3. 验证第 2 张不出现在 GetLegalActions 候选里

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestSpecialtySpike_EquipAndCap(t *testing.T) {
	env := NewGameWithDeck(t, []string{"玛薇卡"}, []string{"玛薇卡"})
	g := env.G

	driveCard, ok := env.RT.Cards.ByName["驰轮车_疾驰"]
	if !ok {
		t.Fatal("驰轮车_疾驰 not in card registry")
	}
	t.Logf("driveCard ref=%d slot=%d requires_char=%s", driveCard.Ref, driveCard.Slot, driveCard.RequiresChar)
	allRefs := []int{}
	for r := range env.RT.Cards.ByRef {
		allRefs = append(allRefs, r)
	}
	t.Logf("all card refs in registry: %v", allRefs)

	// Inject 1 驰轮车·疾驰 into P0's hand (replace existing hand entirely
	// to keep test focused — game_shuffle.SetPlayerHand replaces the full
	// list, so we add it as the only card).
	g.SetPlayerHand(0, []int{driveCard.Ref})

	// Snapshot dice for omni delta verification.
	omniBefore := env.RT.GetDiceCount(0, engine.DiceColorOmni)

	// Find ActionCard for 驰轮车_疾驰 in P0's legal actions.
	actions := g.GetLegalActions()
	pickIdx := -1
	for i, a := range actions {
		if a.PlayerIdx == 0 && a.Kind == engine.ActionCard && a.Index == 0 {
			// hand_idx=0 should be 驰轮车_疾驰 (only card in hand).
			if g.Players[0].Hand[0].Ref == driveCard.Ref {
				pickIdx = i
				break
			}
		}
	}
	if pickIdx < 0 {
		t.Fatalf("驰轮车_疾驰 not in P0 legal card actions; actions=%v hand=%v", actions, g.Players[0].Hand)
	}
	g.Step(pickIdx)

	// After play: 玛薇卡 SpecialtyCardRef should equal driveCard.Ref.
	maviChar := env.RT.Chars.BySlot[0][0]
	if maviChar == nil {
		t.Fatal("P0 char 0 not bound")
	}
	// driveCard.Ref may be 0 (first declared card in registry) so we
	// can't use 0 as "empty" sentinel — that's why CharEntry uses -1.
	if maviChar.SpecialtyCardRef != driveCard.Ref {
		t.Errorf("after 驰轮车 play: P0 SpecialtyCardRef = %d, want %d", maviChar.SpecialtyCardRef, driveCard.Ref)
	}

	// add_dice should have generated 2 omni dice for P0.
	omniAfter := env.RT.GetDiceCount(0, engine.DiceColorOmni)
	if omniAfter != omniBefore+2 {
		t.Errorf("add_dice omni: %d → %d, want +2", omniBefore, omniAfter)
	}

	// Inject second 驰轮车 into P0 hand. Specialty slot is now full —
	// on_action_check should reject this card.
	g.SetPlayerHand(0, []int{driveCard.Ref})

	actions = g.GetLegalActions()
	for _, a := range actions {
		if a.PlayerIdx == 0 && a.Kind == engine.ActionCard {
			handIdx := a.Index
			if handIdx < len(g.Players[0].Hand) && g.Players[0].Hand[handIdx].Ref == driveCard.Ref {
				t.Errorf("specialty slot is full (SpecialtyCardRef=%d) but 驰轮车 still in legal card actions", maviChar.SpecialtyCardRef)
			}
		}
	}
}
