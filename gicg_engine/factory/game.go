package factory

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
	"math/rand"
	"os"
	"strings"
)

// GameHandle holds a game instance with its interpreter runtime.
// It is the unit of state managed by the capi handle table and by
// Go-native consumers (gicg_actor pool goroutines).
type GameHandle struct {
	Game *engine.Game
	RT   *interp.Runtime
	// SuspendedLog holds g.Log while ``GameLogSuspend`` has detached it
	// from the live game (nil when logging is active). See the
	// suspend/resume API for the MCTS-rollout use case.
	SuspendedLog *engine.EventLog
}

// NewGame constructs a fully-initialized GameHandle from a GameConfig.
// This is the canonical game factory used by both the c-shared capi
// shim and the Go-native actor pool — keeping a single initialization
// path means the two callers can never drift apart (e.g. on hook IR
// finalization or pool resolution).
func NewGame(cfg GameConfig) (*GameHandle, error) {
	dataDir := cfg.DataDir
	if dataDir == "" {
		dataDir = FindDataDir()
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
		Obs:       ResolveObsConfig(cfg.Obs),
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

	for _, f := range SystemFiles(dataDir) {
		if err := rt.ExecFileSandboxed(f); err != nil {
			return nil, fmt.Errorf("load %s: %w", f, err)
		}
	}

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

	paddingCard := ""
	if cfg.DeckPadding != nil {
		paddingCard = cfg.DeckPadding.Card
	}
	dslPaths := CollectDSLPaths(pool, teams, cfg.CardPool, paddingCard)
	charFiles, sharedFiles := interp.SplitCharFiles(pool.Chars, dslPaths)
	sharedFiles = FilterTalentCardsForSlotUniqueness(sharedFiles, teams)
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

	// IR-2.b: compile each hook body AST → ir.CompiledHook and attach
	// to Hook.Repr. Post-IR-cutover (IR-2.b.2), obs hook section is
	// IR-encoded — Repr-nil hooks contribute all-zero, which the encoder
	// masks. That silent fall-back hid a 0% compile success rate before
	// G1 landed; threshold below fail-loud on any future schema drift.
	okN, failN := finalizeHookIRs(g, rt)
	if os.Getenv("IR_DIAG") != "" {
		fmt.Fprintf(os.Stderr, "[IR-DIAG] finalizeHookIRs: ok=%d fail=%d total=%d\n", okN, failN, okN+failN)
	}
	total := okN + failN
	if total > 0 {
		failRate := float64(failN) / float64(total)
		if failRate > 0.02 {
			return nil, fmt.Errorf(
				"IR finalize failure rate %.1f%% (ok=%d fail=%d) exceeds 2%% — schema mismatch or builtin coverage gap (set IR_DIAG=1 for per-failure detail)",
				failRate*100, okN, failN,
			)
		}
	}

	g.Log = engine.NewEventLog()

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

	g.InitShuffle(g.Rng)

	return &GameHandle{Game: g, RT: rt}, nil
}
