package lua

import (
	"gicg_mono/gicg_engine"
	"testing"
)

func TestBasicLuaState(t *testing.T) {
	s := NewState()
	defer s.Close()

	if err := s.DoString("x = 1 + 2"); err != nil {
		t.Fatalf("DoString failed: %v", err)
	}
	val, ok := s.GetGlobalInt("x")
	if !ok || val != 3 {
		t.Fatalf("expected x=3, got %d (ok=%v)", val, ok)
	}
}

func TestCounterFromLua(t *testing.T) {
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

	// 在 Lua 中创建 counter 并操作
	err := s.DoString(`
		hp = declare_counter("test_hp", Scope.Self, 10, { min = 0, max = 10 })
		hp:sub(3)
	`)
	if err != nil {
		t.Fatalf("DoString failed: %v", err)
	}

	s.DoString(`_hp_val = hp:get()`)
	hpVal, _ := s.GetGlobalInt("_hp_val")
	if hpVal != 7 {
		t.Fatalf("expected hp=7, got %d", hpVal)
	}
}

func TestContextPassthrough(t *testing.T) {
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

	err := s.DoString(`
		on_damage_boost(function(ctx)
			ctx.value = ctx.value + 5
			ctx.element = Element.Fire
		end)
	`)
	if err != nil {
		t.Fatalf("DoString failed: %v", err)
	}

	ctx := &engine.EventContext{
		Value:   2,
		Element: engine.ElemPhysical,
	}
	g.FireEventHooks(engine.HookDamageBoost, ctx)

	if ctx.Value != 7 {
		t.Fatalf("expected value=7, got %d", ctx.Value)
	}
	if ctx.Element != engine.ElemFire {
		t.Fatalf("expected element=Fire, got %d", ctx.Element)
	}
}

func TestActionCheckFromLua(t *testing.T) {
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

	err := s.DoString(`
		local ch = declare_char("T", { hp = 10, max_energy = 0, element = Element.None })
		bind_char("T", 0, 0)
		sk0 = declare_skill(ch, "s0", 3)
		sk1 = declare_skill(ch, "s1", 3)

		on_action_check(function(ctx)
			if ctx.skill_index == sk1 then
				ctx.playable = false
			end
		end)
	`)
	if err != nil {
		t.Fatalf("DoString: %v", err)
	}

	sk0, _ := s.GetGlobalInt("sk0")
	sk1, _ := s.GetGlobalInt("sk1")

	g.Phase = engine.PhaseAction
	g.Turn = 0
	actions := g.GetLegalActions()

	hasSk0 := false
	hasSk1 := false
	for _, a := range actions {
		if a.Kind == engine.ActionSkill && a.Index == sk0 {
			hasSk0 = true
		}
		if a.Kind == engine.ActionSkill && a.Index == sk1 {
			hasSk1 = true
		}
	}
	if !hasSk0 {
		t.Fatal("sk0 should be available")
	}
	if hasSk1 {
		t.Fatal("sk1 should be blocked by hook")
	}
}

func TestHookFromLua(t *testing.T) {
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

	// 注册一个 round_start hook（system hook 在 PerPlayer 事件上每玩家 fire 一次）
	// 用 context_player() == 0 保证全局 counter 只处理一次
	err := s.DoString(`
		counter = declare_counter("test_counter", Scope.Global, 0)
		on_round_start(function()
			if context_player() == 0 then
				counter:add(1)
			end
		end)
	`)
	if err != nil {
		t.Fatalf("DoString failed: %v", err)
	}

	// 触发 NewRound
	g.Phase = engine.PhaseNotStarted
	g.NewRound()

	s.DoString(`_cv = counter:get()`)
	cv, _ := s.GetGlobalInt("_cv")
	if cv != 1 {
		t.Fatalf("expected counter=1 after NewRound, got %d", cv)
	}

	g.NewRound()
	s.DoString(`_cv = counter:get()`)
	cv, _ = s.GetGlobalInt("_cv")
	if cv != 2 {
		t.Fatalf("expected counter=2 after second NewRound, got %d", cv)
	}
}

func TestDeclareCharAndSkill(t *testing.T) {
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

	err := s.DoString(`
		local ch = declare_char("测试角色", {
			hp = 10,
			max_energy = 3,
			element = Element.Fire,
		})
		bind_char("测试角色", 0, 0)

		assert(ch:hp():get() == 10, "HP should be 10")
		assert(ch:energy():get() == 0, "energy should start at 0")

		_sk0 = declare_skill(ch, "普攻", 3, 3)
		_sk1 = declare_skill(ch, "技能", 2)

		on_skill_use(function(ctx)
			if ctx.skill_index ~= _sk1 then return end
			ch:energy():add(1)
		end)
	`)
	if err != nil {
		t.Fatalf("DoString: %v", err)
	}

	sk0, _ := s.GetGlobalInt("_sk0")
	sk1, _ := s.GetGlobalInt("_sk1")

	g.Phase = engine.PhaseAction
	g.Turn = 0
	actions := g.GetLegalActions()

	hasSk0 := false
	hasSk1 := false
	for _, a := range actions {
		if a.Kind == engine.ActionSkill && a.Index == sk0 {
			hasSk0 = true
		}
		if a.Kind == engine.ActionSkill && a.Index == sk1 {
			hasSk1 = true
		}
	}
	if hasSk0 {
		t.Fatal("sk0 should be blocked (needs 3 energy, have 0)")
	}
	if !hasSk1 {
		t.Fatal("sk1 should be available (no energy cost)")
	}
}

func TestEnumConstants(t *testing.T) {
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

	// 正常访问
	err := s.DoString(`
		assert(Element.Fire == 1)
		assert(Element.Ice == 2)
		assert(Source.Skill == 1)
		assert(Filter.Self == -2)
		assert(Filter.Active == -3)
		assert(Scope.Self == 1)
		assert(Scope.ActiveStatus == 2)
		assert(Scope.PerEnemyChar == 5)
	`)
	if err != nil {
		t.Fatalf("enum access failed: %v", err)
	}

	// 拼写错误应报错
	err = s.DoString(`local _ = Element.Fier`)
	if err == nil {
		t.Fatal("expected error on typo Element.Fier")
	}

	// 赋值应报错
	err = s.DoString(`Element.Fire = 999`)
	if err == nil {
		t.Fatal("expected error on write to read-only enum")
	}

	// Scope 拼写错误
	err = s.DoString(`local _ = Scope.ActiveStatis`)
	if err == nil {
		t.Fatal("expected error on typo Scope.ActiveStatis")
	}
}
