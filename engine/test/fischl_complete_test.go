// test/fischl_complete_test.go
package test

import (
	"testing"

	"gicg_sim/core"
	"gicg_sim/lua"
)

// setupFischlGame 创建带有菲谢尔的干净游戏状态
func setupFischlGame() (*core.GameState, *lua.Runtime) {
	game := core.NewGameState()
	runtime := lua.NewRuntime()
	runtime.SetGame(game, 0)

	fischl := core.NewCharacter("fischl", "菲谢尔", 10, 3, core.Electro)
	game.P0.LoadCharacter(0, fischl)
	game.LoadCharacterData("fischl")

	dummy := core.NewCharacter("dummy", "木桩", 30, 0, core.Pyro)
	game.P1.LoadCharacter(0, dummy)

	game.OnPendingCreate = func(pending *core.PendingState) {
		if pending.Type == core.PendingRerollDice {
			game.PendingManager.Resolve(&core.RerollDiceResult{SelectedIndices: []int{}})
		}
	}

	game.StartBattle()
	return game, runtime
}

// TestFischlElementalSkill 测试菲谢尔E技能召唤奥兹
func TestFischlElementalSkill(t *testing.T) {
	game, runtime := setupFischlGame()
	defer runtime.Close()

	game.P0.Dices.SetDice(core.DiceElectro, 3)

	enemyBefore := game.P1.Characters[0].HP

	err := game.ExecuteSkill(0, "elemental_skill", runtime)
	if err != nil {
		t.Fatalf("ExecuteSkill failed: %v", err)
	}

	game.ProcessDamageQueue()

	damage := enemyBefore - game.P1.Characters[0].HP
	t.Logf("E技能伤害: %d", damage)

	if damage != 1 {
		t.Errorf("期望伤害 1，实际 %d", damage)
	}
}

// TestFischlOzTrigger 测试奥兹在回合结束触发伤害（完整2回合流程）
func TestFischlOzTrigger(t *testing.T) {
	game, runtime := setupFischlGame()
	defer runtime.Close()

	// 先使用E技能召唤奥兹
	game.P0.Dices.SetDice(core.DiceElectro, 3)
	game.ExecuteSkill(0, "elemental_skill", runtime)
	game.ProcessDamageQueue()

	// 第一回合结束 - 奥兹触发第1次
	enemyBefore := game.P1.Characters[0].HP
	if err := game.EndRound(); err != nil {
		t.Fatalf("EndRound failed: %v", err)
	}

	damage1 := enemyBefore - game.P1.Characters[0].HP
	t.Logf("第一回合结束伤害: %d", damage1)

	if damage1 != 1 {
		t.Errorf("期望奥兹伤害 1，实际 %d", damage1)
	}

	// P1 结束回合
	game.EndRound()

	// P0第二回合结束 - 奥兹触发第2次
	if game.PendingManager.IsPending() {
		game.PendingManager.Resolve(&core.RerollDiceResult{SelectedIndices: []int{}})
	}

	enemyBefore = game.P1.Characters[0].HP
	if err := game.EndRound(); err != nil {
		t.Fatalf("EndRound failed: %v", err)
	}

	damage2 := enemyBefore - game.P1.Characters[0].HP
	t.Logf("第二回合结束伤害: %d", damage2)

	if damage2 != 1 {
		t.Errorf("期望奥兹伤害 1，实际 %d", damage2)
	}

	// P1 结束回合
	game.EndRound()

	// P0第三回合 - 奥兹已消失，不应有伤害
	if game.PendingManager.IsPending() {
		game.PendingManager.Resolve(&core.RerollDiceResult{SelectedIndices: []int{}})
	}

	enemyBefore = game.P1.Characters[0].HP
	if err := game.EndRound(); err != nil {
		t.Fatalf("EndRound failed: %v", err)
	}

	if enemyBefore != game.P1.Characters[0].HP {
		t.Errorf("期望伤害 0，实际 %d", enemyBefore-game.P1.Characters[0].HP)
	}
}
