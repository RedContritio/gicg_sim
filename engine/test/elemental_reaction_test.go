// test/elemental_reaction_test.go
package test

import (
	"testing"

	"gicg_sim/core"
	"gicg_sim/lua"
)

// TestVaporizeReaction 测试蒸发反应
func TestVaporizeReaction(t *testing.T) {
	game := core.NewGameState()
	runtime := lua.NewRuntime()
	runtime.SetGame(game, 0)

	// 香菱（火）
	xiangling := core.NewCharacter("xiangling", "香菱", 10, 3, core.Pyro)
	game.P0.LoadCharacter(0, xiangling)
	game.LoadCharacterData("xiangling")

	// 芭芭拉（水）- 用菲谢尔数据代替，手动挂水
	fischl := core.NewCharacter("fischl", "菲谢尔", 10, 3, core.Electro)
	game.P1.LoadCharacter(0, fischl)
	game.LoadCharacterData("fischl")

	game.OnPendingCreate = func(pending *core.PendingState) {
		if pending.Type == core.PendingRerollDice {
			game.PendingManager.Resolve(&core.RerollDiceResult{SelectedIndices: []int{}})
		}
	}

	game.StartBattle()

	// 先给P0前台挂水（模拟被 enemy 挂水）
	game.P0.Characters[0].AddAura(core.Hydro, 2)
	t.Logf("P0香菱身上的附着: %+v", game.P0.Characters[0].Auras)

	// P0香菱用火攻击P1，但P1没有水附着，所以需要调整测试逻辑
	// 让我们给P1挂水，然后香菱打火
	game.P1.Characters[0].AddAura(core.Hydro, 2)
	t.Logf("P1敌人身上的水附着: %+v", game.P1.Characters[0].Auras)

	// P0香菱用火攻击
	game.P0.Dices.SetDice(core.DicePyro, 3)
	enemyBefore := game.P1.Characters[0].HP

	err := game.ExecuteSkill(0, "elemental_skill", runtime)
	if err != nil {
		t.Fatalf("香菱E技能失败: %v", err)
	}

	game.ProcessDamageQueue()

	damage := enemyBefore - game.P1.Characters[0].HP
	t.Logf("蒸发伤害: %d", damage)

	// 锅巴基础伤害1，蒸发*2 = 2
	if damage != 2 {
		t.Errorf("期望蒸发伤害 2，实际 %d", damage)
	}

	// 检查水附着是否被消耗
	if game.P1.Characters[0].HasAura(core.Hydro) {
		t.Error("水附着应该被消耗")
	}
}

// TestMeltReaction 测试融化反应
func TestMeltReaction(t *testing.T) {
	game := core.NewGameState()
	runtime := lua.NewRuntime()
	runtime.SetGame(game, 0)

	// 迪卢克（火）
	diluc := core.NewCharacter("diluc", "迪卢克", 10, 3, core.Pyro)
	game.P0.LoadCharacter(0, diluc)
	game.LoadCharacterData("diluc")

	// 木桩
	dummy := core.NewCharacter("dummy", "木桩", 30, 0, core.Pyro)
	game.P1.LoadCharacter(0, dummy)

	game.OnPendingCreate = func(pending *core.PendingState) {
		if pending.Type == core.PendingRerollDice {
			game.PendingManager.Resolve(&core.RerollDiceResult{SelectedIndices: []int{}})
		}
	}

	game.StartBattle()

	// 给敌人挂冰
	game.P1.Characters[0].AddAura(core.Cryo, 2)

	// 迪卢克用火攻击，触发融化（火打冰*2）
	game.P0.Dices.SetDice(core.DicePyro, 3)
	enemyBefore := game.P1.Characters[0].HP

	err := game.ExecuteSkill(0, "elemental_skill", runtime)
	if err != nil {
		t.Fatalf("迪卢克E技能失败: %v", err)
	}

	game.ProcessDamageQueue()

	damage := enemyBefore - game.P1.Characters[0].HP
	t.Logf("融化伤害: %d", damage)

	// 迪卢克E基础伤害3，融化*2 = 6
	if damage != 6 {
		t.Errorf("期望融化伤害 6，实际 %d", damage)
	}
}

// TestSummonGuoba 测试锅巴召唤物
func TestSummonGuoba(t *testing.T) {
	game := core.NewGameState()
	runtime := lua.NewRuntime()
	runtime.SetGame(game, 0)

	// 香菱
	xiangling := core.NewCharacter("xiangling", "香菱", 10, 3, core.Pyro)
	game.P0.LoadCharacter(0, xiangling)
	game.LoadCharacterData("xiangling")

	dummy := core.NewCharacter("dummy", "木桩", 30, 0, core.Pyro)
	game.P1.LoadCharacter(0, dummy)

	game.OnPendingCreate = func(pending *core.PendingState) {
		if pending.Type == core.PendingRerollDice {
			game.PendingManager.Resolve(&core.RerollDiceResult{SelectedIndices: []int{}})
		}
	}

	game.StartBattle()

	// 召唤锅巴
	game.P0.Dices.SetDice(core.DicePyro, 3)
	enemyBefore := game.P1.Characters[0].HP

	err := game.ExecuteSkill(0, "elemental_skill", runtime)
	if err != nil {
		t.Fatalf("召唤锅巴失败: %v", err)
	}

	game.ProcessDamageQueue()

	// 初始伤害1
	damage1 := enemyBefore - game.P1.Characters[0].HP
	t.Logf("锅巴初始伤害: %d", damage1)
	if damage1 != 1 {
		t.Errorf("期望初始伤害 1，实际 %d", damage1)
	}

	// 第一回合结束 - 锅巴喷火
	game.EndRound()
	game.EndRound() // P1也结束

	enemyBefore = game.P1.Characters[0].HP

	// P0第二回合结束，锅巴再次喷火
	game.EndRound()

	damage2 := enemyBefore - game.P1.Characters[0].HP
	t.Logf("锅巴回合末伤害: %d", damage2)
	if damage2 != 1 {
		t.Errorf("期望回合末伤害 1，实际 %d", damage2)
	}

	// P1结束
	game.EndRound()

	// 第三回合，锅巴应该消失了
	enemyBefore = game.P1.Characters[0].HP
	game.EndRound()

	damage3 := enemyBefore - game.P1.Characters[0].HP
	t.Logf("锅巴消失后伤害: %d", damage3)
	if damage3 != 0 {
		t.Errorf("期望锅巴消失后伤害 0，实际 %d", damage3)
	}
}
