// core/game.go
package core

import (
	"fmt"
	"os"
	"path/filepath"
)

// CharacterLoader 全局角色数据加载器
var CharacterLoader *CharacterDataLoader

func init() {
	// 使用项目根目录的 data/ 作为默认路径
	CharacterLoader = NewCharacterDataLoader("")
	
	// 预加载所有卡牌定义
	loadAllCards()
}

// loadAllCards 加载所有卡牌定义
func loadAllCards() {
	// 加载碌碌无为卡牌
	if _, err := GlobalCardLoader.Load("wuluwuwei"); err != nil {
		// 静默失败，卡牌会在使用时按需加载
	}
}

// ActionType 操作类型
type ActionType string

const (
	ActionUseSkill        ActionType = "use_skill"        // 使用技能
	ActionSwitchChar      ActionType = "switch_char"      // 切换角色
	ActionPlayCard        ActionType = "play_card"        // 打出卡牌
	ActionElementalTuning ActionType = "elemental_tuning" // 元素调和
	ActionEndRound        ActionType = "end_round"        // 结束回合
	ActionRerollDice      ActionType = "reroll_dice"      // 重投骰子
)

// AvailableAction 可选操作
type AvailableAction struct {
	Type      ActionType `json:"type"`
	SkillID   string     `json:"skill_id,omitempty"`   // 技能ID
	CharIndex int        `json:"char_index,omitempty"` // 角色索引（切换目标）
	CardIndex int        `json:"card_index,omitempty"` // 手牌索引
	DiceIndex int        `json:"dice_index,omitempty"` // 骰子索引
	Cost      Cost       `json:"cost"`                 // 消耗（支持元素+任意）
	CanUse    bool       `json:"can_use"`              // 是否可用（骰子足够）
}

// GameState 对局状态
type GameState struct {
	P0 *Side // 玩家0
	P1 *Side // 玩家1

	CurrentSide    int            // 当前行动方 (0=P0, 1=P1)
	Round          int            // 当前回合数
	DamageQueue    []DamageInfo   // 伤害队列
	PendingManager *PendingManager // 等待管理器

	// 回合结束记录
	HasEndedRound [2]bool // 记录双方本回合是否已结束

	// 角色数据数组（最多6个不同角色）
	CharacterData [6]*CharacterData
	CharDataCount int // 实际存储的角色数据数量

	// 回调函数（供 UI/AI 使用）
	OnPendingCreate func(pending *PendingState) // 创建等待时的回调
}

// NewGameState 创建对局状态
func NewGameState() *GameState {
	return &GameState{
		P0:             NewSide(0),
		P1:             NewSide(1),
		CurrentSide:    0,
		Round:          1,
		DamageQueue:    make([]DamageInfo, 0),
		PendingManager: NewPendingManager(),
		HasEndedRound:  [2]bool{false, false},
	}
}

// GetCurrentSide 获取当前行动方
func (g *GameState) GetCurrentSide() *Side {
	if g.CurrentSide == 0 {
		return g.P0
	}
	return g.P1
}

// GetEnemySide 获取敌方
func (g *GameState) GetEnemySide() *Side {
	if g.CurrentSide == 0 {
		return g.P1
	}
	return g.P0
}

// GetSide 获取指定方 (0=P0, 1=P1)
func (g *GameState) GetSide(index int) *Side {
	if index == 0 {
		return g.P0
	}
	if index == 1 {
		return g.P1
	}
	return nil
}

// GetCharacter 获取角色
func (g *GameState) GetCharacter(sideIdx, charIdx int) *Character {
	side := g.GetSide(sideIdx)
	if side == nil {
		return nil
	}
	return side.GetCharacter(charIdx)
}

// DealDamage 造成伤害（加入队列）
func (g *GameState) DealDamage(dmg DamageInfo) {
	g.DamageQueue = append(g.DamageQueue, dmg)
}

// ProcessDamageQueue 处理伤害队列
func (g *GameState) ProcessDamageQueue() {
	for i := range g.DamageQueue {
		dmg := &g.DamageQueue[i]

		// 1. 触发 on_damage_calc Mod（来源方）
		if dmg.Source != nil {
			side := g.GetSide(dmg.Source.SideIndex)
			ctx := &ModContext{
				Game:       g,
				Side:       side,
				SourceChar: dmg.Source,
				TargetChar: dmg.Target,
				DamageInfo: dmg,
			}
			side.Mods.Trigger(EventDamageCalc, ctx)

			if ctx.Canceled {
				continue
			}
		}

		// 2. 触发 on_damage_receive Mod（目标方）
		if dmg.Target != nil {
			side := g.GetSide(dmg.Target.SideIndex)
			ctx := &ModContext{
				Game:       g,
				Side:       side,
				SourceChar: dmg.Source,
				TargetChar: dmg.Target,
				DamageInfo: dmg,
			}
			side.Mods.Trigger(EventDamageReceive, ctx)

			if ctx.Canceled {
				continue
			}
		}

		// 3. 应用最终伤害
		g.applyDamage(dmg)
	}

	// 清空队列
	g.DamageQueue = g.DamageQueue[:0]
}

// applyDamage 应用伤害
func (g *GameState) applyDamage(dmg *DamageInfo) {
	if dmg.Target == nil {
		return
	}

	dmg.Target.HP -= dmg.FinalAmount
	if dmg.Target.HP < 0 {
		dmg.Target.HP = 0
	}
}

// SkillScriptRuntime 技能脚本运行时接口
type SkillScriptRuntime interface {
	ExecuteSkillScript(script string, scriptName string) error
	CallSkillFunction(name string) error
}

// LoadCharacterData 加载角色数据到 GameState
func (g *GameState) LoadCharacterData(charID string) *CharacterData {
	// 检查是否已加载
	for i := 0; i < g.CharDataCount; i++ {
		if g.CharacterData[i] != nil && g.CharacterData[i].ID == charID {
			return g.CharacterData[i]
		}
	}
	
	// 加载新数据
	data, err := CharacterLoader.Load(charID)
	if err != nil {
		return nil
	}
	
	// 存储到数组
	if g.CharDataCount < len(g.CharacterData) {
		g.CharacterData[g.CharDataCount] = data
		g.CharDataCount++
	}
	
	return data
}

// GetCharacterData 获取已加载的角色数据
func (g *GameState) GetCharacterData(charID string) *CharacterData {
	for i := 0; i < g.CharDataCount; i++ {
		if g.CharacterData[i] != nil && g.CharacterData[i].ID == charID {
			return g.CharacterData[i]
		}
	}
	return nil
}

// StartBattle 战斗开始
func (g *GameState) StartBattle() error {
	// 初始化双方牌堆（30张碌碌无为）
	for _, side := range []*Side{g.P0, g.P1} {
		side.Deck.InitializeWithCard("wuluwuwei", 30)
		// 开局抽5张牌
		side.Deck.DrawToHand(5)
	}

	// 触发 battle_start Mod
	for _, side := range []*Side{g.P0, g.P1} {
		ctx := &ModContext{
			Game: g,
			Side: side,
		}
		side.Mods.Trigger(EventBattleStart, ctx)
	}

	// P0 开始第一回合
	g.startTurn(0)

	return nil
}

// startTurn 开始某玩家的回合
func (g *GameState) startTurn(sideIdx int) {
	g.CurrentSide = sideIdx
	side := g.GetSide(sideIdx)

	// 投掷8个骰子
	side.Dices.Clear()
	side.Dices.RollFull()

	// 创建骰子重投等待
	diceTypes := side.Dices.ToSlice()
	pending := g.PendingManager.CreateRerollPending(sideIdx, diceTypes)

	// 设置回调
	pending.OnResolve = func(result interface{}) error {
		if rerollResult, ok := result.(*RerollDiceResult); ok {
			side.Dices.Reroll(rerollResult.SelectedIndices)
		}
		// 重投后进入行动阶段，更新可选操作
		g.updateAvailableActions()
		return nil
	}

	// 触发回调
	if g.OnPendingCreate != nil {
		g.OnPendingCreate(pending)
	}
}

// EndRound 结束当前玩家的回合
func (g *GameState) EndRound() error {
	// 标记当前玩家已结束回合
	g.HasEndedRound[g.CurrentSide] = true

	// 执行回合结束处理
	side := g.GetCurrentSide()

	// 触发 end_phase Mod
	ctx := &ModContext{
		Game: g,
		Side: side,
	}
	side.Mods.Trigger(EventEndPhase, ctx)

	// 处理伤害队列
	g.ProcessDamageQueue()

	// 回合结束抽2张牌
	side.Deck.DrawToHand(2)

	// 清空骰子
	side.Dices.Clear()

	// 检查双方是否都已结束回合
	if g.HasEndedRound[0] && g.HasEndedRound[1] {
		// 进入下一回合
		g.nextRound()
	} else {
		// 切换到另一方
		otherSide := 1 - g.CurrentSide
		if !g.HasEndedRound[otherSide] {
			// 对方还没结束，切换到对方
			g.CurrentSide = otherSide
			g.startTurn(otherSide)
		}
		// 如果对方已结束，当前玩家继续等待（但这种情况不应该发生）
	}

	return nil
}

// nextRound 进入下一回合
func (g *GameState) nextRound() {
	// 触发 round_end
	for _, side := range []*Side{g.P0, g.P1} {
		ctx := &ModContext{
			Game: g,
			Side: side,
		}
		side.Mods.Trigger(EventRoundEnd, ctx)
	}

	// 增加回合数
	g.Round++

	// 重置结束标记
	g.HasEndedRound = [2]bool{false, false}

	// 决定谁先手：上回合先结束的玩家下回合后手
	// 简化逻辑：P0 总是先手（可以根据需要添加更复杂的逻辑）
	g.startTurn(0)
}

// updateAvailableActions 更新当前可选操作列表
func (g *GameState) updateAvailableActions() {
	if !g.PendingManager.IsPending() {
		return
	}

	pending := g.PendingManager.Current
	side := g.GetCurrentSide()
	activeChar := side.GetActiveCharacter()

	actions := make([]AvailableAction, 0)

	// 1. 使用技能选项（从已加载的数据获取）
	if activeChar != nil {
		charData := g.GetCharacterData(activeChar.ID)
		if charData != nil {
			for _, skill := range charData.Skills {
				canUse := side.Dices.CanAffordCost(skill.Cost.ToCost())

				// 元素爆发需要检查能量
				if skill.Type == SkillElementalBurst {
					if activeChar.Energy < activeChar.MaxEnergy {
						canUse = false
					}
				}

				actions = append(actions, AvailableAction{
					Type:    ActionUseSkill,
					SkillID: skill.ID,
					Cost:    skill.Cost.ToCost(),
					CanUse:  canUse,
				})
			}
		}
	}

	// 2. 切换角色选项 (1个任意元素骰)
	for i, char := range side.Characters {
		if char != nil && char.IsAlive() && i != side.ActiveIdx {
			actions = append(actions, AvailableAction{
				Type:      ActionSwitchChar,
				CharIndex: i,
				Cost:      Cost{Any: 1},
				CanUse:    side.Dices.CanAffordCost(Cost{Any: 1}),
			})
		}
	}

	// 3. 打出手牌选项
	for cardIdx, cardID := range side.Hand {
		cardDef, ok := GlobalCardLoader.Get(cardID)
		if ok {
			cost := cardDef.ToCost()
			canUse := side.Dices.CanAffordCost(cost)
			actions = append(actions, AvailableAction{
				Type:      ActionPlayCard,
				CardIndex: cardIdx,
				Cost:      cost,
				CanUse:    canUse,
			})
		}
	}

	// 4. 元素调和选项（无次数限制）
	if activeChar != nil {
		activeElement := activeChar.Element
		for i, dice := range side.Dices.Dices {
			// 只能调和非出战元素、非万能的骰子
			if dice.Type != ElementToDice(activeElement) && dice.Type != DiceOmni {
				// 检查有手牌可以调和
				for cardIdx := range side.Hand {
					actions = append(actions, AvailableAction{
						Type:      ActionElementalTuning,
						CardIndex: cardIdx,
						DiceIndex: i,
						CanUse:    true,
					})
				}
			}
		}
	}

	// 4. 结束回合
	actions = append(actions, AvailableAction{
		Type:   ActionEndRound,
		CanUse: true,
	})

	// 保存到 pending 数据
	pending.AvailableActions = actions
}

// UpdatePendingActions 更新当前可选操作列表（导出供测试使用）
func (g *GameState) UpdatePendingActions() {
	g.updateAvailableActions()
}

// ConvertDice 调和骰子
func (g *GameState) ConvertDice(sideIdx, cardIndex, diceIndex int) bool {
	side := g.GetSide(sideIdx)

	if cardIndex < 0 || cardIndex >= len(side.Hand) {
		return false
	}
	if diceIndex < 0 || diceIndex >= side.Dices.GetTotal() {
		return false
	}

	activeChar := side.GetActiveCharacter()
	if activeChar == nil {
		return false
	}
	activeElement := activeChar.Element

	dice := side.Dices.Dices[diceIndex]

	if dice.Type == ElementToDice(activeElement) {
		return false
	}
	if dice.Type == DiceOmni {
		return false
	}

	side.RemoveCard(cardIndex)
	side.Dices.Dices[diceIndex].Type = ElementToDice(activeElement)

	// 更新可选操作
	g.updateAvailableActions()

	return true
}

// SwitchCharacter 切换角色
func (g *GameState) SwitchCharacter(charIdx int) bool {
	side := g.GetCurrentSide()

	if !side.SwitchCharacter(charIdx) {
		return false
	}

	// 消耗1个任意骰子
	if side.Dices.GetTotal() < 1 {
		return false
	}
	// 移除第一个骰子（简化处理）
	side.Dices.Dices = side.Dices.Dices[1:]

	// 更新可选操作
	g.updateAvailableActions()

	return true
}

// SkillRuntime 技能运行时接口
type SkillRuntime interface {
	ExecuteSkillScript(script string, scriptName string) error
	CallSkillFunction(name string) error
}

// CardRuntime 卡牌运行时接口
type CardRuntime interface {
	CallCardFunction(funcName string) error
}

// ExecuteSkill 执行技能（自动检查费用并调用 Lua 函数）
func (g *GameState) ExecuteSkill(charIdx int, skillID string, runtime SkillRuntime) error {
	side := g.GetCurrentSide()
	char := side.GetCharacter(charIdx)

	if char == nil {
		return fmt.Errorf("character not found: %d/%d", g.CurrentSide, charIdx)
	}

	// 获取已加载的角色数据
	charData := g.GetCharacterData(char.ID)
	if charData == nil {
		return fmt.Errorf("character data not loaded: %s", char.ID)
	}

	skillDef := charData.GetSkill(skillID)
	if skillDef == nil {
		return fmt.Errorf("skill not found: %s", skillID)
	}

	// 检查费用
	cost := skillDef.Cost.ToCost()
	if !side.Dices.CanAffordCost(cost) {
		return fmt.Errorf("not enough dice for skill %s", skillID)
	}

	// 消耗骰子
	if !side.Dices.ConsumeCost(cost) {
		return fmt.Errorf("failed to consume dice for skill %s", skillID)
	}

	// 新架构：加载并执行技能脚本
	if runtime != nil && skillDef.Script != "" {
		// 获取角色目录路径
		dirPath, ok := CharacterLoader.GetDirPath(char.ID)
		if ok {
			scriptPath := filepath.Join(dirPath, skillDef.Script)
			scriptContent, err := os.ReadFile(scriptPath)
			if err == nil {
				// 执行技能脚本（定义 on_xxx 函数）
				runtime.ExecuteSkillScript(string(scriptContent), skillDef.Script)
				
				// 调用技能函数
				funcName := "on_" + skillID
				if err := runtime.CallSkillFunction(funcName); err != nil {
					return fmt.Errorf("skill effect failed: %w", err)
				}
			}
		}
	}

	// 处理伤害队列
	g.ProcessDamageQueue()

	// 更新可选操作
	g.updateAvailableActions()

	return nil
}

// PlayCard 打出卡牌（自动检查费用并调用 Lua 函数）
func (g *GameState) PlayCard(cardIndex int, runtime interface {
	ExecuteCardScript(script string) error
	CallCardFunction(name string) error
}) error {
	side := g.GetCurrentSide()

	if cardIndex < 0 || cardIndex >= len(side.Hand) {
		return fmt.Errorf("invalid card index: %d", cardIndex)
	}

	cardID := side.Hand[cardIndex]
	cardDef, ok := GlobalCardLoader.Get(cardID)
	if !ok {
		return fmt.Errorf("card not found: %s", cardID)
	}

	// 检查费用
	cost := cardDef.ToCost()
	if !side.Dices.CanAffordCost(cost) {
		return fmt.Errorf("not enough dice for card %s", cardID)
	}

	// 消耗骰子
	if !side.Dices.ConsumeCost(cost) {
		return fmt.Errorf("failed to consume dice for card %s", cardID)
	}

	// 从手牌移除（并加入弃牌堆）
	side.Deck.DiscardFromHand(cardIndex)

	// 加载并执行卡牌脚本（如果卡牌有脚本）
	if runtime != nil && cardDef.Script != "" {
		// 读取行动卡脚本（从子目录加载）
		scriptPath := filepath.Join(GetDataDir(), "action", cardDef.Script, "action.lua")
		scriptContent, err := os.ReadFile(scriptPath)
		if err == nil {
			// 执行脚本，定义卡牌效果函数
			runtime.ExecuteCardScript(string(scriptContent))
			
			// 调用 on_play 函数
			if err := runtime.CallCardFunction("on_play"); err != nil {
				return fmt.Errorf("card effect failed: %w", err)
			}
		}
	}

	// 处理伤害队列
	g.ProcessDamageQueue()

	// 更新可选操作
	g.updateAvailableActions()

	return nil
}

// IsGameOver 检查游戏是否结束
func (g *GameState) IsGameOver() (bool, int) {
	for i, side := range []*Side{g.P0, g.P1} {
		hasAlive := false
		for _, c := range side.Characters {
			if c != nil && c.IsAlive() {
				hasAlive = true
				break
			}
		}
		if !hasAlive {
			return true, 1 - i // 返回胜者 (0 或 1)
		}
	}
	return false, -1
}
