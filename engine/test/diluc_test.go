// test/diluc_test.go
package test

import (
	"testing"

	"gicg_sim/core"
	"gicg_sim/lua"
)

// setupDilucGame 创建带有迪卢克的干净游戏状态
func setupDilucGame() (*core.GameState, *lua.Runtime) {
	game := core.NewGameState()
	runtime := lua.NewRuntime()
	runtime.SetGame(game, 0)

	// 加载角色
	diluc := core.NewCharacter("diluc", "迪卢克", 10, 3, core.Pyro)
	game.P0.LoadCharacter(0, diluc)
	game.LoadCharacterData("diluc")

	// 给敌人更多HP以承受完整E技能连段测试 (3+3+5+3+3+5=22点伤害)
	dummy := core.NewCharacter("dummy", "木桩", 30, 0, core.Pyro)
	game.P1.LoadCharacter(0, dummy)

	// 跳过骰子投掷
	game.OnPendingCreate = func(pending *core.PendingState) {
		if pending.Type == core.PendingRerollDice {
			game.PendingManager.Resolve(&core.RerollDiceResult{SelectedIndices: []int{}})
		}
	}

	game.StartBattle()
	return game, runtime
}

// TestDilucNormalAttack 测试迪卢克普攻
func TestDilucNormalAttack(t *testing.T) {
	game, runtime := setupDilucGame()
	defer runtime.Close()

	// 设置2个火骰
	game.P0.Dices.SetDice(core.DicePyro, 2)

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

// TestDilucElementalSkill 测试迪卢克E技能连段
func TestDilucElementalSkill(t *testing.T) {
	game, runtime := setupDilucGame()
	defer runtime.Close()

	expectedDamages := []int{3, 3, 5, 3, 3, 5}
	actualDamages := []int{}

	for i := 0; i < 6; i++ {
		// 每段E技能前设置3个火骰
		game.P0.Dices.SetDice(core.DicePyro, 3)

		enemyBefore := game.P1.Characters[0].HP

		err := game.ExecuteSkill(0, "elemental_skill", runtime)
		if err != nil {
			t.Fatalf("第%d段E失败: %v", i+1, err)
		}

		game.ProcessDamageQueue()

		dmg := enemyBefore - game.P1.Characters[0].HP
		actualDamages = append(actualDamages, dmg)
		t.Logf("第%d段E伤害: %d", i+1, dmg)
	}

	t.Logf("期望序列: %v", expectedDamages)
	t.Logf("实际序列: %v", actualDamages)

	// 验证伤害序列
	for i, exp := range expectedDamages {
		if i >= len(actualDamages) || actualDamages[i] != exp {
			t.Errorf("第%d段E期望伤害 %d，实际 %d", i+1, exp, actualDamages[i])
		}
	}
}

// TestDilucElementalBurst 测试迪卢克大招
func TestDilucElementalBurst(t *testing.T) {
	game, runtime := setupDilucGame()
	defer runtime.Close()

	// 大招需要 3火+2任意=5个骰子
	game.P0.Dices.SetDice(core.DicePyro, 5)

	enemyBefore := game.P1.Characters[0].HP

	err := game.ExecuteSkill(0, "elemental_burst", runtime)
	if err != nil {
		t.Fatalf("大招失败: %v", err)
	}

	game.ProcessDamageQueue()

	damage := enemyBefore - game.P1.Characters[0].HP
	t.Logf("大招伤害: %d", damage)

	if damage != 8 {
		t.Errorf("期望伤害 8，实际 %d", damage)
	}
}

// TestDilucElementalSkillCrossRound 测试迪卢克E技能跨回合
// 第一回合使用2次，第二回合使用1次
// 期望：第一回合 [3, 3]，第二回合 [5]（第三段高伤害）
func TestDilucElementalSkillCrossRound(t *testing.T) {
	game, runtime := setupDilucGame()
	defer runtime.Close()

	// 第一回合 - 第1段E
	game.P0.Dices.SetDice(core.DicePyro, 3)
	enemyBefore := game.P1.Characters[0].HP
	game.ExecuteSkill(0, "elemental_skill", runtime)
	game.ProcessDamageQueue()
	dmg1 := enemyBefore - game.P1.Characters[0].HP
	t.Logf("第一回合第1段E伤害: %d", dmg1)

	// 第一回合 - 第2段E
	game.P0.Dices.SetDice(core.DicePyro, 3)
	enemyBefore = game.P1.Characters[0].HP
	game.ExecuteSkill(0, "elemental_skill", runtime)
	game.ProcessDamageQueue()
	dmg2 := enemyBefore - game.P1.Characters[0].HP
	t.Logf("第一回合第2段E伤害: %d", dmg2)

	// 结束第一回合（P0和P1都结束）
	game.EndRound() // P0结束
	game.EndRound() // P1结束，进入下一回合

	// 第二回合 - 第3段E（应该是高伤害）
	game.P0.Dices.SetDice(core.DicePyro, 3)
	enemyBefore = game.P1.Characters[0].HP
	game.ExecuteSkill(0, "elemental_skill", runtime)
	game.ProcessDamageQueue()
	dmg3 := enemyBefore - game.P1.Characters[0].HP
	t.Logf("第二回合第3段E伤害: %d", dmg3)

	// 验证
	if dmg1 != 3 {
		t.Errorf("第1段E期望伤害 3，实际 %d", dmg1)
	}
	if dmg2 != 3 {
		t.Errorf("第2段E期望伤害 3，实际 %d", dmg2)
	}
	if dmg3 != 5 {
		t.Errorf("第3段E期望伤害 5，实际 %d", dmg3)
	}

	t.Logf("跨回合E技能测试通过: [3, 3, 5]")
}
