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

// Character 角色
type Character struct {
	ID        string
	Name      string
	HP        int
	MaxHP     int
	Energy    int
	MaxEnergy int
	Element   Element
	
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
