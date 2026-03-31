// test/dice_system_test.go
package test

import (
	"testing"

	glua "github.com/yuin/gopher-lua"
	"gicg_sim/core"
	"gicg_sim/lua"
)

// TestDiceManager 测试骰子管理器
func TestDiceManager(t *testing.T) {
	dm := core.NewDiceManager(nil)

	// 1. 测试投掷骰子
	t.Run("Roll", func(t *testing.T) {
		dm.Clear()
		dm.Roll(8)
		if dm.GetTotal() != 8 {
			t.Errorf("期望8个骰子，实际%d", dm.GetTotal())
		}
	})

	// 2. 测试获取数量
	t.Run("GetCount", func(t *testing.T) {
		dm.Clear()
		// 手动添加一些骰子
		dm.Dices = append(dm.Dices, &core.Dice{Type: core.DicePyro})
		dm.Dices = append(dm.Dices, &core.Dice{Type: core.DicePyro})
		dm.Dices = append(dm.Dices, &core.Dice{Type: core.DiceElectro})
		dm.Dices = append(dm.Dices, &core.Dice{Type: core.DiceOmni})

		if dm.GetCount(core.DicePyro) != 2 {
			t.Errorf("期望2个火骰，实际%d", dm.GetCount(core.DicePyro))
		}
		if dm.GetCount(core.DiceElectro) != 1 {
			t.Errorf("期望1个雷骰，实际%d", dm.GetCount(core.DiceElectro))
		}
		if dm.GetCount(core.DiceOmni) != 1 {
			t.Errorf("期望1个万能骰，实际%d", dm.GetCount(core.DiceOmni))
		}
	})

	// 3. 测试消耗骰子
	t.Run("Consume", func(t *testing.T) {
		dm.Clear()
		// 添加骰子：3火 + 2万能
		dm.Dices = append(dm.Dices, &core.Dice{Type: core.DicePyro})
		dm.Dices = append(dm.Dices, &core.Dice{Type: core.DicePyro})
		dm.Dices = append(dm.Dices, &core.Dice{Type: core.DicePyro})
		dm.Dices = append(dm.Dices, &core.Dice{Type: core.DiceOmni})
		dm.Dices = append(dm.Dices, &core.Dice{Type: core.DiceOmni})

		// 消耗2个火骰 - 应该成功
		if !dm.Consume(core.DicePyro, 2) {
			t.Error("消耗2个火骰应该成功")
		}
		if dm.GetCount(core.DicePyro) != 1 {
			t.Errorf("消耗后应该剩1个火骰，实际%d", dm.GetCount(core.DicePyro))
		}

		// 消耗2个火骰 - 只剩1个火骰，需要用万能补充
		if !dm.Consume(core.DicePyro, 2) {
			t.Error("消耗2个火骰（1火+1万能）应该成功")
		}
		if dm.GetCount(core.DicePyro) != 0 {
			t.Errorf("消耗后应该剩0个火骰，实际%d", dm.GetCount(core.DicePyro))
		}
		if dm.GetCount(core.DiceOmni) != 1 {
			t.Errorf("应该剩1个万能骰，实际%d", dm.GetCount(core.DiceOmni))
		}

		// 消耗2个火骰 - 只剩1个万能，不够
		if dm.Consume(core.DicePyro, 2) {
			t.Error("消耗2个火骰（只有1万能）应该失败")
		}
	})
}

// TestPendingManager 测试等待管理器
func TestPendingManager(t *testing.T) {
	pm := core.NewPendingManager()

	// 1. 测试创建等待
	t.Run("CreatePending", func(t *testing.T) {
		pending := pm.CreateRerollPending(0, []int{0, 1, 2, 3, 4, 5, 6, 7})

		if pending.Type != core.PendingRerollDice {
			t.Errorf("期望类型 reroll_dice，实际%s", pending.Type)
		}
		if pending.SideIdx != 0 {
			t.Errorf("期望 side 0，实际%d", pending.SideIdx)
		}
		if pm.IsPending() != true {
			t.Error("应该有等待状态")
		}
	})

	// 2. 测试解决等待
	t.Run("Resolve", func(t *testing.T) {
		result := &core.RerollDiceResult{
			SelectedIndices: []int{0, 1, 2},
		}

		err := pm.Resolve(result)
		if err != nil {
			t.Errorf("解决等待失败: %v", err)
		}

		if pm.IsPending() {
			t.Error("解决后应该没有等待状态")
		}
	})
}

// TestConvertDice 测试调和机制
func TestConvertDice(t *testing.T) {
	game := core.NewGameState()

	// 设置角色
	fischl := core.NewCharacter("fischl", "菲谢尔", 10, 3, core.Electro)
	game.P0.LoadCharacter(0, fischl)

	dummy := core.NewCharacter("dummy", "木桩", 10, 0, core.Pyro)
	game.P1.LoadCharacter(0, dummy)

	// 添加手牌
	game.P0.AddCard("card_1")
	game.P0.AddCard("card_2")

	// 设置骰子：火、水、雷（出战元素）、万能
	game.P0.Dices.Dices = []*core.Dice{
		{Type: core.DicePyro},
		{Type: core.DiceHydro},
		{Type: core.DiceElectro},
		{Type: core.DiceOmni},
	}

	// 1. 测试正常调和：火骰 -> 雷骰
	t.Run("NormalConvert", func(t *testing.T) {
		// 用火骰（索引0）调和
		success := game.ConvertDice(0, 0, 0)
		if !success {
			t.Error("调和应该成功")
		}

		// 检查火骰变成了雷骰
		if game.P0.Dices.Dices[0].Type != core.DiceElectro {
			t.Errorf("火骰应该变成雷骰，实际是%d", game.P0.Dices.Dices[0].Type)
		}

		// 检查手牌减少
		if game.P0.GetHandSize() != 1 {
			t.Errorf("手牌应该剩1张，实际%d", game.P0.GetHandSize())
		}
	})

	// 2. 测试调和出战元素骰 - 应该失败
	t.Run("CannotConvertActiveElement", func(t *testing.T) {
		// 重置手牌
		game.P0.AddCard("card_3")

		// 尝试调和雷骰（出战元素）
		success := game.ConvertDice(0, 0, 0) // 索引0现在是雷骰
		if success {
			t.Error("调和出战元素骰应该失败")
		}
	})

	// 3. 测试调和万能骰 - 应该失败
	t.Run("CannotConvertOmni", func(t *testing.T) {
		// 找到万能骰索引
		omniIdx := -1
		for i, d := range game.P0.Dices.Dices {
			if d.Type == core.DiceOmni {
				omniIdx = i
				break
			}
		}

		if omniIdx == -1 {
			t.Skip("没有万能骰可测试")
		}

		success := game.ConvertDice(0, 0, omniIdx)
		if success {
			t.Error("调和万能骰应该失败")
		}
	})
}

// TestEndRound 测试结束回合流程
func TestEndRound(t *testing.T) {
	game := core.NewGameState()

	// 设置角色
	fischl := core.NewCharacter("fischl", "菲谢尔", 10, 3, core.Electro)
	game.P0.LoadCharacter(0, fischl)

	dummy := core.NewCharacter("dummy", "木桩", 10, 0, core.Pyro)
	game.P1.LoadCharacter(0, dummy)

	// 跳过初始骰子投掷
	game.OnPendingCreate = func(pending *core.PendingState) {
		if pending.Type == core.PendingRerollDice {
			game.PendingManager.Resolve(&core.RerollDiceResult{SelectedIndices: []int{}})
		}
	}

	// 开始战斗
	game.StartBattle()

	// 1. 测试 P0 结束回合
	t.Run("P0EndRound", func(t *testing.T) {
		handSizeBefore := game.P0.GetHandSize()

		// P0 结束回合
		if err := game.EndRound(); err != nil {
			t.Fatalf("EndRound failed: %v", err)
		}

		// 检查切换到 P1
		if game.CurrentSide != 1 {
			t.Errorf("期望当前方为 P1，实际 P%d", game.CurrentSide)
		}

		// 检查 P0 摸牌（+2）
		handSizeAfter := game.P0.GetHandSize()
		if handSizeAfter != handSizeBefore+2 {
			t.Errorf("期望摸2张牌，%d -> %d", handSizeBefore, handSizeAfter)
		}

		// 检查 P0 骰子清空
		if game.P0.Dices.GetTotal() != 0 {
			t.Errorf("期望骰子清空，实际%d", game.P0.Dices.GetTotal())
		}
	})

	// 2. 测试 P1 结束回合（进入下一 Round）
	t.Run("P1EndRound", func(t *testing.T) {
		// 跳过 P1 的骰子投掷
		if game.PendingManager.IsPending() {
			game.PendingManager.Resolve(&core.RerollDiceResult{SelectedIndices: []int{}})
		}

		handSizeBefore := game.P1.GetHandSize()

		// P1 结束回合
		if err := game.EndRound(); err != nil {
			t.Fatalf("EndRound failed: %v", err)
		}

		// 检查进入下一 Round
		if game.Round != 2 {
			t.Errorf("期望 Round=2，实际 %d", game.Round)
		}

		// 检查回到 P0
		if game.CurrentSide != 0 {
			t.Errorf("期望当前方为 P0，实际 P%d", game.CurrentSide)
		}

		// 检查 P1 摸牌（+2）
		handSizeAfter := game.P1.GetHandSize()
		if handSizeAfter != handSizeBefore+2 {
			t.Errorf("期望摸2张牌，%d -> %d", handSizeBefore, handSizeAfter)
		}
	})
}

// TestAvailableActions 测试可选操作列表
func TestAvailableActions(t *testing.T) {
	game := core.NewGameState()

	// 设置角色（P0 有两个角色，用于测试切换）
	fischl := core.NewCharacter("fischl", "菲谢尔", 10, 3, core.Electro)
	game.P0.LoadCharacter(0, fischl)
	game.LoadCharacterData("fischl") // 加载角色数据

	// 第二个角色也使用菲谢尔数据（测试用）
	fischl2 := core.NewCharacter("fischl", "菲谢尔2", 10, 3, core.Electro)
	game.P0.LoadCharacter(1, fischl2)
	game.LoadCharacterData("fischl")

	dummy := core.NewCharacter("dummy", "木桩", 10, 0, core.Pyro)
	game.P1.LoadCharacter(0, dummy)

	// 设置骰子和手牌
	game.P0.Dices.Dices = []*core.Dice{
		{Type: core.DiceElectro},
		{Type: core.DiceElectro},
		{Type: core.DiceElectro},
		{Type: core.DicePyro},
		{Type: core.DicePyro},
	}
	game.P0.AddCard("card_1")

	// 创建等待并更新可选操作
	pending := game.PendingManager.CreateRerollPending(0, game.P0.Dices.ToSlice())
	game.CurrentSide = 0
	game.UpdatePendingActions()

	// 检查是否有技能使用选项
	hasSkill := false
	hasSwitch := false
	hasConvert := false
	hasEndRound := false

	for _, action := range pending.AvailableActions {
		switch action.Type {
		case core.ActionUseSkill:
			hasSkill = true
			t.Logf("技能: %s, cost=%v, can_use=%v", action.SkillID, action.Cost, action.CanUse)
		case core.ActionSwitchChar:
			hasSwitch = true
			t.Logf("切换角色: idx=%d, can_use=%v", action.CharIndex, action.CanUse)
		case core.ActionElementalTuning:
			hasConvert = true
			t.Logf("调和: card=%d, dice=%d", action.CardIndex, action.DiceIndex)
		case core.ActionEndRound:
			hasEndRound = true
			t.Logf("结束回合")
		}
	}

	if !hasSkill {
		t.Error("应该有技能使用选项")
	}
	if !hasSwitch {
		t.Error("应该有切换角色选项")
	}
	if !hasConvert {
		t.Error("应该有调和选项")
	}
	if !hasEndRound {
		t.Error("应该有结束回合选项")
	}
}

// TestCostAutoFill 测试费用自动填充
func TestCostAutoFill(t *testing.T) {
	dm := core.NewDiceManager(nil)

	// 测试场景1：普攻需要2任意，有1雷+1万能
	t.Run("NormalAttackWithOmni", func(t *testing.T) {
		dm.Clear()
		dm.Dices = []*core.Dice{
			{Type: core.DiceElectro},
			{Type: core.DiceOmni},
		}

		cost := core.Cost{Any: 2}
		if !dm.CanAffordCost(cost) {
			t.Error("应该有足够的骰子（1雷+1万能=2任意）")
		}
	})

	// 测试场景2：战技需要3雷，有2雷+1万能
	t.Run("ElementalSkillWithOmni", func(t *testing.T) {
		dm.Clear()
		dm.Dices = []*core.Dice{
			{Type: core.DiceElectro},
			{Type: core.DiceElectro},
			{Type: core.DiceOmni},
		}

		cost := core.Cost{
			Elements: map[core.Element]int{core.Electro: 3},
		}
		if !dm.CanAffordCost(cost) {
			t.Error("应该有足够的骰子（2雷+1万能=3雷）")
		}
	})

	// 测试场景3：战技需要3雷，有1雷+1万能（不够）
	t.Run("ElementalSkillNotEnough", func(t *testing.T) {
		dm.Clear()
		dm.Dices = []*core.Dice{
			{Type: core.DiceElectro},
			{Type: core.DiceOmni},
		}

		cost := core.Cost{
			Elements: map[core.Element]int{core.Electro: 3},
		}
		if dm.CanAffordCost(cost) {
			t.Error("应该不够（1雷+1万能<3雷）")
		}
	})

	// 测试场景4：复杂费用 - 2雷+2任意，有2雷+1火+1万能
	t.Run("ComplexCost", func(t *testing.T) {
		dm.Clear()
		dm.Dices = []*core.Dice{
			{Type: core.DiceElectro},
			{Type: core.DiceElectro},
			{Type: core.DicePyro},
			{Type: core.DiceOmni},
		}

		cost := core.Cost{
			Elements: map[core.Element]int{core.Electro: 2},
			Any:      2,
		}
		if !dm.CanAffordCost(cost) {
			t.Error("应该有足够的骰子（2雷+1火+1万能=2雷+2任意）")
		}
	})

	// 测试场景5：消耗后检查
	t.Run("ConsumeAndCheck", func(t *testing.T) {
		dm.Clear()
		dm.Dices = []*core.Dice{
			{Type: core.DiceElectro},
			{Type: core.DiceElectro},
			{Type: core.DiceElectro},
			{Type: core.DicePyro},
		}

		// 消耗2雷
		cost := core.Cost{
			Elements: map[core.Element]int{core.Electro: 2},
		}
		if !dm.ConsumeCost(cost) {
			t.Error("消耗应该成功")
		}

		// 检查剩余
		if dm.GetCount(core.DiceElectro) != 1 {
			t.Errorf("应该剩1个雷骰，实际%d", dm.GetCount(core.DiceElectro))
		}
		if dm.GetTotal() != 2 { // 1雷+1火
			t.Errorf("应该剩2个骰子，实际%d", dm.GetTotal())
		}
	})
}

// TestAvailableActionsWithCost 测试带费用的可选动作
func TestAvailableActionsWithCost(t *testing.T) {
	game := core.NewGameState()

	// 设置角色并加载数据
	fischl := core.NewCharacter("fischl", "菲谢尔", 10, 3, core.Electro)
	game.P0.LoadCharacter(0, fischl)
	game.LoadCharacterData("fischl")

	// 第二个角色也使用菲谢尔数据（测试用）
	fischl2 := core.NewCharacter("fischl", "菲谢尔2", 10, 3, core.Electro)
	game.P0.LoadCharacter(1, fischl2)
	game.LoadCharacterData("fischl")

	dummy := core.NewCharacter("dummy", "木桩", 10, 0, core.Pyro)
	game.P1.LoadCharacter(0, dummy)

	// 场景1：足够的骰子
	t.Run("EnoughDice", func(t *testing.T) {
		game.P0.Dices.Dices = []*core.Dice{
			{Type: core.DiceElectro},
			{Type: core.DiceElectro},
			{Type: core.DiceElectro},
			{Type: core.DicePyro},
			{Type: core.DicePyro},
		}

		pending := game.PendingManager.CreateRerollPending(0, game.P0.Dices.ToSlice())
		game.CurrentSide = 0
		game.UpdatePendingActions()

		// 检查普攻（2任意）- 应该可用
		// 检查战技（3雷）- 应该可用
		foundSkill := false
		for _, action := range pending.AvailableActions {
			if action.Type == core.ActionUseSkill && action.SkillID == "elemental_skill" {
				foundSkill = true
				if !action.CanUse {
					t.Error("元素战技应该可用（3雷）")
				}
				if action.Cost.Elements[core.Electro] != 3 {
					t.Errorf("战技费用应该是3雷，实际%v", action.Cost)
				}
			}
		}
		if !foundSkill {
			t.Error("应该找到元素战技选项")
		}
	})

	// 场景2：不够的元素骰，但有万能补充
	t.Run("WithOmni", func(t *testing.T) {
		game.P0.Dices.Dices = []*core.Dice{
			{Type: core.DiceElectro},
			{Type: core.DiceElectro},
			{Type: core.DiceOmni}, // 万能补充
		}

		pending := game.PendingManager.CreateRerollPending(0, game.P0.Dices.ToSlice())
		game.CurrentSide = 0
		game.UpdatePendingActions()

		// 检查战技（3雷）- 应该可用（2雷+1万能）
		for _, action := range pending.AvailableActions {
			if action.Type == core.ActionUseSkill && action.SkillID == "elemental_skill" {
				if !action.CanUse {
					t.Error("元素战技应该可用（2雷+1万能）")
				}
			}
		}
	})

	// 场景3：不够骰子
	t.Run("NotEnoughDice", func(t *testing.T) {
		game.P0.Dices.Dices = []*core.Dice{
			{Type: core.DiceElectro},
			{Type: core.DicePyro},
		}

		pending := game.PendingManager.CreateRerollPending(0, game.P0.Dices.ToSlice())
		game.CurrentSide = 0
		game.UpdatePendingActions()

		// 检查战技（3雷）- 应该不可用
		for _, action := range pending.AvailableActions {
			if action.Type == core.ActionUseSkill && action.SkillID == "elemental_skill" {
				if action.CanUse {
					t.Error("元素战技应该不可用（只有1雷+1火）")
				}
			}
		}
	})
}

// TestLuaDiceAPI 测试 Lua 骰子 API
func TestLuaDiceAPI(t *testing.T) {
	game := core.NewGameState()
	runtime := lua.NewRuntime()
	defer runtime.Close()

	// 设置角色
	fischl := core.NewCharacter("fischl", "菲谢尔", 10, 3, core.Electro)
	game.P0.LoadCharacter(0, fischl)
	runtime.SetGame(game, 0)

	// 设置骰子：3雷 + 2火 + 1万能
	game.P0.Dices.Dices = []*core.Dice{
		{Type: core.DiceElectro},
		{Type: core.DiceElectro},
		{Type: core.DiceElectro},
		{Type: core.DicePyro},
		{Type: core.DicePyro},
		{Type: core.DiceOmni},
	}

	script := `
		-- 检查 can_afford_dice (新API: can_afford_dice(amount, element))
		local canAfford3Electro = can_afford_dice(3, ELECTRO)
		local canAfford5Electro = can_afford_dice(5, ELECTRO)
		local canAfford2Pyro = can_afford_dice(2, PYRO)
		
		-- 检查 get_dice_count (新API: get_dice_count(element))
		local electroCount = get_dice_count(ELECTRO)
		local pyroCount = get_dice_count(PYRO)
		local totalCount = get_dice_count(ANY)  -- ANY 表示总数
		
		-- 消耗骰子 (新API: consume_dice(amount, element))
		-- 先消耗2个雷，再消耗1个火
		local consumeResult1 = consume_dice(2, ELECTRO)
		local consumeResult2 = consume_dice(1, PYRO)
		local consumeResult = consumeResult1 and consumeResult2
		
		-- 消耗后再次检查
		local electroAfter = get_dice_count(ELECTRO)
		local pyroAfter = get_dice_count(PYRO)
		
		-- 设置全局变量供 Go 检查
		results = {
			canAfford3Electro = canAfford3Electro,
			canAfford5Electro = canAfford5Electro,
			canAfford2Pyro = canAfford2Pyro,
			electroCount = electroCount,
			pyroCount = pyroCount,
			totalCount = totalCount,
			consumeResult = consumeResult,
			electroAfter = electroAfter,
			pyroAfter = pyroAfter,
		}
	`

	if err := runtime.ExecuteScript(script); err != nil {
		t.Fatalf("脚本执行失败: %v", err)
	}

	// 获取结果
	L := runtime.L
	results := L.GetGlobal("results")
	if results == glua.LNil {
		t.Fatal("未找到 results 变量")
	}

	table, ok := results.(*glua.LTable)
	if !ok {
		t.Fatal("results 不是 table")
	}

	// 验证结果
	checks := map[string]bool{
		"canAfford3Electro": true,
		"canAfford2Pyro":    true,
		"consumeResult":     true,
	}

	for key, expected := range checks {
		val := table.RawGetString(key)
		actual := glua.LVAsBool(val)
		if actual != expected {
			t.Errorf("%s: 期望 %v, 实际 %v", key, expected, actual)
		}
	}

	// 检查数值
	if val := glua.LVAsNumber(table.RawGetString("electroCount")); val != 3 {
		t.Errorf("electroCount: 期望 3, 实际 %v", val)
	}
	if val := glua.LVAsNumber(table.RawGetString("pyroCount")); val != 2 {
		t.Errorf("pyroCount: 期望 2, 实际 %v", val)
	}
	if val := glua.LVAsNumber(table.RawGetString("totalCount")); val != 6 {
		t.Errorf("totalCount: 期望 6, 实际 %v", val)
	}

	// 检查消耗后
	if val := glua.LVAsNumber(table.RawGetString("electroAfter")); val != 1 {
		t.Errorf("electroAfter: 期望 1, 实际 %v", val)
	}
	if val := glua.LVAsNumber(table.RawGetString("pyroAfter")); val != 1 {
		t.Errorf("pyroAfter: 期望 1, 实际 %v", val)
	}
}
