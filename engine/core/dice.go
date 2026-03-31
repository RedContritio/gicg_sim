// core/dice.go
package core

import (
	"math/rand"
)

// DiceType 骰子类型
type DiceType int

const (
	DicePyro DiceType = iota   // 火
	DiceHydro                  // 水
	DiceCryo                   // 冰
	DiceElectro                // 雷
	DiceAnemo                  // 风
	DiceGeo                    // 岩
	DiceDendro                 // 草
	DiceOmni                   // 万能
	DiceTypeCount
)

// String 返回骰子类型名称
func (d DiceType) String() string {
	names := []string{"火", "水", "冰", "雷", "风", "岩", "草", "万能"}
	if int(d) < len(names) {
		return names[d]
	}
	return "未知"
}

// ToElement 骰子类型转元素类型
func (d DiceType) ToElement() Element {
	switch d {
	case DicePyro:
		return Pyro
	case DiceHydro:
		return Hydro
	case DiceCryo:
		return Cryo
	case DiceElectro:
		return Electro
	case DiceAnemo:
		return Anemo
	case DiceGeo:
		return Geo
	case DiceDendro:
		return Dendro
	default:
		return Physical // Omni 和无效值映射到 Physical
	}
}

// ElementToDice 元素类型转骰子类型
func ElementToDice(e Element) DiceType {
	switch e {
	case Pyro:
		return DicePyro
	case Hydro:
		return DiceHydro
	case Cryo:
		return DiceCryo
	case Electro:
		return DiceElectro
	case Anemo:
		return DiceAnemo
	case Geo:
		return DiceGeo
	case Dendro:
		return DiceDendro
	default:
		return DiceOmni
	}
}

// Dice 骰子
type Dice struct {
	Type DiceType
}

// DiceManager 骰子管理器
type DiceManager struct {
	Dices     []*Dice   // 当前骰子
	MaxDices  int       // 最大骰子数（通常是8）
	side      *Side     // 所属方
}

// NewDiceManager 创建骰子管理器
func NewDiceManager(side *Side) *DiceManager {
	return &DiceManager{
		Dices:    make([]*Dice, 0, 8),
		MaxDices: 8,
		side:     side,
	}
}

// Roll 投掷指定数量的骰子
func (dm *DiceManager) Roll(count int) {
	for i := 0; i < count; i++ {
		if len(dm.Dices) >= dm.MaxDices {
			break
		}
		// 随机生成骰子（8种类型）
		diceType := DiceType(rand.Intn(int(DiceTypeCount)))
		dm.Dices = append(dm.Dices, &Dice{Type: diceType})
	}
}

// RollFull 投满骰子
func (dm *DiceManager) RollFull() {
	need := dm.MaxDices - len(dm.Dices)
	if need > 0 {
		dm.Roll(need)
	}
}

// Clear 清空骰子
func (dm *DiceManager) Clear() {
	dm.Dices = dm.Dices[:0]
}

// SetDice 设置指定类型的骰子数量（先清空，再设置）
// 返回实际设置的数量（受限于 MaxDices）
func (dm *DiceManager) SetDice(diceType DiceType, count int) int {
	dm.Clear()
	
	if count > dm.MaxDices {
		count = dm.MaxDices
	}
	if count < 0 {
		count = 0
	}
	
	for i := 0; i < count; i++ {
		dm.Dices = append(dm.Dices, &Dice{Type: diceType})
	}
	
	return count
}

// GetCount 获取指定类型骰子的数量
func (dm *DiceManager) GetCount(diceType DiceType) int {
	count := 0
	for _, d := range dm.Dices {
		if d.Type == diceType {
			count++
		}
	}
	return count
}

// GetTotal 获取骰子总数
func (dm *DiceManager) GetTotal() int {
	return len(dm.Dices)
}

// Consume 消耗指定类型和数量的骰子
// 优先消耗指定类型，如果是出战角色元素，也可以消耗万能骰子
func (dm *DiceManager) Consume(diceType DiceType, count int) bool {
	if count <= 0 {
		return true
	}
	
	available := dm.GetCount(diceType)
	
	// 如果需要消耗的超过拥有的，检查是否有万能骰子补充
	if available < count {
		omniCount := dm.GetCount(DiceOmni)
		if available+omniCount < count {
			return false // 骰子不足
		}
		
		// 先消耗指定类型
		needOmni := count - available
		dm.removeDice(diceType, available)
		dm.removeDice(DiceOmni, needOmni)
	} else {
		dm.removeDice(diceType, count)
	}
	
	return true
}

// ConsumeElement 消耗指定元素的骰子（自动匹配角色元素）
func (dm *DiceManager) ConsumeElement(element Element, count int) bool {
	diceType := ElementToDice(element)
	return dm.Consume(diceType, count)
}

// removeDice 从列表中移除指定数量的某种骰子
func (dm *DiceManager) removeDice(diceType DiceType, count int) {
	removed := 0
	newDices := make([]*Dice, 0, len(dm.Dices))
	
	for _, d := range dm.Dices {
		if removed < count && d.Type == diceType {
			removed++
			continue
		}
		newDices = append(newDices, d)
	}
	
	dm.Dices = newDices
}

// Reroll 重新投掷指定索引的骰子
func (dm *DiceManager) Reroll(indices []int) {
	for _, idx := range indices {
		if idx >= 0 && idx < len(dm.Dices) {
			// 重新随机生成
			dm.Dices[idx].Type = DiceType(rand.Intn(int(DiceTypeCount)))
		}
	}
}

// Convert 调和：将一个骰子转换为指定类型
// 被调和的骰子不能是出战角色元素，也不能是万能
func (dm *DiceManager) Convert(diceIndex int, targetType DiceType, activeElement Element) bool {
	if diceIndex < 0 || diceIndex >= len(dm.Dices) {
		return false
	}
	
	dice := dm.Dices[diceIndex]
	
	// 不能调和出战角色的元素骰
	if dice.Type == ElementToDice(activeElement) {
		return false
	}
	
	// 不能调和万能骰
	if dice.Type == DiceOmni {
		return false
	}
	
	// 执行调和
	dice.Type = targetType
	return true
}

// ToSlice 返回骰子类型的切片（用于 Lua API）
func (dm *DiceManager) ToSlice() []int {
	result := make([]int, len(dm.Dices))
	for i, d := range dm.Dices {
		result[i] = int(d.Type)
	}
	return result
}

// Cost 技能费用
type Cost struct {
	Elements map[Element]int // 指定元素骰：元素 -> 数量
	Any      int             // 任意骰数量（可用任何非万能骰）
}

// CanAffordCost 检查是否能支付费用（支持自动填充）
// 自动填充规则：
// 1. 指定元素优先用对应元素骰，不足用万能补充
// 2. 任意骰可用剩余的任何非万能骰（包括非出战元素）
// 3. 如果任意骰还不够，用万能补充
func (dm *DiceManager) CanAffordCost(cost Cost) bool {
	// 统计当前骰子
	counts := make(map[DiceType]int)
	for _, d := range dm.Dices {
		counts[d.Type]++
	}
	
	omniCount := counts[DiceOmni]
	
	// 1. 处理指定元素需求
	for element, need := range cost.Elements {
		diceType := ElementToDice(element)
		available := counts[diceType]
		
		if available >= need {
			// 足够，消耗对应元素
			counts[diceType] -= need
		} else {
			// 不够，需要万能补充
			needOmni := need - available
			if omniCount < needOmni {
				return false // 万能也不够了
			}
			omniCount -= needOmni
			counts[diceType] = 0
		}
	}
	
	// 2. 处理任意骰需求
	anyNeed := cost.Any
	
	// 先统计剩余的非万能骰总数
	remainingNonOmni := 0
	for diceType, count := range counts {
		if diceType != DiceOmni {
			remainingNonOmni += count
		}
	}
	
	// 用剩余骰子填充任意需求
	if remainingNonOmni >= anyNeed {
		// 足够
		return true
	}
	
	// 不够，需要用万能补充
	anyNeed -= remainingNonOmni
	if omniCount >= anyNeed {
		return true
	}
	
	return false
}

// ConsumeCost 消耗指定费用
func (dm *DiceManager) ConsumeCost(cost Cost) bool {
	if !dm.CanAffordCost(cost) {
		return false
	}
	
	// 按指定元素消耗
	for element, need := range cost.Elements {
		dm.Consume(ElementToDice(element), need)
	}
	
	// 消耗任意骰（简化处理：优先消耗非万能的非出战元素，然后万能）
	anyNeed := cost.Any
	for i := 0; i < len(dm.Dices) && anyNeed > 0; i++ {
		if dm.Dices[i].Type != DiceOmni {
			dm.Dices = append(dm.Dices[:i], dm.Dices[i+1:]...)
			i--
			anyNeed--
		}
	}
	// 如果还有剩余，用万能补充
	if anyNeed > 0 {
		dm.Consume(DiceOmni, anyNeed)
	}
	
	return true
}

// CanAfford 检查是否有足够的骰子支付费用
// cost 是费用映射：元素 -> 数量
func (dm *DiceManager) CanAfford(cost map[Element]int) bool {
	// 计算可用资源
	available := make(map[Element]int)
	omniCount := dm.GetCount(DiceOmni)
	
	for e := Pyro; e < ElementCount; e++ {
		available[e] = dm.GetCount(ElementToDice(e))
	}
	
	// 先匹配精确元素
	shortfall := 0
	for element, need := range cost {
		if available[element] < need {
			shortfall += need - available[element]
		}
	}
	
	// 不足部分用万能骰补充
	return omniCount >= shortfall
}

// ConsumeElementCost 消耗指定费用的骰子
// cost 是费用映射：元素 -> 数量
func (dm *DiceManager) ConsumeElementCost(cost map[Element]int) bool {
	if !dm.CanAfford(cost) {
		return false
	}
	
	// 先消耗精确匹配的元素骰
	remainingOmniNeed := 0
	for element, need := range cost {
		available := dm.GetCount(ElementToDice(element))
		if available >= need {
			dm.removeDice(ElementToDice(element), need)
		} else {
			// 不够的部分用万能骰
			dm.removeDice(ElementToDice(element), available)
			remainingOmniNeed += need - available
		}
	}
	
	// 消耗万能骰补充不足
	if remainingOmniNeed > 0 {
		dm.removeDice(DiceOmni, remainingOmniNeed)
	}
	
	return true
}
