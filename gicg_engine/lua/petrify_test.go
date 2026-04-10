package lua

import (
	"gicg_mono/gicg_engine"
	"testing"
)

// setupPetrify: 天星(P0) vs 目标(P1), 天星 has 枪 and 天星(ultimate)
func setupPetrify(t *testing.T) (*engine.Game, *State) {
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

	for _, f := range []string{
		"../../data/system/round.lua",
		"../../data/system/draw.lua",
	} {
		if err := s.DoFile(f); err != nil {
			t.Fatalf("load %s: %v", f, err)
		}
	}

	// P0: 天星
	if err := s.DoFile("../../data/characters/天星/天星.lua"); err != nil {
		t.Fatal(err)
	}
	if err := s.DoString(`bind_char("天星", 0, 0)`); err != nil {
		t.Fatal(err)
	}
	if err := s.DoFile("../../data/characters/天星/天星_枪.lua"); err != nil {
		t.Fatal(err)
	}
	if err := s.DoFile("../../data/characters/天星/天星_天星.lua"); err != nil {
		t.Fatal(err)
	}

	// P1: 目标 (with a skill so P1 can act)
	if err := s.DoString(`
		declare_char("目标", { hp = 15, max_energy = 0, element = Element.None })
		bind_char("目标", 1, 0)
		local 目标 = get_char("目标")
		local sk = declare_skill(目标, "待机", 3)
		on_skill_use(function(ctx)
			if ctx.skill_index ~= sk then return end
		end)
	`); err != nil {
		t.Fatal(err)
	}

	// Give 天星 3 energy for ultimate
	if err := s.DoString(`get_char("天星"):energy():set(3)`); err != nil {
		t.Fatal(err)
	}

	g.NewRound()

	return g, s
}

func stepAction(t *testing.T, g *engine.Game, kind engine.ActionKind, index int) {
	t.Helper()
	for i, a := range g.GetLegalActions() {
		if a.Kind == kind && a.Index == index {
			g.Step(i)
			return
		}
	}
	t.Fatalf("action kind=%d index=%d not found in legal actions", kind, index)
}

func stepFirstAction(t *testing.T, g *engine.Game, kind engine.ActionKind) {
	t.Helper()
	for i, a := range g.GetLegalActions() {
		if a.Kind == kind {
			g.Step(i)
			return
		}
	}
	t.Fatalf("action kind=%d not found in legal actions", kind)
}

func stepEndTurn(t *testing.T, g *engine.Game) {
	t.Helper()
	for i, a := range g.GetLegalActions() {
		if a.Kind == engine.ActionEndTurn {
			g.Step(i)
			return
		}
	}
	t.Fatal("end turn not found in legal actions")
}

func countActions(g *engine.Game, kind engine.ActionKind) int {
	n := 0
	for _, a := range g.GetLegalActions() {
		if a.Kind == kind {
			n++
		}
	}
	return n
}

func TestPetrify_Applied(t *testing.T) {
	g, s := setupPetrify(t)
	defer s.Close()
	defer Cleanup(s)

	// P0: use ultimate (skill index 1 = 天星)
	stepAction(t, g, engine.ActionSkill, 1)

	// P1's active char should have 石化
	v := luaInt(t, s, `get_counter("石化", Scope.PerChar):get_at(1, 0)`)
	if v != 1 {
		t.Fatalf("石化 should be 1, got %d", v)
	}

	// P1 HP should be 15 - 2 = 13
	hp := luaInt(t, s, `get_char("目标"):hp():get()`)
	if hp != 13 {
		t.Fatalf("目标 HP should be 13, got %d", hp)
	}
}

func TestPetrify_BlocksSecondAction(t *testing.T) {
	g, s := setupPetrify(t)
	defer s.Close()
	defer Cleanup(s)

	// P0: use ultimate (天星 skill, global ID 1)
	stepAction(t, g, engine.ActionSkill, 1)

	// Now it's P1's turn. P1 should be able to act (first action under petrify)
	skills := countActions(g, engine.ActionSkill)
	if skills == 0 {
		t.Fatal("P1 should have skill actions on first turn under petrify")
	}

	// P1: use skill (first action)
	stepFirstAction(t, g, engine.ActionSkill)

	// P0: end turn
	stepEndTurn(t, g)

	// P1's second turn: only EndTurn should be available (petrify blocks)
	skills = countActions(g, engine.ActionSkill)
	if skills != 0 {
		t.Fatalf("P1 should have 0 skill actions on second turn, got %d", skills)
	}

	// EndTurn should still be available
	endTurns := countActions(g, engine.ActionEndTurn)
	if endTurns == 0 {
		t.Fatal("EndTurn should be available under petrify")
	}
}

func TestPetrify_ConsumedAfterTrigger(t *testing.T) {
	g, s := setupPetrify(t)
	defer s.Close()
	defer Cleanup(s)

	// P0: use ultimate
	stepAction(t, g, engine.ActionSkill, 1)

	// P1: first action (skill)
	stepFirstAction(t, g, engine.ActionSkill)

	// P0: end turn
	stepEndTurn(t, g)

	// P1: forced to end turn (petrify blocks second action)
	// Both players ended → EndPhase auto-fires → NewRound auto-starts
	stepEndTurn(t, g)

	// 石化 should be 0 after being consumed in round_end
	v := luaInt(t, s, `get_counter("石化", Scope.PerChar):get_at(1, 0)`)
	if v != 0 {
		t.Fatalf("石化 should be consumed after round end, got %d", v)
	}
}

func TestPetrify_IsCharacterLevel(t *testing.T) {
	// Test that petrify is on a specific character, not the player
	// Setup: 2 chars on P1 side
	g := engine.NewGame(engine.GameConfig{
		Players: [2]engine.PlayerConfig{
			{Chars: []engine.CharConfig{{}}},
			{Chars: []engine.CharConfig{{}, {}}},
		},
	})
	g.Players[0].ActiveChar = 0
	g.Players[1].ActiveChar = 0

	s := NewState()
	defer s.Close()
	InitCounterMetatable(s)
	RegisterPrelude(s, g)
	defer Cleanup(s)

	for _, f := range []string{
		"../../data/system/round.lua",
	} {
		if err := s.DoFile(f); err != nil {
			t.Fatalf("load %s: %v", f, err)
		}
	}

	// P0: 天星
	if err := s.DoFile("../../data/characters/天星/天星.lua"); err != nil {
		t.Fatal(err)
	}
	if err := s.DoString(`bind_char("天星", 0, 0)`); err != nil {
		t.Fatal(err)
	}
	if err := s.DoFile("../../data/characters/天星/天星_枪.lua"); err != nil {
		t.Fatal(err)
	}
	if err := s.DoFile("../../data/characters/天星/天星_天星.lua"); err != nil {
		t.Fatal(err)
	}

	// P1: two characters
	if err := s.DoString(`
		declare_char("目标A", { hp = 15, max_energy = 0, element = Element.None })
		bind_char("目标A", 1, 0)
		local 目标A = get_char("目标A")
		local skA = declare_skill(目标A, "待机A", 3)
		on_skill_use(function(ctx)
			if ctx.skill_index ~= skA then return end
		end)

		declare_char("目标B", { hp = 15, max_energy = 0, element = Element.None })
		bind_char("目标B", 1, 1)
		local 目标B = get_char("目标B")
		local skB = declare_skill(目标B, "待机B", 3)
		on_skill_use(function(ctx)
			if ctx.skill_index ~= skB then return end
		end)
	`); err != nil {
		t.Fatal(err)
	}

	if err := s.DoString(`get_char("天星"):energy():set(3)`); err != nil {
		t.Fatal(err)
	}

	g.NewRound()

	// P0: ultimate → petrify on P1's active char (slot 0)
	stepAction(t, g, engine.ActionSkill, 1)

	// Char 0 should have petrify, char 1 should not
	v0 := luaInt(t, s, `get_counter("石化", Scope.PerChar):get_at(1, 0)`)
	v1 := luaInt(t, s, `get_counter("石化", Scope.PerChar):get_at(1, 1)`)
	if v0 != 1 {
		t.Fatalf("目标A (slot 0) should have 石化=1, got %d", v0)
	}
	if v1 != 0 {
		t.Fatalf("目标B (slot 1) should have 石化=0, got %d", v1)
	}
}
