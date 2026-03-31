// test/arlecchino_test.go
package test

import (
	"testing"

	"gicg_sim/core"
	"gicg_sim/lua"
)

// setupArlecchinoGame 创建带有阿蕾奇诺的干净游戏状态
func setupArlecchinoGame() (*core.GameState, *lua.Runtime) {
	game := core.NewGameState()
	runtime := lua.NewRuntime()
	runtime.SetGame(game, 0)

	// 加载角色
	arlecchino := core.NewCharacter("arlecchino", "阿蕾奇诺", 10, 3, core.Pyro)
	game.P0.LoadCharacter(0, arlecchino)
	game.LoadCharacterData("arlecchino")

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

// TestArlecchinoNormalAttackWithBloodDebt 测试阿蕾奇诺普攻（有血偿勒令增伤）
func TestArlecchinoNormalAttackWithBloodDebt(t *testing.T) {
	game, runtime := setupArlecchinoGame()
	defer runtime.Close()

	// 先上血偿勒令（通过E技能）- 必须使用 ExecuteSkill 才能加载技能脚本
	game.P0.Dices.SetDice(core.DicePyro, 3)
	err := game.ExecuteSkill(0, "elemental_skill", runtime)
	if err != nil {
		t.Fatalf("E技能失败: %v", err)
	}
	game.ProcessDamageQueue()

	// 设置2个任意骰用于普攻
	game.P0.Dices.SetDice(core.DicePyro, 2)

	enemyBefore := game.P1.Characters[0].HP

	err = game.ExecuteSkill(0, "normal_attack", runtime)
	if err != nil {
		t.Fatalf("普攻失败: %v", err)
	}

	game.ProcessDamageQueue()

	damage := enemyBefore - game.P1.Characters[0].HP
	t.Logf("普攻伤害（有血偿勒令）: %d", damage)

	// 期望 2+3=5
	if damage != 5 {
		t.Errorf("期望伤害 5（2基础+3血偿），实际 %d", damage)
	}
}

// TestArlecchinoElementalSkill 测试阿蕾奇诺E技能
func TestArlecchinoElementalSkill(t *testing.T) {
	game, runtime := setupArlecchinoGame()
	defer runtime.Close()

	game.P0.Dices.SetDice(core.DicePyro, 3)

	enemyBefore := game.P1.Characters[0].HP

	err := game.ExecuteSkill(0, "elemental_skill", runtime)
	if err != nil {
		t.Fatalf("E技能失败: %v", err)
	}

	game.ProcessDamageQueue()

	damage := enemyBefore - game.P1.Characters[0].HP
	t.Logf("E技能伤害: %d", damage)

	if damage != 2 {
		t.Errorf("期望伤害 2，实际 %d", damage)
	}
}

// TestArlecchinoElementalBurst 测试阿蕾奇诺大招
func TestArlecchinoElementalBurst(t *testing.T) {
	game, runtime := setupArlecchinoGame()
	defer runtime.Close()

	// 大招需要 3火 + 2任意
	game.P0.Dices.SetDice(core.DicePyro, 5)

	enemyBefore := game.P1.Characters[0].HP

	err := game.ExecuteSkill(0, "elemental_burst", runtime)
	if err != nil {
		t.Fatalf("大招失败: %v", err)
	}

	game.ProcessDamageQueue()

	damage := enemyBefore - game.P1.Characters[0].HP
	t.Logf("大招伤害: %d", damage)

	if damage != 4 {
		t.Errorf("期望伤害 4，实际 %d", damage)
	}
}
