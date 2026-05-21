package factory

import (
	"gicg_mono/gicg_engine/interp"
	"os"
	"path/filepath"
	"regexp"
	"sort"
)

// FindDataDir searches the working tree for a "data/" sibling. The
// candidate list mirrors the legacy capi behavior so existing Python
// callers (which CWD into the repo root) keep resolving the same dir.
func FindDataDir() string {
	candidates := []string{"data", "../data", "../../data"}
	for _, c := range candidates {
		if fi, err := os.Stat(c); err == nil && fi.IsDir() {
			abs, _ := filepath.Abs(c)
			return abs
		}
	}
	return "data"
}

// SystemFiles returns the ordered list of system DSL files to load.
func SystemFiles(dataDir string) []string {
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

// FilterTalentCardsForSlotUniqueness drops shared card files whose
// `requires_char = "X"` marker refers to a char that no side of the
// match has. Any X in at least one team's roster is kept (including
// mirror, where both sides have X) — the shared-load talent path uses
// per-slot SelfSlotProxy + LazyCharProxy / LazySkillRef to lazy-resolve
// owner slots at hook-fire time, so mirror is supported without a
// per-binding load. See gicg_engine/tests/helpers_test.go for the
// matching implementation used by Go tests.
func FilterTalentCardsForSlotUniqueness(paths []string, teams [2][]string) []string {
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

// CollectDSLPaths assembles the char-dsl + card file list for one
// game by reading from the (cached) pool resolution. teams names the
// chars each side wants; only those chars' skill files are loaded
// (declare files are loaded separately by NewGame). cardPool filters
// the pool's cards by name: nil = all pool cards, empty slice = no
// cards. paddingCard, when non-empty, is always added to the allowed
// set so BuildDeck's padding spec resolves even if cardPool excluded
// it. No filesystem access on this path — paths come from PoolResolution.
func CollectDSLPaths(pool *interp.PoolResolution, teams [2][]string, cardPool []string, paddingCard string) []string {
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

	allowAll := cardPool == nil
	allowed := map[string]bool{}
	if paddingCard != "" {
		allowed[paddingCard] = true
	}
	for _, n := range cardPool {
		allowed[n] = true
	}

	for name, p := range pool.Cards {
		if !allowAll && !allowed[name] {
			continue
		}
		paths = append(paths, p)
	}

	sort.Strings(paths)
	return paths
}
