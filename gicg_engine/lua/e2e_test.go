package lua

import (
	"gicg_mono/gicg_engine"
	"testing"
)

// setupE2E 创建一个完整的 1v1 对局（猫咪 vs 猫咪）
func setupE2E(t *testing.T) (*engine.Game, *State) {
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

	// 加载系统 DSL
	for _, f := range []string{
		"../../data/system/round.lua",
		"../../data/system/draw.lua",
	} {
		if err := s.DoFile(f); err != nil {
			t.Fatalf("load %s: %v", f, err)
		}
	}

	// P0: 声明猫咪 → bind → 加载技能（技能 hook 获得 owner = P0/0）
	if err := s.DoFile("../../data/characters/猫咪/猫咪.lua"); err != nil {
		t.Fatalf("load 猫咪.lua: %v", err)
	}
	if err := s.DoString(`bind_char("猫咪", 0, 0)`); err != nil {
		t.Fatalf("bind P0: %v", err)
	}
	if err := s.DoFile("../../data/characters/猫咪/猫咪_箭.lua"); err != nil {
		t.Fatalf("load P0 箭: %v", err)
	}

	// P1: 单独 declare（mirror match 需要独立 counter 实例）
	if err := s.DoString(`
		declare_char("猫咪P1", { hp = 15, max_energy = 3, element = Element.Ice })
		bind_char("猫咪P1", 1, 0)
	`); err != nil {
		t.Fatalf("declare P1: %v", err)
	}
	// P1 也注册普攻（owner = P1/0）
	if err := s.DoString(`
		local p1 = get_char("猫咪P1")
		local 箭 = declare_skill(p1, "箭", 3)
		on_skill_use(function(ctx)
			if ctx.skill_index ~= 箭 then return end
			deal_damage(Target.EnemyActive, Element.Physical, 2)
		end)
	`); err != nil {
		t.Fatalf("P1 skill: %v", err)
	}

	// 开始回合
	g.NewRound()

	return g, s
}

func TestE2E_BasicAttack(t *testing.T) {
	g, s := setupE2E(t)
	defer s.Close()
	defer Cleanup(s)

	// P0 使用普攻（skill 0）
	actions := g.GetLegalActions()
	var skillIdx int = -1
	for i, a := range actions {
		if a.Kind == engine.ActionSkill && a.Index == 0 {
			skillIdx = i
			break
		}
	}
	if skillIdx < 0 {
		t.Fatal("skill 0 not found in legal actions")
	}

	g.Step(skillIdx)

	// P1 HP 应减少 2（物理伤害 2，无护盾无反应）
	if err := s.DoString(`_p1hp = get_char("猫咪P1"):hp():get()`); err != nil {
		t.Fatalf("read P1 HP: %v", err)
	}
	hp, _ := s.GetGlobalInt("_p1hp")
	if hp != 13 {
		t.Fatalf("expected P1 HP=13, got %d", hp)
	}

	// 行动权应翻转到 P1
	if g.Turn != 1 {
		t.Fatalf("expected Turn=1 after battle action, got %d", g.Turn)
	}
}

func TestE2E_DiehuoEnchant(t *testing.T) {
	// 赤蝶 vs 猫咪：赤蝶开蝶火后普攻应造成火伤害 4 点（2 基础 +2 蝶火）
	g := engine.NewGame(engine.GameConfig{
		Players: [2]engine.PlayerConfig{
			{Chars: []engine.CharConfig{{}}},
			{Chars: []engine.CharConfig{{}}},
		},
	})
	g.Players[0].ActiveChar = 0
	g.Players[1].ActiveChar = 0

	s := NewState()
	defer s.Close()
	InitCounterMetatable(s)
	RegisterPrelude(s, g)
	defer Cleanup(s)

	// 加载系统
	for _, f := range []string{
		"../../data/system/round.lua",
	} {
		if err := s.DoFile(f); err != nil {
			t.Fatalf("load %s: %v", f, err)
		}
	}

	// P0: 赤蝶
	if err := s.DoFile("../../data/characters/赤蝶/赤蝶.lua"); err != nil {
		t.Fatal(err)
	}
	if err := s.DoString(`bind_char("赤蝶", 0, 0)`); err != nil {
		t.Fatal(err)
	}
	if err := s.DoFile("../../data/characters/赤蝶/赤蝶_枪.lua"); err != nil {
		t.Fatal(err)
	}
	if err := s.DoFile("../../data/characters/赤蝶/赤蝶_回火.lua"); err != nil {
		t.Fatal(err)
	}
	if err := s.DoFile("../../data/characters/赤蝶/赤蝶_蝶火.lua"); err != nil {
		t.Fatal(err)
	}

	// P1: 简单目标
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

	g.NewRound()

	// 找到蝶火技能（skill 2 — 枪=0, 回火=1, 蝶火=2）
	actions := g.GetLegalActions()
	for i, a := range actions {
		if a.Kind == engine.ActionSkill && a.Index == 2 {
			g.Step(i)
			break
		}
	}

	// 赤蝶应受到 1 穿透伤害（自伤）
	if err := s.DoString(`_selfhp = get_char("赤蝶"):hp():get()`); err != nil {
		t.Fatal(err)
	}
	selfHP, _ := s.GetGlobalInt("_selfhp")
	if selfHP != 14 {
		t.Fatalf("赤蝶 HP should be 14 after self-damage, got %d", selfHP)
	}

	// 行动权翻转到 P1，P1 随便做一个动作（结束回合）
	actions = g.GetLegalActions()
	for i, a := range actions {
		if a.Kind == engine.ActionEndTurn {
			g.Step(i)
			break
		}
	}

	// 回到 P0，使用普攻（skill 0）
	actions = g.GetLegalActions()
	for i, a := range actions {
		if a.Kind == engine.ActionSkill && a.Index == 0 {
			g.Step(i)
			break
		}
	}

	// 目标应受到 4 点伤害（2 基础 + 2 蝶火加伤），且元素应为火（附魔）
	if err := s.DoString(`_targethp = get_char("目标"):hp():get()`); err != nil {
		t.Fatal(err)
	}
	targetHP, _ := s.GetGlobalInt("_targethp")
	if targetHP != 11 {
		t.Fatalf("目标 HP should be 11 (15 - 4 fire), got %d", targetHP)
	}
}

func TestE2E_PomoChain(t *testing.T) {
	// 墨客使用水龙吟后，普攻应触发泼墨额外 2 水伤害
	g := engine.NewGame(engine.GameConfig{
		Players: [2]engine.PlayerConfig{
			{Chars: []engine.CharConfig{{}}},
			{Chars: []engine.CharConfig{{}}},
		},
	})
	g.Players[0].ActiveChar = 0
	g.Players[1].ActiveChar = 0

	s := NewState()
	defer s.Close()
	InitCounterMetatable(s)
	RegisterPrelude(s, g)
	defer Cleanup(s)

	if err := s.DoFile("../../data/system/round.lua"); err != nil {
		t.Fatal(err)
	}

	// P0: 墨客
	if err := s.DoFile("../../data/characters/墨客/墨客.lua"); err != nil {
		t.Fatal(err)
	}
	if err := s.DoString(`bind_char("墨客", 0, 0)`); err != nil {
		t.Fatal(err)
	}
	for _, f := range []string{
		"../../data/characters/墨客/墨客_剑.lua",
		"../../data/characters/墨客/墨客_水龙吟.lua",
	} {
		if err := s.DoFile(f); err != nil {
			t.Fatal(err)
		}
	}

	// P1: 目标
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

	// 给墨客 2 能量（直接操作）
	if err := s.DoString(`get_char("墨客"):energy():set(2)`); err != nil {
		t.Fatal(err)
	}

	g.NewRound()

	// 使用水龙吟（skill 2 — 剑=0, 墨意未加载所以没有, 水龙吟=1）
	// 实际上只加载了 剑 和 水龙吟，所以 剑=0, 水龙吟=1
	actions := g.GetLegalActions()
	for i, a := range actions {
		if a.Kind == engine.ActionSkill && a.Index == 1 {
			g.Step(i)
			break
		}
	}

	// P1 结束回合
	actions = g.GetLegalActions()
	for i, a := range actions {
		if a.Kind == engine.ActionEndTurn {
			g.Step(i)
			break
		}
	}

	// P0 使用普攻（skill 0）——应触发泼墨
	actions = g.GetLegalActions()
	for i, a := range actions {
		if a.Kind == engine.ActionSkill && a.Index == 0 {
			g.Step(i)
			break
		}
	}

	// 目标应受到 4 点伤害（2 物理 + 2 水泼墨）
	if err := s.DoString(`_hp = get_char("目标"):hp():get()`); err != nil {
		t.Fatal(err)
	}
	hp, _ := s.GetGlobalInt("_hp")
	if hp != 11 {
		t.Fatalf("目标 HP should be 11 (15 - 2 physical - 2 water), got %d", hp)
	}
}

func TestE2E_KillAndGameOver(t *testing.T) {
	g, s := setupE2E(t)
	defer s.Close()
	defer Cleanup(s)

	// 直接通过 Lua 把 P1 HP 打到 0
	if err := s.DoString(`get_char("猫咪P1"):hp():sub(15)`); err != nil {
		t.Fatalf("kill P1: %v", err)
	}

	// P1 角色应该死亡
	if g.Players[1].Chars[0].Alive {
		t.Fatal("P1 char should be dead")
	}

	// 1v1 场景，P1 无其他存活角色 → 游戏结束
	if g.Phase != engine.PhaseGameOver {
		t.Fatalf("expected GameOver, got phase %d", g.Phase)
	}
	if g.Winner != 0 {
		t.Fatalf("expected P0 wins, got winner %d", g.Winner)
	}
}
