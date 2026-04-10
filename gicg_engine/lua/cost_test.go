package lua

import (
	"gicg_mono/gicg_engine"
	"testing"
)

func setupCostTest(t *testing.T) (*engine.Game, *State) {
	t.Helper()

	g := engine.NewGame(engine.GameConfig{
		Players: [2]engine.PlayerConfig{
			{Chars: []engine.CharConfig{{}}},
			{Chars: []engine.CharConfig{{}}},
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
		declare_skill(a, "普攻", 3)
		declare_skill(a, "大招", 3, 3)

		declare_char("B", { hp = 15, max_energy = 0, element = Element.Ice })
		bind_char("B", 1, 0)
		local b = get_char("B")
		declare_skill(b, "待机", 3)
	`); err != nil {
		t.Fatalf("chars: %v", err)
	}

	s.ResetOwner()
	if err := s.DoFileSandboxed("../../data/system/round.lua"); err != nil {
		t.Fatalf("round: %v", err)
	}

	g.NewRound()
	return g, s
}

func countSkillActions(g *engine.Game) int {
	n := 0
	for _, a := range g.GetLegalActions() {
		if a.Kind == engine.ActionSkill {
			n++
		}
	}
	return n
}

func TestCost_APInsufficient(t *testing.T) {
	g, s := setupCostTest(t)
	defer s.Close()
	defer Cleanup(s)

	if countSkillActions(g) < 1 {
		t.Fatal("普攻 should be legal with AP=8")
	}

	// Set AP=2, 普攻 costs 3 → should be illegal
	s.DoString(`declare_counter("ap", Scope.PerPlayer, 0, {max=12}):set(2)`)

	skills := countSkillActions(g)
	if skills != 0 {
		t.Fatalf("no skills should be legal with AP=2, got %d", skills)
	}
}

func TestCost_EnergyInsufficient(t *testing.T) {
	g, s := setupCostTest(t)
	defer s.Close()
	defer Cleanup(s)

	// 大招 needs 3 energy, A has 0 → should be illegal
	actions := g.GetLegalActions()
	for _, a := range actions {
		if a.Kind == engine.ActionSkill {
			// Check if this is 大招 by counting - 普攻 should be legal, 大招 should not
		}
	}
	// Should have exactly 1 skill (普攻), 大招 blocked by energy
	if countSkillActions(g) != 1 {
		t.Fatalf("should have 1 skill (大招 blocked), got %d", countSkillActions(g))
	}

	// Give 3 energy → 大招 should become legal
	s.DoString(`get_char("A"):energy():set(3)`)
	if countSkillActions(g) != 2 {
		t.Fatalf("should have 2 skills with energy=3, got %d", countSkillActions(g))
	}
}

func TestCost_CardAPInsufficient(t *testing.T) {
	g, s := setupCostTest(t)
	defer s.Close()
	defer Cleanup(s)

	s.DoString(`declare_card("测试卡", 5)`)
	s.DoString(`_cr = get_card("测试卡")`)
	cr, _ := s.GetGlobalInt("_cr")
	g.Players[0].Hand = []engine.CardInst{{Ref: cr}}

	// AP=8, card costs 5 → legal
	hasCard := false
	for _, a := range g.GetLegalActions() {
		if a.Kind == engine.ActionCard {
			hasCard = true
		}
	}
	if !hasCard {
		t.Fatal("card should be legal with AP=8")
	}

	// AP=4, card costs 5 → illegal
	s.DoString(`declare_counter("ap", Scope.PerPlayer, 0, {max=12}):set(4)`)
	hasCard = false
	for _, a := range g.GetLegalActions() {
		if a.Kind == engine.ActionCard {
			hasCard = true
		}
	}
	if hasCard {
		t.Fatal("card should be illegal with AP=4")
	}
}

func TestCost_SkillCostReduction(t *testing.T) {
	g, s := setupCostTest(t)
	defer s.Close()
	defer Cleanup(s)

	// 注册一个效果：每回合第二次技能 AP -1
	if err := s.DoStringSandboxed(`
		local skill_count = declare_counter("skill_use_count", Scope.PerPlayer, 0, { min = 0, max = 99 })

		on_round_start(function(ctx)
			skill_count:set(0)
		end)

		on_skill_use(function(ctx)
			skill_count:add(1)
		end)

		on_action_prepare(function(ctx)
			if ctx.action_kind ~= ActionKind.Skill then return end
			if skill_count:get() >= 1 then
				ctx.ap_cost = ctx.ap_cost - 1
			end
		end)
	`); err != nil {
		t.Fatalf("buff: %v", err)
	}

	// AP=5, 普攻 costs 3
	s.DoString(`declare_counter("ap", Scope.PerPlayer, 0, {max=12}):set(5)`)

	// 第一次普攻: cost 3, AP 5→2
	if countSkillActions(g) < 1 {
		t.Fatal("first skill should be legal")
	}
	useSkill(t, g, 0) // P0 uses 普攻, costs 3, AP=2

	// P1 行动（结束回合让 P0 再次行动）
	endTurn(t, g)

	// 第二次普攻: base cost 3 - 1 = 2, AP=2 → should be legal
	if countSkillActions(g) < 1 {
		t.Fatal("second skill should be legal (cost reduced to 2, AP=2)")
	}
}
