package lua

import (
	"gicg_mono/gicg_engine"
	"testing"
)

func setupGame(t *testing.T) (*engine.Game, *State) {
	t.Helper()
	g := engine.NewGame(engine.GameConfig{
		Players: [2]engine.PlayerConfig{
			{Chars: []engine.CharConfig{{}, {}, {}}},
			{Chars: []engine.CharConfig{{}, {}, {}}},
		},
	})

	// 测试中直接设置出战角色，跳过选人阶段
	g.Players[0].ActiveChar = 0
	g.Players[1].ActiveChar = 0

	s := NewState()
	InitCounterMetatable(s)
	RegisterPrelude(s, g)

	return g, s
}

func TestSelectActiveAndStartGame(t *testing.T) {
	g, s := setupGame(t)
	defer s.Close()
	defer Cleanup(s)

	// 重置 ActiveChar 为 -1（模拟真实初始化）
	g.Players[0].ActiveChar = -1
	g.Players[1].ActiveChar = -1

	err := s.DoFile("../../data/system/round.lua")
	if err != nil {
		t.Fatalf("load round.lua: %v", err)
	}

	// 进入选人阶段
	g.StartGame()

	if g.Phase != engine.PhaseSelectActive {
		t.Fatalf("expected PhaseSelectActive, got %d", g.Phase)
	}

	// P0 先选
	actions := g.GetLegalActions()
	if len(actions) != 3 { // 3 个角色可选
		t.Fatalf("expected 3 select actions, got %d", len(actions))
	}

	// P0 选第 1 个角色
	g.Step(1)
	if g.Players[0].ActiveChar != 1 {
		t.Fatalf("expected P0 active=1, got %d", g.Players[0].ActiveChar)
	}

	// P1 还没选，仍在选人阶段
	if g.Phase != engine.PhaseSelectActive {
		t.Fatalf("expected still in SelectActive, got %d", g.Phase)
	}
	if g.Turn != 1 {
		t.Fatalf("expected P1 turn, got %d", g.Turn)
	}

	// P1 选第 2 个角色
	g.Step(2)
	if g.Players[1].ActiveChar != 2 {
		t.Fatalf("expected P1 active=2, got %d", g.Players[1].ActiveChar)
	}

	// 双方都选完，应进入 PhaseAction（经过 NewRound）
	if g.Phase != engine.PhaseAction {
		t.Fatalf("expected PhaseAction after both selected, got %d", g.Phase)
	}

	// 验证 round_num = 1
	err = s.DoString(`_round = get_counter("round_num", Scope.Global):get()`)
	if err != nil {
		t.Fatalf("read round: %v", err)
	}
	rv, _ := s.GetGlobalInt("_round")
	if rv != 1 {
		t.Fatalf("expected round=1, got %d", rv)
	}
}

func TestDeathForcedSwitch(t *testing.T) {
	g, s := setupGame(t)
	defer s.Close()
	defer Cleanup(s)

	err := s.DoFile("../../data/system/round.lua")
	if err != nil {
		t.Fatalf("load round.lua: %v", err)
	}

	// 声明角色和注册死亡检测
	err = s.DoString(`
		local ch = declare_char("目标", {
			hp = 5,
			max_energy = 0,
			element = Element.None,
		})

		-- 手动注册死亡检测（正式版在 death.lua 中由 declare_char 自动注册）
		on_after_write(ch:hp(), Op.Sub, function(ctx)
			if ch:hp():get() <= 0 then
				set_alive(0, 0, false)
				request_switch(0)
			end
		end)
	`)
	if err != nil {
		t.Fatalf("DoString: %v", err)
	}

	// 模拟伤害导致死亡
	err = s.DoString(`
		get_char("目标"):hp():sub(10)
	`)
	if err != nil {
		t.Fatalf("kill char: %v", err)
	}

	// 角色应已死亡
	if g.Players[0].Chars[0].Alive {
		t.Fatal("char should be dead")
	}

	// 应有 PendingAction 等待切换
	if g.PendingAction == nil {
		t.Fatal("expected PendingAction for forced switch")
	}
	if g.PendingAction.Kind != engine.ActionSwitch {
		t.Fatalf("expected ActionSwitch, got %d", g.PendingAction.Kind)
	}
}

func TestSystemRoundLua(t *testing.T) {
	g, s := setupGame(t)
	defer s.Close()
	defer Cleanup(s)

	// 加载 round.lua
	err := s.DoFile("../../data/system/round.lua")
	if err != nil {
		t.Fatalf("load round.lua: %v", err)
	}

	// 触发 NewRound
	g.NewRound()

	// 通过 Lua 读取 round_num counter
	err = s.DoString(`_round = get_counter("round_num", Scope.Global):get()`)
	if err != nil {
		t.Fatalf("read round_num: %v", err)
	}
	roundVal, ok := s.GetGlobalInt("_round")
	if !ok || roundVal != 1 {
		t.Fatalf("expected round_num=1, got %d (ok=%v)", roundVal, ok)
	}

	// 验证 round1_first_player 已记录
	err = s.DoString(`_r1fp = get_counter("round1_first_player", Scope.Global):get()`)
	if err != nil {
		t.Fatalf("read round1_first_player: %v", err)
	}
	r1fp, ok := s.GetGlobalInt("_r1fp")
	if !ok || r1fp != 0 {
		t.Fatalf("expected round1_first_player=0 (P0 goes first in round 1), got %d", r1fp)
	}
}

func TestSystemDrawLua(t *testing.T) {
	g, s := setupGame(t)
	defer s.Close()
	defer Cleanup(s)

	// 给两边各加 10 张牌到牌堆
	for i := 0; i < 10; i++ {
		g.Players[0].Deck = append(g.Players[0].Deck, engine.CardInst{Ref: i})
		g.Players[1].Deck = append(g.Players[1].Deck, engine.CardInst{Ref: i + 100})
	}
	g.Players[0].InitDeck = append([]engine.CardInst{}, g.Players[0].Deck...)
	g.Players[1].InitDeck = append([]engine.CardInst{}, g.Players[1].Deck...)

	err := s.DoFile("../../data/system/round.lua")
	if err != nil {
		t.Fatalf("load round.lua: %v", err)
	}
	err = s.DoFile("../../data/system/draw.lua")
	if err != nil {
		t.Fatalf("load draw.lua: %v", err)
	}

	// 开始回合
	g.NewRound()
	g.Phase = engine.PhaseAction

	// 双方声明结束
	g.Players[0].DeclaredEnd = true
	g.Players[1].DeclaredEnd = true
	g.FirstEnd = 0

	// 触发结束阶段（draw.lua 在 RoundEndFinal 抽 2 张）
	g.EndPhase()

	// P0 应有 2 张手牌（从牌堆抽的）
	if len(g.Players[0].Hand) != 2 {
		t.Fatalf("expected P0 hand=2, got %d", len(g.Players[0].Hand))
	}
	if len(g.Players[1].Hand) != 2 {
		t.Fatalf("expected P1 hand=2, got %d", len(g.Players[1].Hand))
	}
}

func TestDeclareCharFullFlow(t *testing.T) {
	g, s := setupGame(t)
	defer s.Close()
	defer Cleanup(s)

	err := s.DoFile("../../data/system/round.lua")
	if err != nil {
		t.Fatalf("load round.lua: %v", err)
	}

	// 声明角色和技能
	err = s.DoString(`
		local ch = declare_char("战士", {
			hp = 8,
			max_energy = 2,
			element = Element.Physical,
		})
		bind_char("战士", 0, 0)

		local sk0 = declare_skill(ch, "普攻", 3)

		on_skill_use(function(ctx)
			if ctx.skill_index ~= sk0 then return end
			ch:energy():add(1)
		end)

		local sk1 = declare_skill(ch, "大招", 3, 2)
	`)
	if err != nil {
		t.Fatalf("DoString: %v", err)
	}

	// 开始回合（AP = 8）
	g.NewRound()

	// 获取合法动作
	actions := g.GetLegalActions()

	skillCount := 0
	for _, a := range actions {
		if a.Kind == engine.ActionSkill {
			skillCount++
		}
	}
	if skillCount != 1 {
		t.Fatalf("expected 1 skill available (大招 blocked by energy), got %d", skillCount)
	}

	for i, a := range actions {
		if a.Kind == engine.ActionSkill {
			g.Step(i)
			break
		}
	}

	// 技能 hook 给了 1 能量，验证
	err = s.DoString(`_energy = get_char("战士"):energy():get()`)
	if err != nil {
		t.Fatalf("read energy: %v", err)
	}
	energy, ok := s.GetGlobalInt("_energy")
	if !ok || energy != 1 {
		t.Fatalf("expected energy=1 after skill, got %d", energy)
	}
}
