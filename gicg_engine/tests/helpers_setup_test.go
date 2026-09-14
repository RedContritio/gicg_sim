package tests

import (
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
	"path/filepath"
	"sort"
	"strings"
	"testing"
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

func newGame(t *testing.T, team0, team1 []string, seed int64, withDecks bool, pools ...string) *GameEnv {
	t.Helper()
	g := &engine.Game{
		Hooks:    engine.NewHookRegistry(),
		Rng:      engine.NewRandom(seed),
		BaseSeed: seed,
		// review D.5: init per-player deck RNGs (default to single seed for
		// test backward compat — production callers pass via cfg.DeckSeeds).
		DeckRngs: [2]*engine.Random{
			engine.NewRandom(seed),
			engine.NewRandom(seed),
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
	pool, dslPaths := collectDSLPaths(teams, pools...)
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
	// their pre-ADR-0011 deck shape. F4 (deck fail-loud): the engine no
	// longer truncates an over-full eligible set silently, so the fixture
	// pins the historical composition explicitly via ExplicitDecks.
	if withDecks {
		rt.DeckPadding = &interp.DeckPaddingSpec{Card: "碌碌无为", TargetSize: 15}
		for pi := 0; pi < 2; pi++ {
			rt.ExplicitDecks[pi] = legacyTruncatedDeck(rt, pi, 15)
			if err := rt.BuildDeck(pi); err != nil {
				t.Fatalf("BuildDeck(%d): %v", pi, err)
			}
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

// legacyTruncatedDeck reproduces the pre-F4 implicit deck for test
// fixtures: eligible cards sorted by name (padding card excluded),
// capped at target. The engine's implicit path now fail-louds when the
// eligible set exceeds the padding target (F4), but these tests load
// broad pool unions (testPools) where eligibility regularly exceeds 15
// and only exercise hook/damage mechanics, not deck composition — so
// the historical composition is pinned explicitly here, at fixture
// level, where any future drift is a visible test-code decision.
func legacyTruncatedDeck(rt *interp.Runtime, pi, target int) []string {
	names := make([]string, 0, len(rt.Cards.ByName))
	for n := range rt.Cards.ByName {
		if n == rt.DeckPadding.Card {
			continue
		}
		names = append(names, n)
	}
	sort.Strings(names)
	deck := make([]string, 0, target)
	for _, n := range names {
		if rt.CardEligibleFor(rt.Cards.ByName[n], pi) {
			deck = append(deck, n)
			if len(deck) == target {
				break
			}
		}
	}
	return deck
}
