// core/card.go
package core

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/BurntSushi/toml"
)

// CardType 卡牌类型
type CardType string

const (
	CardTypeEvent      CardType = "Event"      // 事件卡
	CardTypeSupport    CardType = "Support"    // 支援卡
	CardTypeEquipment  CardType = "Equipment"  // 装备卡
)

// CardDefinition 卡牌定义
type CardDefinition struct {
	ID          string     `toml:"id"`
	Name        string     `toml:"name"`
	Type        CardType   `toml:"type"`
	Description string     `toml:"description"`
	Cost        []CostDef  `toml:"cost"`
	Script      string     `toml:"script,omitempty"` // Lua脚本名称（可选）
}

// CostDef 费用定义（用于TOML解析）
type CostDef struct {
	Type  string `toml:"type"`
	Count int    `toml:"count"`
}

// ToCost 转换为Cost结构
func (cd *CardDefinition) ToCost() Cost {
	cost := Cost{Elements: make(map[Element]int)}
	for _, c := range cd.Cost {
		switch c.Type {
		case "Any":
			cost.Any += c.Count
		case "Omni":
			// 万能骰子可以当作任意元素，在费用中视为任意骰
			cost.Any += c.Count
		case "Pyro":
			cost.Elements[Pyro] += c.Count
		case "Hydro":
			cost.Elements[Hydro] += c.Count
		case "Cryo":
			cost.Elements[Cryo] += c.Count
		case "Electro":
			cost.Elements[Electro] += c.Count
		case "Anemo":
			cost.Elements[Anemo] += c.Count
		case "Geo":
			cost.Elements[Geo] += c.Count
		case "Dendro":
			cost.Elements[Dendro] += c.Count
		}
	}
	return cost
}

// CardDataLoader 卡牌数据加载器
type CardDataLoader struct {
	BasePath string
	Cards    map[string]*CardDefinition
}

// NewCardDataLoader 创建卡牌加载器
func NewCardDataLoader(basePath string) *CardDataLoader {
	loader := &CardDataLoader{
		BasePath: basePath,
		Cards:    make(map[string]*CardDefinition),
	}
	// 初始化时扫描所有行动卡目录
	loader.scanCardDirs()
	return loader
}

// scanCardDirs 扫描行动卡目录
func (cl *CardDataLoader) scanCardDirs() {
	entries, err := os.ReadDir(cl.BasePath)
	if err != nil {
		return
	}
	
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		
		dirName := entry.Name()
		dirPath := filepath.Join(cl.BasePath, dirName)
		
		// 查找目录中的 action.toml 文件
		dirEntries, err := os.ReadDir(dirPath)
		if err != nil {
			continue
		}
		
		var tomlPath string
		for _, file := range dirEntries {
			if !file.IsDir() && file.Name() == "action.toml" {
				tomlPath = filepath.Join(dirPath, file.Name())
				break
			}
		}
		
		if tomlPath == "" {
			continue
		}
		
		// 读取并解析 TOML
		data, err := os.ReadFile(tomlPath)
		if err != nil {
			continue
		}
		
		var cardDef CardDefinition
		if err := toml.Unmarshal(data, &cardDef); err != nil {
			continue
		}
		
		if cardDef.ID != "" {
			cl.Cards[cardDef.ID] = &cardDef
		}
	}
}

// Load 加载单个卡牌定义（从子目录）
func (cl *CardDataLoader) Load(cardID string) (*CardDefinition, error) {
	// 检查缓存
	if card, ok := cl.Cards[cardID]; ok {
		return card, nil
	}

	// 查找子目录中的 action.toml
	tomlPath := filepath.Join(cl.BasePath, cardID, "action.toml")
	data, err := os.ReadFile(tomlPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read card TOML: %w", err)
	}

	// 解析TOML
	var cardDef CardDefinition
	if err := toml.Unmarshal(data, &cardDef); err != nil {
		return nil, fmt.Errorf("failed to unmarshal card TOML: %w", err)
	}

	// 缓存
	cl.Cards[cardID] = &cardDef
	return &cardDef, nil
}

// Get 获取已加载的卡牌定义
func (cl *CardDataLoader) Get(cardID string) (*CardDefinition, bool) {
	card, ok := cl.Cards[cardID]
	return card, ok
}

// GlobalCardLoader 全局行动卡加载器
var GlobalCardLoader *CardDataLoader

func init() {
	// 使用绝对路径
	GlobalCardLoader = NewCardDataLoader("/home/redcontritio/gicg_sim/data/action")
}
