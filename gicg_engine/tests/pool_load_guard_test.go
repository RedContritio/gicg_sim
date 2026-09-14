package tests

// F3 全树加载 guard — 配合 topo loader fail-loud(loader_topo.go),
// 系统性保证仓库内所有真实池的 DSL 文件可加载:
//
//   1. 每个池(及 testPools union)、每个池内角色,走 production 路径
//      factory.NewGame 构一局镜像对局(双方同角色)。fail-loud 后任何
//      依赖不可解析的文件 → NewGame 直接报错,死文件不可能静默潜伏。
//      镜像保证该角色的天赋卡(requires_char)进入加载集。
//   2. 对局构造后按声明名断言卡注册表:requires_char 为空或命中队伍
//      的卡必须已注册;requires_char 未命中的卡必须被声明式预过滤
//      (FilterTalentCardsForSlotUniqueness)排除——锁定「可选文件」唯一
//      合法通道在 topo 之前。
//   3. 全池静态断言:每个 requires_char 标记都解析到 union 内存在的
//      角色,否则该卡在任何对局里都进不了加载集 = 构造性死文件。
//
// 取代 F2 的单卡断言 TestYiYiDaiLao_LoadsIntoCardSet(以逸待劳 属
// v_legacy 无 requires_char 卡,在本 guard 的每局注册表断言内)。

import (
	"os"
	"regexp"
	"sort"
	"testing"

	"gicg_mono/gicg_engine/factory"
	"gicg_mono/gicg_engine/interp"
)

// guardPoolSets 列出受 guard 的池组合:每个真实池单独 + 全 union。
var guardPoolSets = [][]string{
	{"test_basic"},
	{"v_legacy"},
	{"v_phase2"},
	{"spike"},
	testPools, // v_phase2 + v_legacy + test_basic + spike union
}

var declareCardNameRe = regexp.MustCompile(`declare_card\(\s*"([^"]+)"`)
var requiresCharRe = regexp.MustCompile(`requires_char\s*=\s*"([^"]+)"`)

// cardMeta 扫一个卡文件的声明名 + requires_char 标记(与
// factory.FilterTalentCardsForSlotUniqueness 同一 marker 语义)。
type cardMeta struct {
	declared     string
	requiresChar string
}

func scanCardMeta(t *testing.T, path string) cardMeta {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	m := cardMeta{}
	if g := declareCardNameRe.FindSubmatch(data); g != nil {
		m.declared = string(g[1])
	}
	if g := requiresCharRe.FindSubmatch(data); g != nil {
		m.requiresChar = string(g[1])
	}
	return m
}

func sortedCharNames(pool *interp.PoolResolution) []string {
	names := make([]string, 0, len(pool.Chars))
	for n := range pool.Chars {
		names = append(names, n)
	}
	sort.Strings(names)
	return names
}

func sortedCardPaths(pool *interp.PoolResolution) []string {
	paths := make([]string, 0, len(pool.Cards))
	for _, p := range pool.Cards {
		paths = append(paths, p)
	}
	sort.Strings(paths)
	return paths
}

// TestAllPoolFilesLoadable: guard #1 + #2。
func TestAllPoolFilesLoadable(t *testing.T) {
	for _, poolIDs := range guardPoolSets {
		pool, err := interp.ResolvePoolUnion(dataDir, poolIDs)
		if err != nil {
			t.Fatalf("ResolvePoolUnion %v: %v", poolIDs, err)
		}
		for _, charName := range sortedCharNames(pool) {
			cfg := factory.GameConfig{DataDir: dataDir, Pools: poolIDs, Seed: 42}
			cfg.Players[0].Chars = []factory.CharDef{{Name: charName}}
			cfg.Players[1].Chars = []factory.CharDef{{Name: charName}}
			h, err := factory.NewGame(cfg)
			if err != nil {
				t.Errorf("pools %v mirror %q: NewGame failed:\n%v", poolIDs, charName, err)
				continue
			}
			for _, p := range sortedCardPaths(pool) {
				meta := scanCardMeta(t, p)
				if meta.declared == "" {
					t.Errorf("pools %v: %s has no declare_card — unscannable card file", poolIDs, p)
					continue
				}
				inTeam := meta.requiresChar == "" || meta.requiresChar == charName
				registered := h.RT.Cards.ByName[meta.declared] != nil
				if inTeam && !registered {
					t.Errorf("pools %v mirror %q: card %q (%s) not in registry — file missing from load set",
						poolIDs, charName, meta.declared, p)
				}
				if !inTeam && registered {
					t.Errorf("pools %v mirror %q: off-team talent card %q (%s) leaked past the requires_char pre-filter",
						poolIDs, charName, meta.declared, p)
				}
			}
		}
	}
}

// TestRequiresCharResolvesInUnion: guard #3 — requires_char 指向 union
// 不存在的角色 = 该卡构造性死文件(任何队伍配置都进不了加载集)。
func TestRequiresCharResolvesInUnion(t *testing.T) {
	pool, err := interp.ResolvePoolUnion(dataDir, testPools)
	if err != nil {
		t.Fatalf("ResolvePoolUnion %v: %v", testPools, err)
	}
	for _, p := range sortedCardPaths(pool) {
		meta := scanCardMeta(t, p)
		if meta.requiresChar == "" {
			continue
		}
		if pool.Chars[meta.requiresChar] == nil {
			t.Errorf("%s: requires_char = %q does not resolve to any char in union %v — constructively dead card",
				p, meta.requiresChar, testPools)
		}
	}
}
