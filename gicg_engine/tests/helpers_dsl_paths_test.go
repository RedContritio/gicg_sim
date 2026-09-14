package tests

import (
	"gicg_mono/gicg_engine/interp"
	"os"
	"path/filepath"
	"regexp"
	"sort"
)

func systemFiles() []string {
	ordered := []string{
		"system/round.lua", "system/dice.lua", "system/alive.lua", "system/draw.lua",
		"system/element.lua", "system/frozen.lua", "system/food.lua",
		"system/equip.lua", "system/timeout.lua",
		"system/arche.lua", // ADR-0019 §A.3 Phase 1: Arkhe enum + marker counter
	}
	reactDir := filepath.Join(dataDir, "system", "reactions")
	entries, _ := os.ReadDir(reactDir)
	for _, e := range entries {
		if filepath.Ext(e.Name()) == ".lua" {
			ordered = append(ordered, "system/reactions/"+e.Name())
		}
	}
	ordered = append(ordered, "system/reaction.lua")

	var out []string
	for _, n := range ordered {
		p := filepath.Join(dataDir, n)
		if _, err := os.Stat(p); err == nil {
			out = append(out, p)
		}
	}
	return out
}

// filterTalentCardsForSlotUniqueness drops shared card files whose
// `requires_char = "X"` marker refers to a char that no side of the
// match has. Mirror (both sides have X) is supported via the shared-
// load talent path (SelfSlotProxy + LazyCharProxy + LazySkillRef lazy-
// resolving at hook-fire time), so k>=1 is kept.
func filterTalentCardsForSlotUniqueness(paths []string, teams [2][]string) []string {
	slotCount := map[string]int{}
	for pi := 0; pi < 2; pi++ {
		for _, name := range teams[pi] {
			slotCount[name]++
		}
	}
	requiresRe := regexp.MustCompile(`requires_char\s*=\s*"([^"]+)"`)
	out := make([]string, 0, len(paths))
	for _, p := range paths {
		data, err := os.ReadFile(p)
		if err != nil {
			out = append(out, p)
			continue
		}
		m := requiresRe.FindStringSubmatch(string(data))
		if m == nil {
			out = append(out, p)
			continue
		}
		if slotCount[m[1]] > 0 {
			out = append(out, p)
		}
	}
	return out
}

// testPools lists the pools Go engine tests load from. v_legacy holds
// the prod chars/cards (赤蝶/墨客/... + L1..L6) used by most tests;
// test_basic holds synthetic 测试角色/测试卡 fixtures used by a few
// shape/element tests. The two pools are sibling roots with disjoint
// name sets, so a flat union is the right semantics here. Tests that
// want to exercise the parent-chain overlay mechanism specifically
// should call interp.ResolvePool directly with a single pool ID.
var testPools = []string{"v_phase2", "v_legacy", "test_basic", "spike"}

func collectDSLPaths(teams [2][]string, pools ...string) (*interp.PoolResolution, []string) {
	if len(pools) == 0 {
		pools = testPools
	}
	pool, err := interp.ResolvePoolUnion(dataDir, pools)
	if err != nil {
		panic(err)
	}
	seen := map[string]bool{}
	var paths []string
	for pi := 0; pi < 2; pi++ {
		for _, name := range teams[pi] {
			entry := pool.Chars[name]
			if entry == nil {
				continue
			}
			for _, p := range entry.Skills {
				if !seen[p] {
					seen[p] = true
					paths = append(paths, p)
				}
			}
		}
	}
	for _, p := range pool.Cards {
		paths = append(paths, p)
	}
	sort.Strings(paths)
	return pool, paths
}
