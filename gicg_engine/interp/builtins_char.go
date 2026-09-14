package interp

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
)

// Char-family builtins: declare_char, bind_char, get_char,
// findSelfCounter + registerAliveTransitionHook helpers.

func (rt *Runtime) builtinDeclareChar(args []Value) (Value, error) {
	name, _ := args[0].(string)
	opts, _ := args[1].(*Table)

	element := 0
	weapon := 0
	if opts != nil {
		if v, ok := opts.Fields["element"]; ok {
			element, _ = ToInt(v)
		}
		if v, ok := opts.Fields["weapon"]; ok {
			weapon, _ = ToInt(v)
		}
	}

	// Let subsequent declare_counter(Scope.Self) in this file key its entry
	// under this char name. Set before the idempotent early-return so
	// mirror-match second loads (which hit the early return) still scope
	// subsequent counter declarations correctly. ExecFileSandboxed clears
	// the field at file exit.
	rt.CurrentFileCharOwner = name

	// Idempotent: re-declaring the same name (e.g. when the char file is
	// loaded once per binding in a mirror match) returns the existing
	// template entry instead of clobbering it. This keeps Skills/SkillIDs
	// stable across loads. Per-slot state (PlayerIdx, HPCounterID, …) is
	// later cloned into BySlot entries by bind_char, so the template here
	// is treated as read-only metadata.
	if existing, ok := rt.Chars.ByName[name]; ok {
		return &CharProxy{Entry: existing}, nil
	}

	entry := &CharEntry{
		Name:            name,
		HPCounterID:     -1,
		EnergyCounterID: -1,
		AliveCounterID:  -1,
		ActiveCounterID: -1,
		Element:         element,
		Weapon:          weapon,
		PlayerIdx:       -1,
		CharIdx:         -1,
		Skills:          make(map[string]int),
		NormalAttackID:  -1,
	}
	rt.Chars.ByName[name] = entry
	return &CharProxy{Entry: entry}, nil
}

// findSelfCounter looks up a Self-scope counter owned by (playerIdx, charIdx).
// Returns the raw counter ID, or -1 if not found.
//
// Self/ActiveStatus entries are keyed "<charName>:<counterName>".
// SlotIDs[playerIdx*MaxChars+charIdx] stores the counter ID allocated
// for that slot, or -1 if the slot hasn't been declared.
func (rt *Runtime) findSelfCounter(playerIdx, charIdx int, name string) int {
	slot := rt.Chars.BySlot[playerIdx][charIdx]
	if slot == nil {
		return -1
	}
	key := slot.Name + ":" + name
	entry, ok := rt.Counters.Entries[key]
	if !ok {
		return -1
	}
	if entry.Scope != ScopeSelf && entry.Scope != ScopeActiveStatus {
		return -1
	}
	idx := playerIdx*MaxChars + charIdx
	if idx < 0 || idx >= len(entry.SlotIDs) {
		return -1
	}
	return entry.SlotIDs[idx]
}

func (rt *Runtime) builtinBindChar(args []Value) (Value, error) {
	name, _ := args[0].(string)
	playerIdx, _ := ToInt(args[1])
	charIdx, _ := ToInt(args[2])

	template, ok := rt.Chars.ByName[name]
	if !ok {
		return nil, fmt.Errorf("bind_char: unknown char %q", name)
	}

	// Build a per-slot CharEntry that copies template-level metadata but
	// owns its own per-slot state (PlayerIdx/CharIdx/counter IDs/Skills).
	// Mirror matches need each slot to be independently addressable so
	// per-slot CounterProxy / CharProxy don't alias.
	entry := &CharEntry{
		Name:            template.Name,
		Element:         template.Element,
		Weapon:          template.Weapon,
		PlayerIdx:       playerIdx,
		CharIdx:         charIdx,
		Skills:          make(map[string]int),
		HPCounterID:     -1,
		EnergyCounterID: -1,
		AliveCounterID:  -1,
		ActiveCounterID: -1,
		NormalAttackID:  template.NormalAttackID, // inherit from template
	}
	rt.Chars.BySlot[playerIdx][charIdx] = entry

	// Look up the char's self-scope counters. The char file is expected to
	// have declared CounterHP (required) and optionally Energy/Alive/Active.
	entry.HPCounterID = rt.findSelfCounter(playerIdx, charIdx, CounterHP)
	if entry.HPCounterID < 0 {
		return nil, fmt.Errorf("bind_char %q: char must declare a Self-scope %q counter", name, CounterHP)
	}
	entry.EnergyCounterID = rt.findSelfCounter(playerIdx, charIdx, CounterEnergy)
	entry.AliveCounterID = rt.findSelfCounter(playerIdx, charIdx, CounterAlive)
	entry.ActiveCounterID = rt.findSelfCounter(playerIdx, charIdx, CounterActive)

	g := rt.Game

	// Propagate element to engine-side CharInfo so the dice system
	// (normal-attack char-elem cost, tune target color) can read it
	// without crossing into the interp layer.
	if playerIdx >= 0 && playerIdx < 2 && charIdx >= 0 && charIdx < len(g.Players[playerIdx].Chars) {
		g.Players[playerIdx].Chars[charIdx].Element = engine.Element(entry.Element)
		g.Players[playerIdx].Chars[charIdx].SpecialtyCardRef = -1
	}

	g.RegisterCounterChar(entry.HPCounterID, playerIdx, charIdx)
	if entry.EnergyCounterID >= 0 {
		g.RegisterCounterChar(entry.EnergyCounterID, playerIdx, charIdx)
	}
	if entry.AliveCounterID >= 0 {
		g.RegisterCounterChar(entry.AliveCounterID, playerIdx, charIdx)
	}
	if entry.ActiveCounterID >= 0 {
		g.RegisterCounterChar(entry.ActiveCounterID, playerIdx, charIdx)
	}

	// Add skills to game
	for _, skillID := range entry.SkillIDs {
		g.AddSkill(playerIdx, charIdx, skillID)
	}

	// Store name metadata
	if g.CharNames == nil {
		g.CharNames = make(map[[2]int]string)
	}
	g.CharNames[[2]int{playerIdx, charIdx}] = name

	// Register death check (Go-native hook on HP counter)
	rt.registerDeathCheck(entry, playerIdx, charIdx)

	// Register alive transition detector: fires HookDeath / HookRevive on
	// alive 1→0 / 0→1 transitions. The engine-level death check (above) and
	// future revive effects both write via this counter, so the transition
	// hook catches all lifecycle events in one place.
	if entry.AliveCounterID >= 0 {
		rt.registerAliveTransitionHook(entry, playerIdx, charIdx)
		// Trigger initial spawn: alive 0 → 1 fires HookRevive.
		g.WriteCounter(entry.AliveCounterID, engine.OpSet, 1)
	}

	return nil, nil
}

// registerAliveTransitionHook wires a HookAfterWrite on the char's alive
// counter. When the value transitions 1→0 it fires HookDeath; 0→1 fires
// HookRevive. Initial-spawn semantics: char files declare alive with init=0
// and bind_char writes 1 to trigger on_revive (handled elsewhere).
func (rt *Runtime) registerAliveTransitionHook(entry *CharEntry, playerIdx, charIdx int) {
	aliveID := entry.AliveCounterID
	rt.registerHook(engine.Hook{
		Type:      engine.HookAfterWrite,
		CounterID: aliveID,
		Op:        engine.OpSet,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			var hookType engine.HookType
			switch {
			case ctx.Before == 1 && ctx.After == 0:
				hookType = engine.HookDeath
			case ctx.Before == 0 && ctx.After == 1:
				hookType = engine.HookRevive
			default:
				return
			}
			eCtx := &engine.EventContext{
				ActorPlayer: playerIdx,
				ActorChar:   charIdx,
			}
			g.FireEventHooks(hookType, eCtx)
		},
	})
}

func (rt *Runtime) builtinGetChar(args []Value) (Value, error) {
	name, _ := args[0].(string)
	template, ok := rt.Chars.ByName[name]
	if !ok {
		return nil, fmt.Errorf("unresolved_dependency:%s", name)
	}
	// Per-binding char-file load: return the slot-specific CharProxy so
	// closures capture the correct slot for mirror matches.
	pi := rt.CurrentOwnerPlayer
	ci := rt.CurrentOwnerChar
	if pi >= 0 && ci >= 0 {
		slot := rt.Chars.BySlot[pi][ci]
		if slot != nil && slot.Name == name {
			return &CharProxy{Entry: slot}, nil
		}
	}
	// Shared-load talent card: return a lazy proxy that resolves the
	// backing slot via (CurrentContextPlayer, name) at each method call.
	// This lets talent DSLs capture a single local reference while still
	// working correctly under mirror (both sides loaded once) + any-side-
	// acts semantics at hook-fire time.
	if rt.CurrentFileTalentOwner != "" {
		return &LazyCharProxy{Name: name}, nil
	}
	return &CharProxy{Entry: template}, nil
}

// --- Skill Builtins ---
