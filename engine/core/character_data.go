// core/character_data.go
package core

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/BurntSushi/toml"
)

// SkillType 技能类型
type SkillType string

const (
	SkillNormalAttack   SkillType = "NormalAttack"
	SkillElementalSkill SkillType = "ElementalSkill"
	SkillElementalBurst SkillType = "ElementalBurst"
)

// CostItem 费用项（TOML 结构）
type CostItem struct {
	Type  string `toml:"type"`  // "Any", "Pyro", "Hydro", "Electro"...
	Count int    `toml:"count"`
}

// SkillCost 技能消耗（TOML 结构）- 列表形式
type SkillCost []CostItem

// ToCost 转换为引擎的 Cost 类型
func (sc SkillCost) ToCost() Cost {
	cost := Cost{
		Elements: make(map[Element]int),
		Any:      0,
	}

	for _, item := range sc {
		if strings.EqualFold(item.Type, "Any") {
			cost.Any += item.Count
		} else {
			elem := ParseElement(item.Type)
			if elem != ElementCount { // 有效元素
				cost.Elements[elem] += item.Count
			}
		}
	}

	return cost
}

// SkillDef 技能定义（TOML 结构）
type SkillDef struct {
	ID     string    `toml:"id"`
	Name   string    `toml:"name"`
	Type   SkillType `toml:"type"`
	Script string    `toml:"script"` // Lua 脚本名称
	Cost   SkillCost `toml:"cost"`
}

// CharacterData 角色数据（TOML 结构）
type CharacterData struct {
	ID        string     `toml:"id"`
	Name      string     `toml:"name"`
	MaxHP     int        `toml:"max_hp"`
	MaxEnergy int        `toml:"max_energy"`
	Element   string     `toml:"element"`
	Skills    []SkillDef `toml:"skills"`
	
	// 运行时填充
	DirPath string `toml:"-"` // 角色数据所在目录（如 "阿蕾奇诺"）
}

// CharacterDataLoader 角色数据加载器
type CharacterDataLoader struct {
	dataDir       string
	cache         map[string]*CharacterData
	idToDirMap    map[string]string  // ID -> 目录名映射
	idToPathMap   map[string]string  // ID -> 完整目录路径映射
}

// NewCharacterDataLoader 创建加载器
// 默认从项目根目录的 data/characters 加载
func NewCharacterDataLoader(dataDir string) *CharacterDataLoader {
	if dataDir == "" {
		// 默认路径：项目根目录/data
		dataDir = "/home/redcontritio/gicg_sim/data"
	}
	loader := &CharacterDataLoader{
		dataDir:     dataDir,
		cache:       make(map[string]*CharacterData),
		idToDirMap:  make(map[string]string),
		idToPathMap: make(map[string]string),
	}
	// 初始化时扫描所有角色目录
	loader.scanCharacterDirs()
	return loader
}

// scanCharacterDirs 扫描角色目录，建立 ID 到目录的映射
func (loader *CharacterDataLoader) scanCharacterDirs() {
	charsDir := filepath.Join(loader.dataDir, "characters")
	
	entries, err := os.ReadDir(charsDir)
	if err != nil {
		fmt.Printf("Warning: failed to read characters directory: %v\n", err)
		return
	}
	
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		
		dirName := entry.Name()
		dirPath := filepath.Join(charsDir, dirName)
		
		// 查找目录中的 .toml 文件（角色定义文件）
		dirEntries, err := os.ReadDir(dirPath)
		if err != nil {
			continue
		}
		
		var tomlPath string
		for _, file := range dirEntries {
			if !file.IsDir() && strings.HasSuffix(file.Name(), ".toml") {
				tomlPath = filepath.Join(dirPath, file.Name())
				break
			}
		}
		
		if tomlPath == "" {
			continue // 跳过没有 toml 文件的目录
		}
		
		// 解析 TOML 获取 ID
		content, err := os.ReadFile(tomlPath)
		if err != nil {
			continue
		}
		
		var data CharacterData
		if err := toml.Unmarshal(content, &data); err != nil {
			fmt.Printf("Warning: failed to parse %s: %v\n", tomlPath, err)
			continue
		}
		
		if data.ID != "" {
			loader.idToDirMap[data.ID] = dirName
			loader.idToPathMap[data.ID] = dirPath
		}
	}
}

// Load 加载角色数据
func (loader *CharacterDataLoader) Load(characterID string) (*CharacterData, error) {
	// 检查缓存
	if data, ok := loader.cache[characterID]; ok {
		return data, nil
	}

	// 查找角色目录
	dirPath, ok := loader.idToPathMap[characterID]
	if !ok {
		return nil, fmt.Errorf("character not found: %s", characterID)
	}
	
	dirName := loader.idToDirMap[characterID]

	// 查找目录中的 .toml 文件
	entries, err := os.ReadDir(dirPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read character directory %s: %w", dirPath, err)
	}
	
	var filePath string
	for _, entry := range entries {
		if !entry.IsDir() && strings.HasSuffix(entry.Name(), ".toml") {
			filePath = filepath.Join(dirPath, entry.Name())
			break
		}
	}
	
	if filePath == "" {
		return nil, fmt.Errorf("no toml file found in %s", dirPath)
	}

	// 读取文件
	content, err := os.ReadFile(filePath)
	if err != nil {
		return nil, fmt.Errorf("failed to read character file %s: %w", filePath, err)
	}

	// 解析 TOML
	var data CharacterData
	if err := toml.Unmarshal(content, &data); err != nil {
		return nil, fmt.Errorf("failed to parse TOML for %s: %w", characterID, err)
	}

	// 设置运行时字段
	data.DirPath = dirName

	// 验证数据
	if err := data.Validate(); err != nil {
		return nil, fmt.Errorf("invalid character data for %s: %w", characterID, err)
	}

	// 缓存
	loader.cache[characterID] = &data

	return &data, nil
}

// GetDirPath 获取角色目录路径
func (loader *CharacterDataLoader) GetDirPath(characterID string) (string, bool) {
	path, ok := loader.idToPathMap[characterID]
	return path, ok
}

// GetDirName 获取角色目录名
func (loader *CharacterDataLoader) GetDirName(characterID string) (string, bool) {
	dir, ok := loader.idToDirMap[characterID]
	return dir, ok
}

// Validate 验证角色数据
func (cd *CharacterData) Validate() error {
	if cd.ID == "" {
		return fmt.Errorf("character id is required")
	}
	if cd.Name == "" {
		return fmt.Errorf("character name is required")
	}
	if cd.MaxHP <= 0 {
		return fmt.Errorf("max_hp must be positive")
	}
	if ParseElement(cd.Element) == ElementCount {
		return fmt.Errorf("invalid element: %s", cd.Element)
	}

	// 验证技能
	skillIDs := make(map[string]bool)
	for i, skill := range cd.Skills {
		if skill.ID == "" {
			return fmt.Errorf("skill %d: id is required", i)
		}
		if skillIDs[skill.ID] {
			return fmt.Errorf("duplicate skill id: %s", skill.ID)
		}
		skillIDs[skill.ID] = true

		if skill.Script == "" {
			return fmt.Errorf("skill %s: script is required", skill.ID)
		}

		// 验证消耗
		for j, cost := range skill.Cost {
			if cost.Count <= 0 {
				return fmt.Errorf("skill %s: cost %d count must be positive", skill.ID, j)
			}
			if !strings.EqualFold(cost.Type, "Any") && ParseElement(cost.Type) == ElementCount {
				return fmt.Errorf("skill %s: cost %d invalid type: %s", skill.ID, j, cost.Type)
			}
		}
	}

	return nil
}

// GetSkill 获取指定技能定义
func (cd *CharacterData) GetSkill(skillID string) *SkillDef {
	for i := range cd.Skills {
		if cd.Skills[i].ID == skillID {
			return &cd.Skills[i]
		}
	}
	return nil
}

// ParseElement 从字符串解析元素
func ParseElement(name string) Element {
	switch strings.ToLower(name) {
	case "pyro":
		return Pyro
	case "hydro":
		return Hydro
	case "cryo":
		return Cryo
	case "electro":
		return Electro
	case "anemo":
		return Anemo
	case "geo":
		return Geo
	case "dendro":
		return Dendro
	case "physical":
		return Physical
	default:
		return ElementCount // 无效值
	}
}
