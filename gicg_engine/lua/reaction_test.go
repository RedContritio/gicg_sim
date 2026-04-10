package lua

import (
	"fmt"
	"gicg_mono/gicg_engine"
	"testing"
)

// setupReactionEnv 加载 element + reactions + reaction（附着），角色在 system 之前
func setupReactionEnv(t *testing.T, setupCharsLua string, charCounts [2][]engine.CharConfig) (*engine.Game, *State) {
	t.Helper()

	g := engine.NewGame(engine.GameConfig{
		Players: [2]engine.PlayerConfig{
			{Chars: charCounts[0]},
			{Chars: charCounts[1]},
		},
	})
	g.Players[0].ActiveChar = 0
	g.Players[1].ActiveChar = 0

	s := NewState()
	InitCounterMetatable(s)
	RegisterPrelude(s, g)

	if err := s.DoStringSandboxed(setupCharsLua); err != nil {
		t.Fatalf("setup chars: %v", err)
	}

	for _, f := range []string{
		"../../data/system/round.lua",
		"../../data/system/element.lua",
		"../../data/system/frozen.lua",
		"../../data/system/reactions/解冻.lua",
		"../../data/system/reactions/蒸发.lua",
		"../../data/system/reactions/融化.lua",
		"../../data/system/reactions/超载.lua",
		"../../data/system/reactions/感电.lua",
		"../../data/system/reactions/冻结.lua",
		"../../data/system/reactions/超导.lua",
		"../../data/system/reactions/结晶.lua",
		"../../data/system/reaction.lua",
	} {
		if err := s.DoFileSandboxed(f); err != nil {
			t.Fatalf("load %s: %v", f, err)
		}
	}

	g.NewRound()
	return g, s
}

func setup1v1(t *testing.T, charsLua string) (*engine.Game, *State) {
	t.Helper()
	return setupReactionEnv(t, charsLua, [2][]engine.CharConfig{
		{{}},
		{{}},
	})
}

func luaInt(t *testing.T, s *State, expr string) int {
	t.Helper()
	if err := s.DoString("_v = " + expr); err != nil {
		t.Fatalf("eval %s: %v", expr, err)
	}
	v, _ := s.GetGlobalInt("_v")
	return v
}

func getAttached(t *testing.T, s *State, elem string, p, c int) int {
	t.Helper()
	return luaInt(t, s, fmt.Sprintf(
		`get_counter("attached_%s", Scope.PerChar):get_at(%d, %d)`, elem, p, c))
}

func setAttached(t *testing.T, s *State, elem string, p, c, v int) {
	t.Helper()
	if err := s.DoString(fmt.Sprintf(
		`get_counter("attached_%s", Scope.PerChar):set_at(%d, %d, %d)`, elem, p, c, v)); err != nil {
		t.Fatalf("setAttached: %v", err)
	}
}

func getFrozen(t *testing.T, s *State, p, c int) int {
	t.Helper()
	return luaInt(t, s, fmt.Sprintf(
		`get_counter("frozen", Scope.PerChar):get_at(%d, %d)`, p, c))
}

func setFrozen(t *testing.T, s *State, p, c, v int) {
	t.Helper()
	if err := s.DoString(fmt.Sprintf(
		`get_counter("frozen", Scope.PerChar):set_at(%d, %d, %d)`, p, c, v)); err != nil {
		t.Fatalf("setFrozen: %v", err)
	}
}

func useSkill(t *testing.T, g *engine.Game, nth int) {
	t.Helper()
	count := 0
	for i, a := range g.GetLegalActions() {
		if a.Kind == engine.ActionSkill {
			if count == nth {
				g.Step(i)
				return
			}
			count++
		}
	}
	t.Fatalf("skill #%d not found (%d available)", nth, count)
}

func endTurn(t *testing.T, g *engine.Game) {
	t.Helper()
	for i, a := range g.GetLegalActions() {
		if a.Kind == engine.ActionEndTurn {
			g.Step(i)
			return
		}
	}
	t.Fatal("end turn not found")
}

const defaultChars = `
declare_char("A", { hp = 15, max_energy = 0, element = Element.Fire })
bind_char("A", 0, 0)
local a = get_char("A")
local sk0 = declare_skill(a, "火攻", 3)
on_skill_use(function(ctx)
  if ctx.skill_index ~= sk0 then return end
  deal_damage(Target.EnemyActive, Element.Fire, 3)
end)
local sk1 = declare_skill(a, "物攻", 3)
on_skill_use(function(ctx)
  if ctx.skill_index ~= sk1 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 2)
end)
local sk2 = declare_skill(a, "待机", 3)
on_skill_use(function(ctx)
  if ctx.skill_index ~= sk2 then return end
end)

declare_char("B", { hp = 15, max_energy = 0, element = Element.Ice })
bind_char("B", 1, 0)
local b = get_char("B")
local sk3 = declare_skill(b, "冰攻", 3)
on_skill_use(function(ctx)
  if ctx.skill_index ~= sk3 then return end
  deal_damage(Target.EnemyActive, Element.Ice, 3)
end)
local sk4 = declare_skill(b, "水攻", 3)
on_skill_use(function(ctx)
  if ctx.skill_index ~= sk4 then return end
  deal_damage(Target.EnemyActive, Element.Water, 2)
end)
local sk5 = declare_skill(b, "待机", 3)
on_skill_use(function(ctx)
  if ctx.skill_index ~= sk5 then return end
end)
`

func TestReaction_Attach(t *testing.T) {
	g, s := setup1v1(t, defaultChars)
	defer s.Close()
	defer Cleanup(s)

	useSkill(t, g, 0) // P0 火攻
	if hp := luaInt(t, s, `get_char("B"):hp():get()`); hp != 12 {
		t.Fatalf("HP=%d, want 12", hp)
	}
	if v := getAttached(t, s, "fire", 1, 0); v != 1 {
		t.Fatalf("attached_fire=%d, want 1", v)
	}
}

func TestReaction_NoAttachPhysical(t *testing.T) {
	g, s := setup1v1(t, defaultChars)
	defer s.Close()
	defer Cleanup(s)

	useSkill(t, g, 1) // P0 物攻
	if v := getAttached(t, s, "fire", 1, 0); v != 0 {
		t.Fatalf("should not attach physical, got %d", v)
	}
}

func TestReaction_Melt(t *testing.T) {
	g, s := setup1v1(t, defaultChars)
	defer s.Close()
	defer Cleanup(s)

	setAttached(t, s, "ice", 1, 0, 1)
	useSkill(t, g, 0) // 火 + 冰附着 → 融化 +2
	if hp := luaInt(t, s, `get_char("B"):hp():get()`); hp != 10 {
		t.Fatalf("HP=%d, want 10 (15-5)", hp)
	}
	if v := getAttached(t, s, "ice", 1, 0); v != 0 {
		t.Fatalf("ice should be cleared, got %d", v)
	}
}

func TestReaction_Vaporize(t *testing.T) {
	g, s := setup1v1(t, defaultChars)
	defer s.Close()
	defer Cleanup(s)

	setAttached(t, s, "water", 1, 0, 1)
	useSkill(t, g, 0) // 火 + 水附着 → 蒸发 +2
	if hp := luaInt(t, s, `get_char("B"):hp():get()`); hp != 10 {
		t.Fatalf("HP=%d, want 10", hp)
	}
}

func TestReaction_Freeze(t *testing.T) {
	g, s := setup1v1(t, defaultChars)
	defer s.Close()
	defer Cleanup(s)

	setAttached(t, s, "ice", 0, 0, 1) // P0 有冰附着
	useSkill(t, g, 0)                           // P0 火攻 → 翻转到 P1
	useSkill(t, g, 1)                           // P1 水攻 P0 → 水 + 冰 = 冻结

	if v := getFrozen(t, s, 0, 0); v != 1 {
		t.Fatalf("frozen=%d, want 1", v)
	}
	// 冻结角色不能用技能
	for _, a := range g.GetLegalActions() {
		if a.Kind == engine.ActionSkill {
			t.Fatal("frozen char should not have skill actions")
		}
	}
}

func TestReaction_Thaw(t *testing.T) {
	g, s := setup1v1(t, defaultChars)
	defer s.Close()
	defer Cleanup(s)

	setFrozen(t, s, 1, 0, 1)
	useSkill(t, g, 0) // 火 + 冻结 → 解冻 +2
	if hp := luaInt(t, s, `get_char("B"):hp():get()`); hp != 10 {
		t.Fatalf("HP=%d, want 10 (15-5)", hp)
	}
	if v := getFrozen(t, s, 1, 0); v != 0 {
		t.Fatalf("frozen=%d, want 0", v)
	}
}

func TestReaction_ThawConsumesElement(t *testing.T) {
	g, s := setup1v1(t, defaultChars)
	defer s.Close()
	defer Cleanup(s)

	// frozen + water附着，火打过来：只触发解冻(+2)，不触发蒸发
	setFrozen(t, s, 1, 0, 1)
	setAttached(t, s, "water", 1, 0, 1)
	useSkill(t, g, 0) // 火攻
	if hp := luaInt(t, s, `get_char("B"):hp():get()`); hp != 10 {
		t.Fatalf("HP=%d, want 10 (thaw only, not thaw+vaporize)", hp)
	}
	// 水附着应保留（火被解冻消耗，没有触发蒸发）
	if v := getAttached(t, s, "water", 1, 0); v != 1 {
		t.Fatalf("water should remain, got %d", v)
	}
}

func TestReaction_SameElement(t *testing.T) {
	g, s := setup1v1(t, defaultChars)
	defer s.Close()
	defer Cleanup(s)

	setAttached(t, s, "fire", 1, 0, 1)
	useSkill(t, g, 0) // 火 + 火附着 → 不反应
	if hp := luaInt(t, s, `get_char("B"):hp():get()`); hp != 12 {
		t.Fatalf("HP=%d, want 12 (no reaction)", hp)
	}
	if v := getAttached(t, s, "fire", 1, 0); v != 1 {
		t.Fatalf("fire should remain, got %d", v)
	}
}

func TestReaction_Overload(t *testing.T) {
	g := engine.NewGame(engine.GameConfig{
		Players: [2]engine.PlayerConfig{
			{Chars: []engine.CharConfig{{}}},
			{Chars: []engine.CharConfig{{}, {}}},
		},
	})
	g.Players[0].ActiveChar = 0
	g.Players[1].ActiveChar = 0

	s := NewState()
	InitCounterMetatable(s)
	RegisterPrelude(s, g)
	defer s.Close()
	defer Cleanup(s)

	s.DoStringSandboxed(`
		declare_char("攻", { hp = 15, max_energy = 0, element = Element.Fire })
		bind_char("攻", 0, 0)
		local a = get_char("攻")
		local sk = declare_skill(a, "火攻", 3)
		on_skill_use(function(ctx)
			if ctx.skill_index ~= sk then return end
			deal_damage(Target.EnemyActive, Element.Fire, 3)
		end)
		declare_skill(a, "s2", 3)
		declare_skill(a, "s3", 3)

		declare_char("目标A", { hp = 15, max_energy = 0, element = Element.Electro })
		bind_char("目标A", 1, 0)
		local b = get_char("目标A")
		declare_skill(b, "待机", 3)

		declare_char("目标B", { hp = 15, max_energy = 0, element = Element.None })
		bind_char("目标B", 1, 1)
		local c = get_char("目标B")
		declare_skill(c, "待机", 3)
	`)

	for _, f := range []string{
		"../../data/system/round.lua",
		"../../data/system/element.lua",
		"../../data/system/frozen.lua",
		"../../data/system/reactions/解冻.lua",
		"../../data/system/reactions/超载.lua",
		"../../data/system/reaction.lua",
	} {
		if err := s.DoFile(f); err != nil {
			t.Fatalf("load %s: %v", f, err)
		}
	}

	setAttached(t, s, "electro", 1, 0, 1)
	g.NewRound()
	useSkill(t, g, 0) // 火 + 雷 → 超载 +2, 强制切换

	if hp := luaInt(t, s, `get_char("目标A"):hp():get()`); hp != 10 {
		t.Fatalf("HP=%d, want 10", hp)
	}
	if g.Players[1].ActiveChar != 1 {
		t.Fatalf("active=%d, want 1 after overload", g.Players[1].ActiveChar)
	}
}

func TestReaction_Electrocharge(t *testing.T) {
	g := engine.NewGame(engine.GameConfig{
		Players: [2]engine.PlayerConfig{
			{Chars: []engine.CharConfig{{}}},
			{Chars: []engine.CharConfig{{}, {}}},
		},
	})
	g.Players[0].ActiveChar = 0
	g.Players[1].ActiveChar = 0

	s := NewState()
	InitCounterMetatable(s)
	RegisterPrelude(s, g)
	defer s.Close()
	defer Cleanup(s)

	s.DoStringSandboxed(`
		declare_char("攻", { hp = 15, max_energy = 0, element = Element.Water })
		bind_char("攻", 0, 0)
		local a = get_char("攻")
		local sk = declare_skill(a, "水攻", 3)
		on_skill_use(function(ctx)
			if ctx.skill_index ~= sk then return end
			deal_damage(Target.EnemyActive, Element.Water, 2)
		end)
		declare_skill(a, "s2", 3)
		declare_skill(a, "s3", 3)

		declare_char("目标A", { hp = 15, max_energy = 0, element = Element.Electro })
		bind_char("目标A", 1, 0)
		declare_skill(get_char("目标A"), "待机", 3)

		declare_char("目标B", { hp = 15, max_energy = 0, element = Element.None })
		bind_char("目标B", 1, 1)
		declare_skill(get_char("目标B"), "待机", 3)
	`)

	for _, f := range []string{
		"../../data/system/round.lua",
		"../../data/system/element.lua",
		"../../data/system/frozen.lua",
		"../../data/system/reactions/感电.lua",
		"../../data/system/reaction.lua",
	} {
		if err := s.DoFile(f); err != nil {
			t.Fatalf("load %s: %v", f, err)
		}
	}

	setAttached(t, s, "electro", 1, 0, 1)
	g.NewRound()
	useSkill(t, g, 0) // 水 + 雷 → 感电, 全体 1 穿透

	hpA := luaInt(t, s, `get_char("目标A"):hp():get()`)
	hpB := luaInt(t, s, `get_char("目标B"):hp():get()`)
	if hpA != 12 { // 15 - 2(水攻) - 1(感电穿透)
		t.Fatalf("目标A HP=%d, want 12", hpA)
	}
	if hpB != 14 { // 15 - 1(感电穿透)
		t.Fatalf("目标B HP=%d, want 14", hpB)
	}
}

func TestReaction_Crystallize(t *testing.T) {
	g, s := setupReactionEnv(t, `
		declare_char("岩手", { hp = 15, max_energy = 0, element = Element.Geo })
		bind_char("岩手", 0, 0)
		local a = get_char("岩手")
		local sk = declare_skill(a, "岩攻", 3)
		on_skill_use(function(ctx)
			if ctx.skill_index ~= sk then return end
			deal_damage(Target.EnemyActive, Element.Geo, 2)
		end)
		declare_skill(a, "s2", 3)
		declare_skill(a, "s3", 3)

		declare_char("目标", { hp = 15, max_energy = 0, element = Element.Fire })
		bind_char("目标", 1, 0)
		local b = get_char("目标")
		declare_skill(b, "待机", 3)
		declare_skill(b, "s2", 3)
		declare_skill(b, "s3", 3)
	`, [2][]engine.CharConfig{
		{{}},
		{{}},
	})
	defer s.Close()
	defer Cleanup(s)

	setAttached(t, s, "fire", 1, 0, 1)
	useSkill(t, g, 0) // 岩 + 火附着 → 结晶

	if v := getAttached(t, s, "fire", 1, 0); v != 0 {
		t.Fatalf("fire should be cleared, got %d", v)
	}
	shield := luaInt(t, s, `get_counter("结晶护盾", Scope.PerPlayer):get_at(0)`)
	if shield != 1 {
		t.Fatalf("shield=%d, want 1", shield)
	}
}
