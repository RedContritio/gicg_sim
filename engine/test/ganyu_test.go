// test/ganyu_test.go
package test

import (
	"testing"

	"gicg_sim/core"
	"gicg_sim/lua"
)

// setupGanyuGame 创建带有甘雨的干净游戏状态
func setupGanyuGame() (*core.GameState, *lua.Runtime) {
	game := core.NewGameState()
	runtime := lua.NewRuntime()
	runtime.SetGame(game, 0)

	ganyu := core.NewCharacter("ganyu", "甘雨", 10, 3, core.Cryo)
	game.P0.LoadCharacter(0, ganyu)
	game.LoadCharacterData("ganyu")

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

// TestGanyuNormalAttack 测试甘雨普攻
func TestGanyuNormalAttack(t *testing.T) {
	game, runtime := setupGanyuGame()
	defer runtime.Close()

	game.P0.Dices.SetDice(core.DiceCryo, 2)

	enemyBefore := game.P1.Characters[0].HP

	err := game.ExecuteSkill(0, "normal_attack", runtime)
	if err != nil {
		t.Fatalf("普攻失败: %v", err)
	}

	game.ProcessDamageQueue()

	damage := enemyBefore - game.P1.Characters[0].HP
	t.Logf("普攻伤害: %d", damage)

	if damage != 2 {
		t.Errorf("期望伤害 2，实际 %d", damage)
	}
}

// TestGanyuElementalSkill 测试甘雨E技能（冰莲）
func TestGanyuElementalSkill(t *testing.T) {
	game, runtime := setupGanyuGame()
	defer runtime.Close()

	game.P0.Dices.SetDice(core.DiceCryo, 3)

	enemyBefore := game.P1.Characters[0].HP

	err := game.ExecuteSkill(0, "elemental_skill", runtime)
	if err != nil {
		t.Fatalf("E技能失败: %v", err)
	}

	game.ProcessDamageQueue()

	damage := enemyBefore - game.P1.Characters[0].HP
	t.Logf("E技能伤害: %d", damage)

	if damage != 1 {
		t.Errorf("期望伤害 1，实际 %d", damage)
	}
}

// TestGanyuElementalBurst 测试甘雨大招
func TestGanyuElementalBurst(t *testing.T) {
	game, runtime := setupGanyuGame()
	defer runtime.Close()

	game.P0.Dices.SetDice(core.DiceCryo, 5)

	enemyBefore := game.P1.Characters[0].HP

	err := game.ExecuteSkill(0, "elemental_burst", runtime)
	if err != nil {
		t.Fatalf("大招失败: %v", err)
	}

	game.ProcessDamageQueue()

	damage := enemyBefore - game.P1.Characters[0].HP
	t.Logf("大招伤害: %d", damage)

	if damage != 1 {
		t.Errorf("期望伤害 1，实际 %d", damage)
	}
}

// TestGanyuIceLotusTrigger 测试冰莲在回合结束触发（完整2回合流程）
func TestGanyuIceLotusTrigger(t *testing.T) {
	game, runtime := setupGanyuGame()
	defer runtime.Close()

	// 先使用E技能创建冰莲
	game.P0.Dices.SetDice(core.DiceCryo, 3)
	game.ExecuteSkill(0, "elemental_skill", runtime)
	game.ProcessDamageQueue()

	// 回合结束 - 冰莲触发第1次
	enemyBefore := game.P1.Characters[0].HP
	if err := game.EndRound(); err != nil {
		t.Fatalf("EndRound failed: %v", err)
	}

	damage := enemyBefore - game.P1.Characters[0].HP
	t.Logf("第一回合结束伤害（冰莲）: %d", damage)

	if damage != 1 {
		t.Errorf("期望冰莲伤害 1，实际 %d", damage)
	}

	// P1 结束回合
	game.EndRound()

	// P0第二回合 - 冰莲应该还有1次
	if game.PendingManager.IsPending() {
		game.PendingManager.Resolve(&core.RerollDiceResult{SelectedIndices: []int{}})
	}

	enemyBefore = game.P1.Characters[0].HP
	if err := game.EndRound(); err != nil {
		t.Fatalf("EndRound failed: %v", err)
	}

	damage = enemyBefore - game.P1.Characters[0].HP
	t.Logf("第二回合结束伤害（冰莲）: %d", damage)

	if damage != 1 {
		t.Errorf("期望冰莲伤害 1，实际 %d", damage)
	}
}
