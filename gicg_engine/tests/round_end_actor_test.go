package tests

// 回合末(及一切 per-player hook 阶段)效果必须以归属者为视角结算。
// 历史 bug:事件栈在回合末为空,currentEvent() 返回零值帧(Player=0),
// resolveTargetHP / DealDamage / Heal 全部以 P0 视角解析 → P1 的回合末
// 效果 100% 友伤自己(run 150 全部 1024 局 replay 实证)。修复后
// FirePerPlayerHooks 为每次 hook 调用压 actor 事件帧。
//
// 覆盖受影响 hook 类型:
//   以牙还牙(shared 卡,on_round_end_post_summon,FilterAny system hook,每玩家 fire 一次)
//   猫咪_甜美领域(on_round_end_post_summon,per-binding char hook,OwnerPlayer fire 一次)
//   蝶鳞(on_round_end,per-binding char hook)
//   以逸待劳(on_after_heal + defer_fn 二级链:回合末 heal 触发,defer 挂 actor 帧
//   并在 hook 结束时 drain,反击目标以归属者为视角解析)

import (
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// perCharCounterValue 读 PerChar scope counter 在 (p, c) 槽位的值。
func perCharCounterValue(t *testing.T, env *GameEnv, name string, p, c int) int {
	t.Helper()
	entry, ok := env.RT.CounterEntries()[name]
	if !ok {
		t.Fatalf("counter %s not declared", name)
	}
	pc, ok := entry.Ref.(*interp.PerCharProxy)
	if !ok {
		t.Fatalf("counter %s is not PerChar (%T)", name, entry.Ref)
	}
	return env.G.Counters[pc.IDs[p*interp.MaxChars+c]].Value
}

// playCardFromHand 注入卡到 player 手牌并经 production 合法动作路径打出。
// 调用方保证当前行动权在 player,dice 须覆盖卡费。
func playCardFromHand(t *testing.T, env *GameEnv, player int, cardName string, dice map[int]int) {
	t.Helper()
	card := env.RT.Cards.ByName[cardName]
	if card == nil {
		t.Fatalf("%s not in test pool", cardName)
	}
	env.G.Players[player].Hand = append(env.G.Players[player].Hand, engine.CardInst{Ref: card.Ref})
	env.SetDice(player, dice)
	idx := env.FindAction(engine.ActionCard, cardName)
	if idx < 0 {
		t.Fatalf("%s not offered for P%d", cardName, player)
	}
	env.Step(idx)
}

// P1 打出以牙还牙 → 回合末 tick 必须命中 P0 出战角色(伤害与元素附着
// 都落在 P0),且伤害归属 actor=P1。bug 行为是 tick 友伤 P1 自己。
func TestRoundEnd_以牙还牙_P1Owner_HitsP0Active(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"猫咪"})

	env.StepEndTurn() // P0 先宣告结束,行动权交给 P1
	if env.G.Turn != 1 {
		t.Fatalf("turn = %d, want 1 after P0 end", env.G.Turn)
	}

	playCardFromHand(t, env, 1, "以牙还牙", map[int]int{int(engine.DiceColorFire): 2})

	hp0Before := env.HP(0, 0)
	hp1Before := env.HP(1, 0)

	env.StepEndTurn() // P1 宣告结束 → 双方均已宣告,EndPhase 触发

	// tick 元素 = 敌方(P0)出战角色自己的元素 = 火(赤蝶)
	if got := env.HP(0, 0); got != hp0Before-1 {
		t.Errorf("P0 active HP = %d, want %d (P1 的以牙还牙 tick 应命中 P0)", got, hp0Before-1)
	}
	if got := env.HP(1, 0); got != hp1Before {
		t.Errorf("P1 active HP = %d, want %d (tick 不应友伤 P1 自己)", got, hp1Before)
	}
	if got := perCharCounterValue(t, env, "火元素附着", 0, 0); got != 1 {
		t.Errorf("火元素附着(0,0) = %d, want 1 (附着应落在 P0 出战角色)", got)
	}
	if got := perCharCounterValue(t, env, "火元素附着", 1, 0); got != 0 {
		t.Errorf("火元素附着(1,0) = %d, want 0", got)
	}

	if n := len(env.G.RecentDamageEvents); n != 1 {
		t.Fatalf("RecentDamageEvents len = %d, want 1 (本局唯一伤害 = tick)", n)
	}
	e := env.G.RecentDamageEvents[0]
	if e.ActorPlayer != 1 || e.TargetPlayer != 0 {
		t.Errorf("tick 归属 actor=P%d target=P%d, want actor=P1 target=P0",
			e.ActorPlayer, e.TargetPlayer)
	}
}

// P0 打出以牙还牙 → 回合末 tick 命中 P1 出战角色(锁住原本就正确的方向)。
func TestRoundEnd_以牙还牙_P0Owner_HitsP1Active(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"猫咪"})

	playCardFromHand(t, env, 0, "以牙还牙", map[int]int{int(engine.DiceColorFire): 2})

	hp0Before := env.HP(0, 0)
	hp1Before := env.HP(1, 0)

	env.StepEndTurn() // P0 宣告结束
	env.StepEndTurn() // P1 宣告结束 → EndPhase

	// tick 元素 = 敌方(P1)出战角色自己的元素 = 冰(猫咪)
	if got := env.HP(1, 0); got != hp1Before-1 {
		t.Errorf("P1 active HP = %d, want %d (P0 的以牙还牙 tick 应命中 P1)", got, hp1Before-1)
	}
	if got := env.HP(0, 0); got != hp0Before {
		t.Errorf("P0 active HP = %d, want %d", got, hp0Before)
	}
	if got := perCharCounterValue(t, env, "冰元素附着", 1, 0); got != 1 {
		t.Errorf("冰元素附着(1,0) = %d, want 1 (附着应落在 P1 出战角色)", got)
	}

	if n := len(env.G.RecentDamageEvents); n != 1 {
		t.Fatalf("RecentDamageEvents len = %d, want 1 (本局唯一伤害 = tick)", n)
	}
	e := env.G.RecentDamageEvents[0]
	if e.ActorPlayer != 0 || e.TargetPlayer != 1 {
		t.Errorf("tick 归属 actor=P%d target=P%d, want actor=P0 target=P1",
			e.ActorPlayer, e.TargetPlayer)
	}
}

// P1 猫咪召唤甜美领域(per-binding char hook)→ 回合末治疗 P1 自己的
// 出战角色 + 对 P0 出战角色造成 1 冰伤。bug 行为是治疗 P0、伤害 P1。
func TestRoundEnd_甜美领域_P1Owner_HealsOwnDamagesEnemy(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"猫咪"})

	env.StepEndTurn() // P0 先宣告结束,行动权交给 P1

	// P1 猫咪:能量 3 + 冰 3,用大招甜美领域(即时 2 冰伤 + 召唤物持续 2 回合)
	hp0Start := env.HP(0, 0)
	cat := env.RT.Chars.BySlot[1][0]
	env.G.Counters[cat.EnergyCounterID].Value = 3
	env.SetDice(1, map[int]int{int(engine.DiceColorIce): 3})
	if !env.StepSkill("甜美领域") {
		t.Fatal("甜美领域 not offered")
	}
	hp0AfterSkill := env.HP(0, 0)
	if hp0AfterSkill != hp0Start-2 {
		t.Fatalf("P0 active HP after 甜美领域 = %d, want %d (即时 2 冰伤)", hp0AfterSkill, hp0Start-2)
	}

	// 打伤猫咪,留出召唤物治疗空间
	env.G.Counters[cat.HPCounterID].Value = 6

	env.StepEndTurn() // P1 宣告结束 → EndPhase

	if got := env.HP(1, 0); got != 8 {
		t.Errorf("P1 active HP = %d, want 8 (6 + 自己召唤物治疗 2)", got)
	}
	if got := env.HP(0, 0); got != hp0AfterSkill-1 {
		t.Errorf("P0 active HP = %d, want %d (召唤物对敌冰伤 1)", got, hp0AfterSkill-1)
	}
}

// P1 赤蝶打出蝶鳞 + 枪命中种蝶印(on_round_end char hook)→ 回合末 burn
// 必须命中 P0 出战角色并清除蝶印。bug 行为是 burn 友伤 P1 自己。
func TestRoundEnd_蝶鳞_P1Owner_BurnsP0Active(t *testing.T) {
	env := NewGame(t, []string{"猫咪"}, []string{"赤蝶"})

	env.StepEndTurn() // P0 先宣告结束,行动权交给 P1

	playCardFromHand(t, env, 1, "蝶鳞", map[int]int{int(engine.DiceColorFire): 8})

	// P1 用枪命中 P0 出战角色,种下蝶印
	env.SetDice(1, map[int]int{int(engine.DiceColorFire): 8})
	if !env.StepSkill("枪") {
		t.Fatal("枪 not offered after 蝶鳞")
	}
	if got := perCharCounterValue(t, env, "蝶印", 0, 0); got != 1 {
		t.Fatalf("蝶印(0,0) = %d, want 1 (枪命中后敌方出战角色挂印)", got)
	}

	hp0Before := env.HP(0, 0)
	hp1Before := env.HP(1, 0)

	env.StepEndTurn() // P1 宣告结束 → EndPhase,蝶印 burn

	if got := env.HP(0, 0); got != hp0Before-1 {
		t.Errorf("P0 active HP = %d, want %d (P1 的蝶印 burn 应命中 P0)", got, hp0Before-1)
	}
	if got := env.HP(1, 0); got != hp1Before {
		t.Errorf("P1 active HP = %d, want %d (burn 不应友伤 P1 自己)", got, hp1Before)
	}
	if got := perCharCounterValue(t, env, "蝶印", 0, 0); got != 0 {
		t.Errorf("蝶印(0,0) = %d, want 0 (burn 后清除)", got)
	}
}

// 回合末 heal 触发的 on_after_heal 内 defer_fn 反击链:defer 挂在
// per-player actor 帧上、hook 结束时 drain — 反击必须命中 P0 出战
// 角色且不丢失。bug 行为是治疗落 P0(门控 ctx.target_player=0 →
// P1 持有的反击 hook 根本不触发)+ tick 友伤 P1。
//
// hook 体取自 以逸待劳.lua 的 on_after_heal(support-active 门控特化为
// P1)。真卡依赖已不存在的 counter "ap",被 topo loader 静默排除,
// 无法经打牌路径进入对局,故经真实 interpreter 注入等价 hook。
func TestRoundEnd_AfterHealDefer_P1Owner_CounterHitsP0(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"猫咪"})

	src := `
on_after_heal(function(ctx)
  if ctx.target_player ~= 1 then return end
  if ctx.value <= 0 then return end
  local p = ctx.target_player
  local own_active = get_active_char(p)
  local elem = _char_by_slot[p][own_active].element
  defer_fn(function()
    deal_damage(Target.EnemyActive, elem, ctx.value, { source = Source.Support })
  end)
end)
`
	lenv := interp.NewEnv(env.RT.Interp.Global)
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src), lenv); err != nil {
		t.Fatalf("register after_heal hook: %v", err)
	}

	env.StepEndTurn() // P0 先宣告结束,行动权交给 P1

	// P1 猫咪:能量 3 + 冰 3,大招召唤甜美领域
	cat := env.RT.Chars.BySlot[1][0]
	env.G.Counters[cat.EnergyCounterID].Value = 3
	env.SetDice(1, map[int]int{int(engine.DiceColorIce): 3})
	if !env.StepSkill("甜美领域") {
		t.Fatal("甜美领域 not offered")
	}
	hp0AfterSkill := env.HP(0, 0)

	// 打伤猫咪,留出召唤物治疗空间
	env.G.Counters[cat.HPCounterID].Value = 5

	env.StepEndTurn() // P1 宣告结束 → EndPhase

	// 甜美领域 tick:治疗 P1 出战 +2 → 反击 2 冰(猫咪元素)
	// 叠加 tick 自身 1 冰伤,P0 出战共 -3
	if got := env.HP(1, 0); got != 7 {
		t.Errorf("P1 active HP = %d, want 7 (5 + 甜美领域治疗 2)", got)
	}
	if got := env.HP(0, 0); got != hp0AfterSkill-3 {
		t.Errorf("P0 active HP = %d, want %d (tick 1 + 治疗反击 2)", got, hp0AfterSkill-3)
	}

	// 反击在 hook 体 tick 之后 drain → 是最后一条伤害事件:P1 → P0,值 2
	if n := len(env.G.RecentDamageEvents); n == 0 {
		t.Fatal("RecentDamageEvents empty")
	}
	last := env.G.RecentDamageEvents[len(env.G.RecentDamageEvents)-1]
	if last.ActorPlayer != 1 || last.TargetPlayer != 0 || last.FinalValue != 2 {
		t.Errorf("反击事件 actor=P%d target=P%d final=%d, want actor=P1 target=P0 final=2",
			last.ActorPlayer, last.TargetPlayer, last.FinalValue)
	}
}
