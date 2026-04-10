package lua

import (
	"gicg_mono/gicg_engine"
	"testing"
)

func setupEquipTest(t *testing.T) (*engine.Game, *State) {
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
		declare_char("剑士", { hp = 15, max_energy = 0, element = Element.Fire, weapon = Weapon.Sword })
		bind_char("剑士", 0, 0)
		local a = get_char("剑士")
		local sk = declare_skill(a, "斩", 3)
		on_skill_use(function(ctx)
			if ctx.skill_index ~= sk then return end
			deal_damage(Target.EnemyActive, Element.Physical, 2)
		end)

		declare_char("靶", { hp = 30, max_energy = 0, element = Element.None, weapon = Weapon.None })
		bind_char("靶", 1, 0)
		local b = get_char("靶")
		declare_skill(b, "待机", 3)
	`); err != nil {
		t.Fatalf("chars: %v", err)
	}

	s.ResetOwner()

	if err := s.LoadFilesWithDeps([]string{
		"../../data/system/round.lua",
		"../../data/system/equip.lua",
		"../../data/cards/L3/铁剑.lua",
	}); err != nil {
		t.Fatalf("system: %v", err)
	}

	g.NewRound()
	return g, s
}

func TestEquip_WeaponMismatch(t *testing.T) {
	g, s := setupEquipTest(t)
	defer s.Close()
	defer Cleanup(s)

	s.DoString(`_cr = get_card("铁剑")`)
	cr, _ := s.GetGlobalInt("_cr")
	g.Players[0].Hand = []engine.CardInst{{Ref: cr}}

	// 打出铁剑 → 需要目标
	var cardIdx int = -1
	for i, a := range g.GetLegalActions() {
		if a.Kind == engine.ActionCard {
			cardIdx = i
			break
		}
	}
	if cardIdx < 0 {
		t.Fatal("铁剑 should be playable")
	}

	result := g.Step(cardIdx)
	if result != engine.StepNeedTarget {
		t.Fatal("铁剑 should need target")
	}

	// 目标列表：只有剑士（Sword）可选，靶（None）不行
	targets := g.GetLegalActions()
	if len(targets) != 1 {
		t.Fatalf("should have 1 valid target (sword only), got %d", len(targets))
	}
}

func TestEquip_铁剑_CostReduction(t *testing.T) {
	g, s := setupEquipTest(t)
	defer s.Close()
	defer Cleanup(s)

	// 直接给剑士装备铁剑
	s.DoString(`
		local eq = get_counter("equipped", Scope.PerChar)
		eq:set_at(0, 0, get_card("铁剑"))
	`)

	// AP=8, 斩 costs 3 → 第一次斩（无减费）
	useSkill(t, g, 0) // P0 斩, AP=5
	endTurn(t, g)      // P1 结束

	// 第二次斩：铁剑效果，同技能 AP-1 = 2
	// AP=5, cost=2 → legal
	if countSkillActions(g) < 1 {
		t.Fatal("second 斩 should be legal (cost reduced)")
	}

	useSkill(t, g, 0) // P0 斩, AP=3

	hp := luaInt(t, s, `get_char("靶"):hp():get()`)
	// 两次斩各 2 伤 = 4
	if hp != 26 {
		t.Fatalf("HP=%d, want 26 (30-2-2)", hp)
	}
}
