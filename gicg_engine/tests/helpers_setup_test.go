package tests

import (
	"math/rand"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// Game construction helpers — NewGame / NewGameSeed / NewGameWithDeck
// construct a fully-loaded engine + interpreter pair from a teams spec.
// systemFiles / filterTalentCardsForSlotUniqueness / splitDSLPaths /
// collectDSLPaths mirror the logic in gicg_engine/capi/capi.go so tests
// exercise the same DSL load sequence production uses.

// --- Setup ---

// NewGame creates a fully initialized game environment (no deck).
func NewGame(t *testing.T, team0, team1 []string) *GameEnv {
	t.Helper()
	return newGame(t, team0, team1, 42, false)
}

// NewGameSeed creates a game with specific seed (no deck).
func NewGameSeed(t *testing.T, team0, team1 []string, seed int64) *GameEnv {
	t.Helper()
	return newGame(t, team0, team1, seed, false)
}

// NewGameWithDeck builds decks + deals initial hands via the normal round_start draw.
// Use this for replay/record tests that need realistic hand state.
func NewGameWithDeck(t *testing.T, team0, team1 []string) *GameEnv {
	t.Helper()
	return newGame(t, team0, team1, 42, true)
}

func newGame(t *testing.T, team0, team1 []string, seed int64, withDecks bool) *GameEnv {
	t.Helper()
	g := &engine.Game{
		Hooks:    engine.NewHookRegistry(),
		Rng:      rand.New(rand.NewSource(seed)),
		BaseSeed: seed,
		// review D.5: init per-player deck RNGs (default to single seed for
		// test backward compat — production callers pass via cfg.DeckSeeds).
		DeckRngs: [2]*rand.Rand{
			rand.New(rand.NewSource(seed)),
			rand.New(rand.NewSource(seed)),
		},
		DeckSeeds: [2]int64{seed, seed},
		Obs:       engine.NewDefaultObsConfig(),
	}

	for pi, team := range [2][]string{team0, team1} {
		for ci := range team {
			g.Players[pi].Chars = append(g.Players[pi].Chars, engine.CharInfo{
				PlayerIdx: pi, CharIdx: ci, Alive: true,
			})
		}
		g.Players[pi].ActiveChar = -1
	}

	rt := interp.NewRuntime(g)
	rt.RegisterBuiltins()

	// System files
	for _, f := range systemFiles() {
		if err := rt.ExecFileSandboxed(f); err != nil {
			t.Fatalf("load %s: %v", filepath.Base(f), err)
		}
	}

	// Chars: declare + bind, reading paths from the cached pool.
	teams := [2][]string{team0, team1}
	pool, dslPaths := collectDSLPaths(teams)
	for pi := 0; pi < 2; pi++ {
		for ci, name := range teams[pi] {
			entry := pool.Chars[name]
			if entry == nil {
				t.Fatalf("char %q not in test pools %v", name, testPools)
			}
			rt.CurrentOwnerPlayer = pi
			rt.CurrentOwnerChar = ci
			if err := rt.ExecFileSandboxed(entry.Declare); err != nil {
				t.Fatalf("load char %s: %v", name, err)
			}
			if err := rt.BindChar(name, pi, ci); err != nil {
				t.Fatalf("bind %s: %v", name, err)
			}
		}
	}
	rt.CurrentOwnerPlayer = -1
	rt.CurrentOwnerChar = -1

	// DSL files: split into char-specific (loaded per binding so mirror
	// matches get a fresh slot-aware load for each binding) and shared
	// cards (loaded once via the global topo loader).
	charFiles, sharedFiles := interp.SplitCharFiles(pool.Chars, dslPaths)
	// Talent cards (requires_char = "..." + Self-scope deps on that char's
	// buff counters) can only load when the required char has exactly one
	// slot, because the shared topo loader picks a unique slot for charDep
	// and mirror matches have >1. Drop them from sharedFiles otherwise.
	sharedFiles = filterTalentCardsForSlotUniqueness(sharedFiles, teams)
	buildPre := func() []string {
		var pre []string
		for name := range rt.Chars.ByName {
			pre = append(pre, "char:"+name)
		}
		// CounterEntries keys for Self/ActiveStatus scope are "P:C:name"
		// (e.g. "0:0:蝶火_active"), while card files do their get_counter
		// lookups by bare name. Register BOTH forms as satisfied symbols
		// so the topo sort can resolve "counter:蝶火_active" even when
		// the provider file was loaded under a per-binding slot context.
		for key := range rt.CounterEntries() {
			pre = append(pre, "counter:"+key)
			if idx := strings.LastIndex(key, ":"); idx >= 0 {
				pre = append(pre, "counter:"+key[idx+1:])
			}
		}
		// Skills declared during per-binding char file loading must also
		// be listed so talent cards that do get_skill(char, "...") can
		// topo-resolve. Without this the L5 talent cards (蝶鳞, 守正, 星愿,
		// 刺刺猫爪, 发现静电) are silently excluded from the shared topo
		// because skill:蝶火 / skill:玉璋 / etc. have no provider.
		for _, sk := range rt.Skills.ByID {
			pre = append(pre, "skill:"+sk.Name)
		}
		// Cards declared in char files (e.g. 刻师傅_复刻.lua declares 复刻)
		// must also be listed so talent cards that do get_card("...") can
		// topo-resolve.
		for name := range rt.Cards.ByName {
			pre = append(pre, "card:"+name)
		}
		return pre
	}
	for pi := 0; pi < 2; pi++ {
		for ci, name := range teams[pi] {
			files := charFiles[name]
			if len(files) == 0 {
				continue
			}
			if err := rt.LoadCharFilesPerBinding(files, pi, ci, buildPre()...); err != nil {
				t.Fatalf("LoadCharFilesPerBinding %s: %v", name, err)
			}
		}
	}
	// Rebuild pre AFTER per-binding load so the shared cards' topo sort
	// sees counters declared in char files (e.g. 蝶火_active), otherwise
	// talent cards that depend on those counters get silently excluded.
	if len(sharedFiles) > 0 {
		if err := rt.LoadFilesWithDeps(sharedFiles, buildPre()...); err != nil {
			t.Fatalf("LoadFilesWithDeps: %v", err)
		}
	}

	// Enable event log
	g.Log = engine.NewEventLog()

	// Optionally build decks; initial hand is drawn by system/draw.lua on
	// round 1 start, so we must build before select-active. Tests default
	// to the legacy 碌碌无为 / 15-slot padding so existing fixtures keep
	// their pre-ADR-0011 deck shape; tests exercising the no-padding path
	// can override rt.DeckPadding before calling NewGameWithDeck.
	if withDecks {
		rt.DeckPadding = &interp.DeckPaddingSpec{Card: "碌碌无为", TargetSize: 15}
		for pi := 0; pi < 2; pi++ {
			rt.BuildDeck(pi)
		}
	}

	// Start game
	g.Phase = engine.PhaseSelectActive
	g.Turn = 0
	g.Winner = -1
	g.FirstEnd = -1
	g.Step(0) // P0 select char 0
	g.Step(0) // P1 select char 0
	// Game is now in PhaseRoundStart (inter-round pause). Advance into round 1
	// so tests see the standard "ready to play" PhaseAction state.
	g.GetLegalActions()

	env := &GameEnv{G: g, RT: rt, T: t}

	// Print replay on test failure
	t.Cleanup(func() {
		if t.Failed() && g.Log != nil {
			t.Log("=== REPLAY ===")
			g.Log.Print(g.SkillNames, g.CardNames, g.CharNames)
		}
	})

	return env
}

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

func collectDSLPaths(teams [2][]string) (*interp.PoolResolution, []string) {
	pool, err := interp.ResolvePoolUnion(dataDir, testPools)
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
