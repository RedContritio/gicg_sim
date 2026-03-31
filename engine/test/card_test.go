// test/card_test.go
package test

import (
	"testing"

	"gicg_sim/core"
	"gicg_sim/lua"
)

// TestCardSystem 测试卡牌系统
func TestCardSystem(t *testing.T) {
	game := core.NewGameState()
	runtime := lua.NewRuntime()
	defer runtime.Close()
	runtime.SetGame(game, 0)

	// 加载角色
	diluc := core.NewCharacter("diluc", "迪卢克", 10, 3, core.Pyro)
	game.P0.LoadCharacter(0, diluc)
	game.LoadCharacterData("diluc")

	dummy := core.NewCharacter("dummy", "木桩", 30, 0, core.Pyro)
	game.P1.LoadCharacter(0, dummy)

	// 跳过骰子投掷
	game.OnPendingCreate = func(pending *core.PendingState) {
		if pending.Type == core.PendingRerollDice {
			game.PendingManager.Resolve(&core.RerollDiceResult{SelectedIndices: []int{}})
		}
	}

	// 开始战斗（会初始化牌堆并抽5张牌）
	if err := game.StartBattle(); err != nil {
		t.Fatalf("StartBattle failed: %v", err)
	}

	// 验证开局手牌
	handSize := game.P0.GetHandSize()
	t.Logf("开局手牌数: %d", handSize)
	if handSize != 5 {
		t.Errorf("期望开局手牌5张，实际 %d", handSize)
	}

	// 验证牌堆
	drawPileCount := game.P0.Deck.GetDrawPileCount()
	t.Logf("抽牌堆剩余: %d", drawPileCount)
	if drawPileCount != 25 { // 30 - 5 = 25
		t.Errorf("期望抽牌堆25张，实际 %d", drawPileCount)
	}

	// 验证卡牌都是碌碌无为
	for i, cardID := range game.P0.Hand {
		if cardID != "wuluwuwei" {
			t.Errorf("手牌[%d]期望 wuluwuwei，实际 %s", i, cardID)
		}
	}
	t.Log("所有手牌都是碌碌无为 ✓")
}

// TestPlayCard 测试打出卡牌
func TestPlayCard(t *testing.T) {
	game := core.NewGameState()
	runtime := lua.NewRuntime()
	defer runtime.Close()
	runtime.SetGame(game, 0)

	// 加载角色
	diluc := core.NewCharacter("diluc", "迪卢克", 10, 3, core.Pyro)
	game.P0.LoadCharacter(0, diluc)
	game.LoadCharacterData("diluc")

	dummy := core.NewCharacter("dummy", "木桩", 30, 0, core.Pyro)
	game.P1.LoadCharacter(0, dummy)

	// 跳过骰子投掷
	game.OnPendingCreate = func(pending *core.PendingState) {
		if pending.Type == core.PendingRerollDice {
			game.PendingManager.Resolve(&core.RerollDiceResult{SelectedIndices: []int{}})
		}
	}

	game.StartBattle()

	// 设置1个任意骰子（碌碌无为需要1个任意骰）
	game.P0.Dices.SetDice(core.DicePyro, 1)

	// 记录打出手牌前的状态
	handBefore := game.P0.GetHandSize()
	diceBefore := game.P0.Dices.GetTotal()
	discardBefore := game.P0.Deck.GetDiscardPileCount()

	t.Logf("打出手牌前 - 手牌: %d, 骰子: %d, 弃牌堆: %d", handBefore, diceBefore, discardBefore)

	// 打出第0张手牌（碌碌无为）
	err := game.PlayCard(0, runtime)
	if err != nil {
		t.Fatalf("PlayCard failed: %v", err)
	}

	// 验证结果
	handAfter := game.P0.GetHandSize()
	diceAfter := game.P0.Dices.GetTotal()
	discardAfter := game.P0.Deck.GetDiscardPileCount()

	t.Logf("打出手牌后 - 手牌: %d, 骰子: %d, 弃牌堆: %d", handAfter, diceAfter, discardAfter)

	// 手牌应该减少1张
	if handAfter != handBefore-1 {
		t.Errorf("期望手牌 %d，实际 %d", handBefore-1, handAfter)
	}

	// 骰子应该消耗1个
	if diceAfter != diceBefore-1 {
		t.Errorf("期望骰子 %d，实际 %d", diceBefore-1, diceAfter)
	}

	// 弃牌堆应该增加1张
	if discardAfter != discardBefore+1 {
		t.Errorf("期望弃牌堆 %d，实际 %d", discardBefore+1, discardAfter)
	}

	t.Log("碌碌无为打出成功，什么也不会发生 ✓")
}

// TestDrawCardsOnEndRound 测试回合结束抽牌
func TestDrawCardsOnEndRound(t *testing.T) {
	game := core.NewGameState()
	runtime := lua.NewRuntime()
	defer runtime.Close()
	runtime.SetGame(game, 0)

	// 加载角色
	diluc := core.NewCharacter("diluc", "迪卢克", 10, 3, core.Pyro)
	game.P0.LoadCharacter(0, diluc)
	game.LoadCharacterData("diluc")

	dummy := core.NewCharacter("dummy", "木桩", 30, 0, core.Pyro)
	game.P1.LoadCharacter(0, dummy)

	game.OnPendingCreate = func(pending *core.PendingState) {
		if pending.Type == core.PendingRerollDice {
			game.PendingManager.Resolve(&core.RerollDiceResult{SelectedIndices: []int{}})
		}
	}

	game.StartBattle()

	// 记录P0回合结束前的手牌
	handBefore := game.P0.GetHandSize()
	t.Logf("回合结束前手牌: %d", handBefore)

	// P0结束回合（会抽2张牌）
	game.EndRound()

	// P1结束回合（让流程继续）
	game.EndRound()

	// 回到P0的回合，检查手牌
	handAfter := game.P0.GetHandSize()
	t.Logf("下一回合P0手牌: %d", handAfter)

	// 应该抽了2张（但实际可能受手牌上限限制）
	// 开局5张，回合结束抽2张 = 7张
	expectedHand := handBefore + 2
	if handAfter != expectedHand {
		t.Errorf("期望手牌 %d，实际 %d", expectedHand, handAfter)
	}
}
