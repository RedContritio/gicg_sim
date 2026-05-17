package main

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
	"math/rand"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

func findDataDir() string {
	candidates := []string{"data", "../data", "../../data"}
	for _, c := range candidates {
		if fi, err := os.Stat(c); err == nil && fi.IsDir() {
			abs, _ := filepath.Abs(c)
			return abs
		}
	}
	return "data"
}

// systemFiles returns the ordered list of system DSL files to load.
func systemFiles(dataDir string) []string {
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
// match has. Any X in at least one team's roster is kept (including
// mirror, where both sides have X) — the shared-load talent path uses
// per-slot SelfSlotProxy + LazyCharProxy / LazySkillRef to lazy-resolve
// owner slots at hook-fire time, so mirror is supported without a
// per-binding load. See gicg_engine/tests/helpers_test.go for the
// matching implementation used by Go tests.
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

// collectDSLPaths assembles the char-dsl + card file list for one
// game by reading from the (cached) pool resolution. teams names the
// chars each side wants; only those chars' skill files are loaded
// (declare files are loaded separately by initGame). cardPool filters
// the pool's cards by name: nil = all pool cards, empty slice = no
// cards. paddingCard, when non-empty, is always added to the allowed
// set so BuildDeck's padding spec resolves even if cardPool excluded
// it. No filesystem access on this path — paths come from PoolResolution.
func collectDSLPaths(pool *interp.PoolResolution, teams [2][]string, cardPool []string, paddingCard string) []string {
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

func initGame(cfg GameConfig) (*GameHandle, error) {
	dataDir := cfg.DataDir
	if dataDir == "" {
		dataDir = findDataDir()
	}

	g := &engine.Game{
		Hooks:    engine.NewHookRegistry(),
		Rng:      rand.New(rand.NewSource(cfg.Seed)),
		BaseSeed: cfg.Seed,
		// review D.5: init per-player deck RNGs at GameNew time. Default to
		// cfg.Seed so legacy single-seed callers see identical deck shuffles.
		// PeriodicEvaluator overrides via ResetDynamicStateWithSeeds per scenario.
		DeckRngs: [2]*rand.Rand{
			rand.New(rand.NewSource(cfg.Seed)),
			rand.New(rand.NewSource(cfg.Seed)),
		},
		DeckSeeds: [2]int64{cfg.Seed, cfg.Seed},
		Winner:    -1,
		FirstEnd:  -1,
		Obs:       resolveObsConfig(cfg.Obs),
		MaxRounds: cfg.MaxRounds,
		FixDice:   cfg.FixDice,
	}

	teams := [2][]string{}
	for pi := 0; pi < 2; pi++ {
		for ci, cd := range cfg.Players[pi].Chars {
			g.Players[pi].Chars = append(g.Players[pi].Chars, engine.CharInfo{
				PlayerIdx: pi, CharIdx: ci, Alive: true,
			})
			teams[pi] = append(teams[pi], cd.Name)
		}
		g.Players[pi].ActiveChar = -1
	}

	rt := interp.NewRuntime(g)
	rt.RegisterBuiltins()
	if cfg.DeckPadding != nil {
		rt.DeckPadding = &interp.DeckPaddingSpec{
			Card:       cfg.DeckPadding.Card,
			TargetSize: cfg.DeckPadding.TargetSize,
		}
	}

	poolIDs := cfg.Pools
	if len(poolIDs) == 0 {
		poolIDs = []string{"v_legacy"}
	}
	pool, err := interp.ResolvePoolUnion(dataDir, poolIDs)
	if err != nil {
		return nil, err
	}

	// System files
	for _, f := range systemFiles(dataDir) {
		if err := rt.ExecFileSandboxed(f); err != nil {
			return nil, fmt.Errorf("load %s: %w", filepath.Base(f), err)
		}
	}

	// Character declaration + bind
	for pi := 0; pi < 2; pi++ {
		for ci, name := range teams[pi] {
			entry := pool.Chars[name]
			if entry == nil {
				return nil, fmt.Errorf("char %q not in pools %v", name, poolIDs)
			}
			rt.CurrentOwnerPlayer = pi
			rt.CurrentOwnerChar = ci
			if err := rt.ExecFileSandboxed(entry.Declare); err != nil {
				return nil, fmt.Errorf("load char %s: %w", name, err)
			}
			if err := rt.BindChar(name, pi, ci); err != nil {
				return nil, fmt.Errorf("bind %s: %w", name, err)
			}
		}
	}
	rt.CurrentOwnerPlayer = -1
	rt.CurrentOwnerChar = -1

	// DSL files: split char-specific (loaded per binding) from shared cards
	// (loaded once via global topo). Per-binding loading lets each slot
	// register its own player-filtered skill hooks and capture its own
	// CharProxy in closures, which is required for mirror matches.
	paddingCard := ""
	if cfg.DeckPadding != nil {
		paddingCard = cfg.DeckPadding.Card
	}
	dslPaths := collectDSLPaths(pool, teams, cfg.CardPool, paddingCard)
	charFiles, sharedFiles := interp.SplitCharFiles(pool.Chars, dslPaths)
	sharedFiles = filterTalentCardsForSlotUniqueness(sharedFiles, teams)
	// buildPre collects the topo-sort "preExisting" list. It must be called
	// both before per-binding char loading AND again before the shared
	// cards load, so counters/skills/cards declared during per-binding
	// loading are visible to the shared topo. Without the second call,
	// L5 talent cards (蝶鳞, 守正, 星愿, 刺刺猫爪, 发现静电) that reference
	// char-file symbols (skill:蝶火, counter:蝶火_active, card:复刻, ...)
	// get silently excluded.
	buildPre := func() []string {
		var pre []string
		for name := range rt.Chars.ByName {
			pre = append(pre, "char:"+name)
		}
		for key := range rt.CounterEntries() {
			pre = append(pre, "counter:"+key)
			if idx := strings.LastIndex(key, ":"); idx >= 0 {
				pre = append(pre, "counter:"+key[idx+1:])
			}
		}
		for _, sk := range rt.Skills.ByID {
			pre = append(pre, "skill:"+sk.Name)
		}
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
				return nil, fmt.Errorf("LoadCharFilesPerBinding %s: %w", name, err)
			}
		}
	}
	if len(sharedFiles) > 0 {
		if err := rt.LoadFilesWithDeps(sharedFiles, buildPre()...); err != nil {
			return nil, fmt.Errorf("LoadFilesWithDeps: %w", err)
		}
	}

	// Enable event log for replay inspection
	g.Log = engine.NewEventLog()

	// Build decks (initial hand is dealt by system/draw.lua on round 1 start)
	for pi := 0; pi < 2; pi++ {
		rt.BuildDeck(pi)
	}

	// Start game: leave both players in PhaseSelectActive so the agent
	// gets to choose its initial active char as a normal action. The
	// rollout loop sees a select-active option in get_legal_actions on
	// the first two turns. This was previously hardcoded to slot 0 for
	// both players, which artificially fixed the opening char and
	// removed a real strategic decision.
	g.Phase = engine.PhaseSelectActive
	g.Turn = 0

	// Pin structural counter sids (HP/energy/alive/active per char +
	// dice + alive_count) at canonical positions 0..K-1 before shuffling
	// the rest. Phantoms are created for unbound char slots so sid
	// semantics stays stable across team_size configurations.
	g.StructuralSids = rt.BuildStructuralCounterIDs(g)

	// Shuffle for RL observation
	g.InitShuffle(g.Rng)

	return &GameHandle{Game: g, RT: rt}, nil
}
