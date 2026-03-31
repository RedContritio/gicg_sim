// core/side.go
package core

// Side 一方玩家
type Side struct {
	Index      int
	Characters [3]*Character
	ActiveIdx  int
	
	Counters       *CounterManager
	ScopedCounters *ScopedCounterManager  // 带作用域的计数器
	Mods           *ModManager
	Dices          *DiceManager  // 骰子管理器
	Deck           *Deck         // 牌堆管理器
	
	// 手牌
	Hand       []string  // 手牌列表（卡牌ID）
	MaxHand    int       // 最大手牌数
}

// NewSide 创建 Side
func NewSide(index int) *Side {
	side := &Side{
		Index:      index,
		Characters: [3]*Character{},
		ActiveIdx:  0,
		Hand:       make([]string, 0, 10),
		MaxHand:    10,
	}
	
	side.Counters = NewCounterManager(side)
	side.ScopedCounters = NewScopedCounterManager()
	side.Mods = NewModManager(side)
	side.Dices = NewDiceManager(side)
	side.Deck = NewDeck(side)
	
	return side
}

// AddCard 添加手牌
func (s *Side) AddCard(cardID string) bool {
	if len(s.Hand) >= s.MaxHand {
		return false // 手牌已满
	}
	s.Hand = append(s.Hand, cardID)
	return true
}

// RemoveCard 移除手牌
func (s *Side) RemoveCard(index int) string {
	if index < 0 || index >= len(s.Hand) {
		return ""
	}
	cardID := s.Hand[index]
	s.Hand = append(s.Hand[:index], s.Hand[index+1:]...)
	return cardID
}

// GetHandSize 获取手牌数
func (s *Side) GetHandSize() int {
	return len(s.Hand)
}

// GetActiveCharacter 获取当前出战角色
func (s *Side) GetActiveCharacter() *Character {
	return s.Characters[s.ActiveIdx]
}

// GetCharacter 获取指定角色
func (s *Side) GetCharacter(idx int) *Character {
	if idx < 0 || idx >= 3 {
		return nil
	}
	return s.Characters[idx]
}

// LoadCharacter 加载角色
func (s *Side) LoadCharacter(idx int, char *Character) {
	if idx >= 0 && idx < 3 {
		s.Characters[idx] = char
		char.SideIndex = s.Index
		char.CharIndex = idx
	}
}

// SwitchCharacter 切换角色
func (s *Side) SwitchCharacter(idx int) bool {
	if idx < 0 || idx >= 3 {
		return false
	}
	if s.Characters[idx] == nil || !s.Characters[idx].IsAlive() {
		return false
	}
	s.ActiveIdx = idx
	return true
}

// GetAliveCharacters 获取所有存活角色
func (s *Side) GetAliveCharacters() []*Character {
	var result []*Character
	for _, c := range s.Characters {
		if c != nil && c.IsAlive() {
			result = append(result, c)
		}
	}
	return result
}

// GetFrontCharacters 获取前台角色
func (s *Side) GetFrontCharacter() *Character {
	return s.GetActiveCharacter()
}

// GetBackCharacters 获取后台角色
func (s *Side) GetBackCharacters() []*Character {
	var result []*Character
	for i, c := range s.Characters {
		if i != s.ActiveIdx && c != nil && c.IsAlive() {
			result = append(result, c)
		}
	}
	return result
}

// GetOppositeSide 获取对手索引
func (s *Side) GetOppositeSide() int {
	return 1 - s.Index
}
