package interp

import (
	engine "gicg_mono/gicg_engine"
)

// Runtime holds the per-game dynamic state. It embeds a pointer to a
// shared Ruleset (static, immutable). Many Runtimes can share one
// Ruleset and run in parallel, because Ruleset is read-only and all
// mutable fields live on Runtime.
//
// Runtime's transient fields (CurrentContextPlayer, CurrentOwnerPlayer/
// Char, CurrentCardTargetPlayer/Char, DeferredFns, PendingTokens,
// lastError) are scratch space for hook dispatch and card play. They
// are deep-copied on Clone so parallel playthroughs don't interfere.
type Runtime struct {
	*Ruleset // embedded: rt.Interp / rt.Counters / rt.Chars / ... keep working

	Game *engine.Game

	// Context state (set during file loading and hook execution)
	CurrentOwnerPlayer   int
	CurrentOwnerChar     int
	CurrentContextPlayer int

	// Deprecated compatibility fields. Target.CardTarget resolves from Game's
	// execution frames; these fields are not a gameplay source of truth.
	CurrentCardTargetPlayer int
	CurrentCardTargetChar   int

	// Deferred functions
	DeferredFns        []*Closure
	currentHookContext *engine.EventContext

	// LoadedFiles accumulates the file paths fed through ExecFileSandboxed
	// (in load order). Used by the IR-2.b finalization step to walk the
	// cached AST chunks and extract per-file closure bindings.
	LoadedFiles []string

	// Debug
	traceEnabled bool
	lastError    error

	// CurrentSourceFile is a short tag identifying the DSL file currently
	// being executed (e.g. "铁剑" for data/cards/L3/铁剑.lua). Set by
	// ExecFileSandboxed before parse/exec, cleared after. Hook builtins
	// copy this (plus a per-file-load registration index) onto the Hook
	// struct so the visualizer can give each hook a unique label.
	CurrentSourceFile string
	// CurrentSourceHookIdx counts hook registrations within the current
	// file load. Combined with CurrentSourceFile it gives every hook a
	// unique tag like "蒸发#0" or "赤蝶_蝶火#3", disambiguating multiple
	// on_xxx callbacks from the same file (e.g. 蝶火.lua has 2 damage_boost
	// registrations: 物理→火 enchant and 枪 加伤).
	CurrentSourceHookIdx int

	// CurrentFileTalentOwner captures the char name a talent card file is
	// "bound to" via declare_card(..., requires_char="X"). It is set by
	// builtinDeclareCard during shared-load and cleared by ExecFileSandboxed
	// at file-exit. Downstream Scope.Self / get_char / get_skill builtins
	// that are called within the same file (and not under per-binding
	// char load, i.e. CurrentOwnerPlayer < 0) use this field to decide
	// whether to return lazy/ctx-resolved proxies (non-empty) or error
	// (empty — a plain shared-load card using Scope.Self is invalid).
	//
	// Not accessible from DSL. Save/restore happens in ExecFileSandboxed
	// so a file that sets it can't leak the binding into the next file.
	CurrentFileTalentOwner string

	// CurrentFileCharOwner captures the char name declared by the current
	// file via declare_char, for the narrow window where the pre-bind
	// char file (capi.go step 2) is executing: CurrentOwnerPlayer/Char
	// is set, but BySlot[p][c] is not yet populated (bind_char runs AFTER
	// the file finishes). Subsequent declare_counter(Scope.Self) within
	// the same file needs a char name to key the entry; without this
	// field, CounterKey would fall back to the bare name and collide
	// across chars ("hp" declared by 赤蝶 and 墨客 merge).
	//
	// Set by builtinDeclareChar, cleared by ExecFileSandboxed. Not
	// DSL-accessible.
	CurrentFileCharOwner string

	// DeckPadding controls how BuildDeck pads short decks. nil = no
	// padding. Set by capi initGame from GameConfig.DeckPadding; survives
	// Clone (shared pointer — spec is treated as immutable) and
	// ResetDynamic (deck shape is part of the static game spec).
	DeckPadding *DeckPaddingSpec

	// ExplicitDecks pins each player's deck to a declared card-name list
	// (F4 — [scenario].deck_0/deck_1). nil entry = implicit path (deck =
	// full eligible set). Set at game-init from GameConfig.Players[i].Deck;
	// like DeckPadding the slices are treated as immutable spec, shared
	// across Clone and reused by ResetDynamic.
	ExplicitDecks [2][]string
}

// NewRuntime creates a fresh Ruleset and wraps it in a Runtime bound to g.
// Used at game construction time; for cloning, use Runtime.Clone instead.
func NewRuntime(g *engine.Game) *Runtime {
	rs := NewRuleset()
	return rs.NewRuntime(g)
}

// NewRuntime (on *Ruleset) creates a Runtime sharing this ruleset and
// bound to the given Game. The Game's Extra pointer is set to the new
// Runtime so hook closures can resolve it later.
func (rs *Ruleset) NewRuntime(g *engine.Game) *Runtime {
	rt := &Runtime{
		Ruleset:              rs,
		Game:                 g,
		CurrentOwnerPlayer:   -1,
		CurrentOwnerChar:     -1,
		CurrentContextPlayer: -1,
	}
	if g != nil {
		g.Extra = rt
	}
	return rt
}

// Clone returns an independent Runtime suitable for parallel speculative
// rollout. The clone shares the Ruleset (static DSL definitions) but owns
// a deep copy of the Game and a private scratchpad for transient state
// (DeferredFns, CurrentContextPlayer, etc.). Hook closures running under
// the clone will resolve the clone's runtime via Game.Extra.
//
// The clone starts with no pending per-step state — callers about to
// rollback should Snapshot before making speculative Steps on the clone.
func (rt *Runtime) Clone() *Runtime {
	newGame := rt.Game.DeepCopy()
	copy := *rt
	clone := &copy
	clone.Game = newGame
	clone.DeferredFns = append([]*Closure(nil), rt.DeferredFns...)
	clone.currentHookContext = nil
	newGame.Extra = clone
	return clone
}

// ResetDynamic restores the wrapped Game to its just-after-load state and
// re-fires per-char spawn hooks so DSL handlers (alive_count, status
// counters, etc.) reinitialize cleanly. After this call, the game sits in
// the opening round's reroll decision with both players having selected char 0.
//
// Static identity (Ruleset, Hooks, CounterPerm, HookPerm) is preserved.
// The clone-friendly invariant Game.Extra == rt is maintained.
func (rt *Runtime) ResetDynamic(seed int64) {
	rt.ResetDynamicWithSeeds(seed, [2]int64{seed, seed})
}

// ResetDynamicWithSeeds — review D.5 (2026-05-14): 3-axis seed variant.
// diceSeed controls Rng (dice rolls + DSL randomness + obs perm via
// InitShuffle); deckSeeds[pi] independently control per-player deck
// Fisher-Yates shuffle. ResetDynamic(seed) routes here as
// ResetDynamicWithSeeds(seed, [seed, seed]) so legacy single-seed callers
// keep identical deck shuffles. Post-state: the opening round's reroll
// decision, with both players having selected char 0.
func (rt *Runtime) ResetDynamicWithSeeds(diceSeed int64, deckSeeds [2]int64) {
	g := rt.Game
	g.ResetDynamicStateWithSeeds(diceSeed, deckSeeds)

	rt.CurrentOwnerPlayer = -1
	rt.CurrentOwnerChar = -1
	rt.CurrentContextPlayer = -1
	rt.CurrentCardTargetPlayer = 0
	rt.CurrentCardTargetChar = 0
	rt.DeferredFns = nil
	rt.currentHookContext = nil
	rt.lastError = nil

	for pi := 0; pi < 2; pi++ {
		for ci := 0; ci < MaxChars; ci++ {
			entry := rt.Chars.BySlot[pi][ci]
			if entry == nil || entry.AliveCounterID < 0 {
				continue
			}
			g.WriteCounter(entry.AliveCounterID, engine.OpSet, 1)
		}
	}

	for pi := 0; pi < 2; pi++ {
		if err := rt.BuildDeck(pi); err != nil {
			// The deck spec (ExplicitDecks / DeckPadding / declared card
			// set) is static after NewGame validated it, so a reset-time
			// BuildDeck failure can only be an engine bug. This panic is
			// an invariant assertion, not input validation — it keeps the
			// error-free reset signature across capi GameReset and the
			// Go-native per-episode reset path.
			panic(err)
		}
	}

	g.Step(0)
	g.Step(0)
	g.GetLegalActions()
}

// ResolvePlayer converts Player.Own/Enemy/absolute to absolute index.
func (rt *Runtime) ResolvePlayer(p int) int {
	if p >= 0 {
		return p
	}
	if p == PlayerOwn {
		return rt.CurrentContextPlayer
	}
	if p == PlayerEnemy {
		return 1 - rt.CurrentContextPlayer
	}
	return -1
}

// BindChar is a public wrapper for builtinBindChar.
func (rt *Runtime) BindChar(name string, playerIdx, charIdx int) error {
	_, err := rt.builtinBindChar([]Value{name, playerIdx, charIdx})
	return err
}

// CounterEntries returns the counter registry for external use.
func (rt *Runtime) CounterEntries() map[string]*CounterEntry {
	return rt.Counters.Entries
}

// SkillIdentityOf — ADR-0019 §B.3 P0-γ 修复:skillID → (charIdx, slot)
// 反查,用于 obs encoder 编码 prepare-skill 状态(避免暴露 global skill ID
// 进 obs,违反 No-IDs 原则)。
//
// playerIdx ∈ {0, 1};skillID 是 Game.Preparing[player] 存的 ID。
// 返回 (charIdx ∈ [0, 4), slot ∈ [0, 4)) 或 (-1, -1, false) 若未找到。
//
// SkillSlot 对应 CharEntry.SkillIDs 数组 index,通常:
//
//	slot 0 = 普攻 / slot 1 = 战技 / slot 2 = 爆发 / slot 3 = 被动
//
// 但 slot 含义由 char declare 顺序决定,DSL 作者保证。
//
// 实时遍历 BySlot[player] (4 chars × ~4 skills = 16 ops),非 hot path
// (obs build per RL step 1-2 次调用),无 cache 必要。
func (rt *Runtime) SkillIdentityOf(playerIdx, skillID int) (charIdx, slot int, ok bool) {
	if playerIdx < 0 || playerIdx > 1 || skillID == 0 {
		return -1, -1, false
	}
	for cIdx, entry := range rt.Chars.BySlot[playerIdx] {
		if entry == nil {
			continue
		}
		for sIdx, sid := range entry.SkillIDs {
			if sid == skillID {
				return cIdx, sIdx, true
			}
		}
	}
	return -1, -1, false
}

// SetTrace enables/disables debug tracing.
func (rt *Runtime) SetTrace(enabled bool) {
	rt.traceEnabled = enabled
}

// CounterKey computes the registry key for a counter.
//
// PerPlayer / PerChar / Global: bare name.
//
// Self / ActiveStatus: namespaced by owner char name, so "hp" under
// 赤蝶 and "hp" under 墨客 are separate entries with their own
// bounds / init values. Per-binding char-file declares (which set
// CurrentOwnerPlayer/Char) look up char name via BySlot; shared-load
// talent declares (which set CurrentFileTalentOwner) use the talent
// owner directly. Entries created by per-binding declares are
// populated into their SlotIDs table progressively (one slot per
// mirror binding); talent cross-references the same entry via
// get_counter and lazy-resolves slots via SelfSlotProxy.
func (rt *Runtime) CounterKey(name string, scope int) string {
	if scope != ScopeSelf && scope != ScopeActiveStatus {
		return name
	}
	if rt.CurrentOwnerPlayer >= 0 {
		if entry := rt.Chars.BySlot[rt.CurrentOwnerPlayer][rt.CurrentOwnerChar]; entry != nil {
			return entry.Name + ":" + name
		}
		// Pre-bind char file: BySlot not yet populated. declare_char
		// has stored the char name in CurrentFileCharOwner.
		if rt.CurrentFileCharOwner != "" {
			return rt.CurrentFileCharOwner + ":" + name
		}
	}
	if rt.CurrentFileTalentOwner != "" {
		return rt.CurrentFileTalentOwner + ":" + name
	}
	return name
}
