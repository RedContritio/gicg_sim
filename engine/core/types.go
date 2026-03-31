// core/types.go
package core

// Element 元素类型
type Element int

const (
	Pyro Element = iota
	Hydro
	Cryo
	Electro
	Anemo
	Geo
	Dendro
	Physical
	Piercing
	ElementCount
)

func (e Element) String() string {
	names := []string{"Pyro", "Hydro", "Cryo", "Electro", "Anemo", "Geo", "Dendro", "Physical", "Piercing"}
	if int(e) < len(names) {
		return names[e]
	}
	return "Unknown"
}

// Target 目标类型
type Target int

const (
	TargetNone Target = iota
	TargetSelf
	TargetActiveEnemy
	TargetAllEnemies
	TargetBackEnemies
	TargetAllAllies
)

// Aura 元素附着
type Aura struct {
	Element   Element
	Duration  int  // 剩余回合数（某些附着会衰减）
}

// Character 角色
type Character struct {
	ID        string
	Name      string
	HP        int
	MaxHP     int
	Energy    int
	MaxEnergy int
	Element   Element
	
	// 元素附着（可以有多重附着，如冻元素+水元素）
	Auras []Aura
	
	// 索引信息
	SideIndex int // 0 或 1
	CharIndex int // 0, 1, 2
}

// NewCharacter 创建角色
func NewCharacter(id, name string, maxHP, maxEnergy int, element Element) *Character {
	return &Character{
		ID:        id,
		Name:      name,
		HP:        maxHP,
		MaxHP:     maxHP,
		Energy:    0,
		MaxEnergy: maxEnergy,
		Element:   element,
	}
}

// IsAlive 是否存活
func (c *Character) IsAlive() bool {
	return c.HP > 0
}

// HasAura 检查是否有指定元素附着
func (c *Character) HasAura(element Element) bool {
	for _, aura := range c.Auras {
		if aura.Element == element {
			return true
		}
	}
	return false
}

// AddAura 添加元素附着
func (c *Character) AddAura(element Element, duration int) {
	// 检查是否已有同元素附着，更新持续时间
	for i := range c.Auras {
		if c.Auras[i].Element == element {
			c.Auras[i].Duration = duration
			return
		}
	}
	// 添加新附着
	c.Auras = append(c.Auras, Aura{Element: element, Duration: duration})
}

// RemoveAura 移除指定元素附着
func (c *Character) RemoveAura(element Element) {
	var newAuras []Aura
	for _, aura := range c.Auras {
		if aura.Element != element {
			newAuras = append(newAuras, aura)
		}
	}
	c.Auras = newAuras
}

// ClearAuras 清除所有附着
func (c *Character) ClearAuras() {
	c.Auras = nil
}

// DamageInfo 伤害信息
type DamageInfo struct {
	Amount     int
	Element    Element
	Source     *Character
	Target     *Character
	IsPiercing bool
	
	// 可被 Mod 修改
	FinalAmount   int
	FinalElement  Element
}

// NewDamageInfo 创建伤害信息
func NewDamageInfo(amount int, element Element, source, target *Character) *DamageInfo {
	return &DamageInfo{
		Amount:       amount,
		Element:      element,
		Source:       source,
		Target:       target,
		FinalAmount:  amount,
		FinalElement: element,
	}
}
