// core/pending.go
package core

import (
	"fmt"
)

// PendingType 等待类型
type PendingType string

const (
	PendingNone          PendingType = ""              // 无等待
	PendingRerollDice    PendingType = "reroll_dice"   // 等待选择骰子重投
	PendingSelectTarget  PendingType = "select_target" // 等待选择目标
	PendingSelectCards   PendingType = "select_cards"  // 等待选择卡牌
	PendingSelectAction  PendingType = "select_action" // 等待选择行动
)

// PendingState 等待状态
type PendingState struct {
	Type             PendingType       // 等待类型
	SideIdx          int               // 等待哪一方
	Message          string            // 提示信息
	Data             interface{}       // 附加数据
	Resolved         bool              // 是否已解决
	Result           interface{}       // 玩家操作结果
	OnResolve        func(result interface{}) error  // 解决后的回调
	AvailableActions []AvailableAction // 可选操作列表
}

// PendingManager 等待管理器
type PendingManager struct {
	Current   *PendingState  // 当前等待状态
	History   []*PendingState // 历史记录
}

// NewPendingManager 创建等待管理器
func NewPendingManager() *PendingManager {
	return &PendingManager{
		Current: nil,
		History: make([]*PendingState, 0),
	}
}

// IsPending 是否有等待中的操作
func (pm *PendingManager) IsPending() bool {
	return pm.Current != nil && !pm.Current.Resolved
}

// GetPendingSide 获取当前等待的方
func (pm *PendingManager) GetPendingSide() int {
	if pm.Current == nil {
		return -1
	}
	return pm.Current.SideIdx
}

// CreatePending 创建新的等待状态
func (pm *PendingManager) CreatePending(pendingType PendingType, sideIdx int, message string, data interface{}) *PendingState {
	// 如果有未解决的等待，先保存到历史
	if pm.Current != nil && !pm.Current.Resolved {
		pm.History = append(pm.History, pm.Current)
	}
	
	pm.Current = &PendingState{
		Type:     pendingType,
		SideIdx:  sideIdx,
		Message:  message,
		Data:     data,
		Resolved: false,
	}
	
	return pm.Current
}

// Resolve 解决当前等待
func (pm *PendingManager) Resolve(result interface{}) error {
	if pm.Current == nil {
		return fmt.Errorf("no pending state")
	}
	
	if pm.Current.Resolved {
		return fmt.Errorf("pending already resolved")
	}
	
	pm.Current.Resolved = true
	pm.Current.Result = result
	
	// 调用回调
	if pm.Current.OnResolve != nil {
		if err := pm.Current.OnResolve(result); err != nil {
			return err
		}
	}
	
	// 保存到历史
	pm.History = append(pm.History, pm.Current)
	pm.Current = nil
	
	return nil
}

// Cancel 取消当前等待
func (pm *PendingManager) Cancel() {
	if pm.Current != nil {
		pm.Current.Resolved = true
		pm.History = append(pm.History, pm.Current)
		pm.Current = nil
	}
}

// RerollDiceData 重投骰子数据
type RerollDiceData struct {
	DiceTypes []int  // 当前骰子类型列表
	MaxSelect int    // 最多可选择几个重投（通常 0-8）
}

// RerollDiceResult 重投骰子结果
type RerollDiceResult struct {
	SelectedIndices []int  // 选择重投的骰子索引
}

// ConvertDiceData 调和骰子数据
type ConvertDiceData struct {
	HandCards   []string  // 手牌列表
	DiceTypes   []int     // 当前骰子类型列表
	ActiveElement Element // 出战角色元素
}

// ConvertDiceResult 调和骰子结果
type ConvertDiceResult struct {
	CardIndex   int  // 选择的手牌索引
	DiceIndex   int  // 选择的骰子索引
}

// CreateRerollPending 创建骰子重投等待
func (pm *PendingManager) CreateRerollPending(sideIdx int, diceTypes []int) *PendingState {
	data := &RerollDiceData{
		DiceTypes: diceTypes,
		MaxSelect: len(diceTypes),
	}
	
	return pm.CreatePending(PendingRerollDice, sideIdx, "请选择要重新投掷的骰子", data)
}

// CreateConvertPending 创建调和等待
func (pm *PendingManager) CreateConvertPending(sideIdx int, handCards []string, diceTypes []int, activeElement Element) *PendingState {
	data := &ConvertDiceData{
		HandCards:     handCards,
		DiceTypes:     diceTypes,
		ActiveElement: activeElement,
	}
	
	return pm.CreatePending(PendingSelectCards, sideIdx, "请选择一张手牌和一个非元素/非万能骰子进行调和", data)
}
