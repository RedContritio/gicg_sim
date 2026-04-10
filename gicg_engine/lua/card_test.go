package lua

import (
	"gicg_mono/gicg_engine"
	"testing"
)

func setupCardTest(t *testing.T) (*engine.Game, *State) {
	t.Helper()

	g := engine.NewGame(engine.GameConfig{
		Players: [2]engine.PlayerConfig{
			{
				Chars: []engine.CharConfig{{}},
				Deck:  []engine.CardInst{{Ref: 1}, {Ref: 2}},
			},
			{
				Chars: []engine.CharConfig{{}},
			},
		},
	})
	g.Players[0].ActiveChar = 0
	g.Players[1].ActiveChar = 0

	s := NewState()
	InitCounterMetatable(s)
	RegisterPrelude(s, g)

	if err := s.DoStringSandboxed(`
		declare_char("A", { hp = 15, max_energy = 3, element = Element.Fire })
		bind_char("A", 0, 0)
		local a = get_char("A")
		declare_skill(a, "攻击", 3)

		declare_char("B", { hp = 15, max_energy = 3, element = Element.Ice })
		bind_char("B", 1, 0)
		local b = get_char("B")
		declare_skill(b, "待机", 3)
	`); err != nil {
		t.Fatalf("chars: %v", err)
	}

	if err := s.LoadFilesWithDeps([]string{
		"../../data/system/round.lua",
		"../../data/system/food.lua",
		"../../data/cards/L1/碌碌无为.lua",
	}); err != nil {
		t.Fatalf("system: %v", err)
	}

	g.NewRound()
	return g, s
}

func TestCard_碌碌无为(t *testing.T) {
	g, s := setupCardTest(t)
	defer s.Close()
	defer Cleanup(s)

	g.Players[0].Hand = []engine.CardInst{{Ref: 1}}

	s.DoString(`declare_card("碌碌无为", 1)`)
	s.DoString(`_card_ref = get_card("碌碌无为")`)
	cardRef, _ := s.GetGlobalInt("_card_ref")
	g.Players[0].Hand[0].Ref = cardRef

	actions := g.GetLegalActions()
	var cardIdx int = -1
	for i, a := range actions {
		if a.Kind == engine.ActionCard {
			cardIdx = i
			break
		}
	}
	if cardIdx < 0 {
		t.Fatal("card should be in legal actions")
	}

	result := g.Step(cardIdx)
	if result == engine.StepNeedTarget {
		t.Fatal("碌碌无为 should not need target")
	}

	if len(g.Players[0].Hand) != 0 {
		t.Fatal("card should be consumed")
	}
}

func TestCard_占星_Target(t *testing.T) {
	g, s := setupCardTest(t)
	defer s.Close()
	defer Cleanup(s)

	if err := s.DoFileSandboxed("../../data/cards/L2/占星.lua"); err != nil {
		t.Fatalf("load 占星: %v", err)
	}

	s.DoString(`_card_ref = get_card("占星")`)
	cardRef, _ := s.GetGlobalInt("_card_ref")
	g.Players[0].Hand = []engine.CardInst{{Ref: cardRef}}

	actions := g.GetLegalActions()
	var cardIdx int = -1
	for i, a := range actions {
		if a.Kind == engine.ActionCard {
			cardIdx = i
			break
		}
	}
	if cardIdx < 0 {
		t.Fatal("占星 should be in legal actions")
	}

	result := g.Step(cardIdx)
	if result != engine.StepNeedTarget {
		t.Fatalf("占星 should need target, got %d", result)
	}

	targets := g.GetLegalActions()
	if len(targets) == 0 {
		t.Fatal("should have target options")
	}

	g.StepTarget(0)

	energy := luaInt(t, s, `get_char("A"):energy():get()`)
	if energy != 2 {
		t.Fatalf("energy=%d, want 2", energy)
	}
}

func TestCard_诅咒_EnemyTarget(t *testing.T) {
	g, s := setupCardTest(t)
	defer s.Close()
	defer Cleanup(s)

	s.DoString(`get_char("B"):energy():set(3)`)

	if err := s.DoFileSandboxed("../../data/cards/L2/诅咒.lua"); err != nil {
		t.Fatalf("load 诅咒: %v", err)
	}

	s.DoString(`_card_ref = get_card("诅咒")`)
	cardRef, _ := s.GetGlobalInt("_card_ref")
	g.Players[0].Hand = []engine.CardInst{{Ref: cardRef}}

	actions := g.GetLegalActions()
	var cardIdx int = -1
	for i, a := range actions {
		if a.Kind == engine.ActionCard {
			cardIdx = i
			break
		}
	}
	if cardIdx < 0 {
		t.Fatal("诅咒 should be in legal actions")
	}

	result := g.Step(cardIdx)
	if result != engine.StepNeedTarget {
		t.Fatalf("诅咒 should need target, got %d", result)
	}

	g.StepTarget(0)

	energy := luaInt(t, s, `get_char("B"):energy():get()`)
	if energy != 2 {
		t.Fatalf("energy=%d, want 2 (3-1)", energy)
	}
}
