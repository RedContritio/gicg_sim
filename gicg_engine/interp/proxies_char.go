package interp

import (
	"fmt"
)

// Char / Skill proxies — DSL handles for character entries and
// skill refs. Two families:
//
//  - CharProxy + SkillRef: per-binding char handles captured at
//    character-DSL load time. CharProxy.Entry points directly at
//    the per-slot CharEntry.
//  - LazyCharProxy + LazySkillRef: shared-load talent handles that
//    resolve to a concrete per-slot entry at each call via
//    (CurrentContextPlayer, Name). Used by talent cards whose DSL
//    is loaded globally once but can be attached to either side of
//    a mirror match.

// --- Char Proxy ---

type CharProxy struct {
	Entry *CharEntry
}

func (cp *CharProxy) CallMethod(rt *Runtime, method string, args []Value) (Value, error) {
	g := rt.Game
	switch method {
	case "hp":
		return &CounterProxy{ID: cp.Entry.HPCounterID}, nil
	case "energy":
		return &CounterProxy{ID: cp.Entry.EnergyCounterID}, nil
	case "alive":
		return g.Counters[cp.Entry.AliveCounterID].Value > 0, nil
	case "name":
		return cp.Entry.Name, nil
	case "element":
		return cp.Entry.Element, nil
	case "weapon":
		return cp.Entry.Weapon, nil
	case "owner_player":
		return cp.Entry.PlayerIdx, nil
	case "owner_char":
		return cp.Entry.CharIdx, nil
	default:
		return nil, fmt.Errorf("CharProxy: unknown method %q", method)
	}
}

func (cp *CharProxy) GetField(rt *Runtime, field string) (Value, error) {
	switch field {
	case "hp":
		return &CounterProxy{ID: cp.Entry.HPCounterID}, nil
	case "energy":
		return &CounterProxy{ID: cp.Entry.EnergyCounterID}, nil
	case "element":
		return cp.Entry.Element, nil
	case "weapon":
		return cp.Entry.Weapon, nil
	case "normal_attack":
		// Returns the *SkillRef of this char's normal attack
		// (identified at declare_skill time as the first skill whose
		// cost has Any > 0), or nil if no such skill was declared.
		if cp.Entry.NormalAttackID < 0 {
			return nil, nil
		}
		if ref, ok := rt.Skills.ByID[cp.Entry.NormalAttackID]; ok {
			return ref, nil
		}
		return nil, nil
	case "_skills":
		// Returns a 1-indexed table of *SkillRef for this char's
		// registered skills, in declaration order.
		t := NewTable()
		for i, id := range cp.Entry.SkillIDs {
			if ref, ok := rt.Skills.ByID[id]; ok {
				t.Fields[ToString(i+1)] = ref
			}
		}
		return t, nil
	default:
		return nil, fmt.Errorf("CharProxy: unknown field %q", field)
	}
}

// --- Lazy Char Proxy (shared-load talent reference to a char) ---
//
// LazyCharProxy mirrors CharProxy's surface but resolves its backing
// CharEntry at each call via (CurrentContextPlayer, Name). Used by
// shared-load talent card DSLs where the talent file captures a char
// reference at load time (local 赤蝶 = get_char("赤蝶")) but the
// actual slot it maps to depends on which side is acting at hook-fire
// time. If the current context player has no char matching Name,
// method results are null / no-op.
type LazyCharProxy struct {
	Name string
}

// resolveEntry returns the per-slot CharEntry for the current runtime
// context, or nil if the current context player has no char named
// LazyCharProxy.Name.
func (lp *LazyCharProxy) resolveEntry(rt *Runtime) *CharEntry {
	p := rt.CurrentContextPlayer
	if p < 0 || p > 1 {
		return nil
	}
	for c := 0; c < MaxChars; c++ {
		slot := rt.Chars.BySlot[p][c]
		if slot != nil && slot.Name == lp.Name {
			return slot
		}
	}
	return nil
}

func (lp *LazyCharProxy) CallMethod(rt *Runtime, method string, args []Value) (Value, error) {
	entry := lp.resolveEntry(rt)
	switch method {
	case "name":
		return lp.Name, nil
	case "owner_player":
		if entry != nil {
			return entry.PlayerIdx, nil
		}
		return rt.CurrentContextPlayer, nil
	case "owner_char":
		if entry != nil {
			return entry.CharIdx, nil
		}
		return -1, nil
	case "element":
		if entry != nil {
			return entry.Element, nil
		}
		if tpl, ok := rt.Chars.ByName[lp.Name]; ok {
			return tpl.Element, nil
		}
		return 0, nil
	case "weapon":
		if entry != nil {
			return entry.Weapon, nil
		}
		if tpl, ok := rt.Chars.ByName[lp.Name]; ok {
			return tpl.Weapon, nil
		}
		return 0, nil
	case "hp":
		if entry != nil {
			return &CounterProxy{ID: entry.HPCounterID}, nil
		}
		return &CounterProxy{ID: -1}, nil
	case "energy":
		if entry != nil {
			return &CounterProxy{ID: entry.EnergyCounterID}, nil
		}
		return &CounterProxy{ID: -1}, nil
	case "alive":
		if entry == nil || entry.AliveCounterID < 0 {
			return false, nil
		}
		return rt.Game.Counters[entry.AliveCounterID].Value > 0, nil
	default:
		return nil, fmt.Errorf("LazyCharProxy: unknown method %q", method)
	}
}

func (lp *LazyCharProxy) GetField(rt *Runtime, field string) (Value, error) {
	entry := lp.resolveEntry(rt)
	switch field {
	case "hp":
		if entry != nil {
			return &CounterProxy{ID: entry.HPCounterID}, nil
		}
		return &CounterProxy{ID: -1}, nil
	case "energy":
		if entry != nil {
			return &CounterProxy{ID: entry.EnergyCounterID}, nil
		}
		return &CounterProxy{ID: -1}, nil
	case "element":
		if entry != nil {
			return entry.Element, nil
		}
		if tpl, ok := rt.Chars.ByName[lp.Name]; ok {
			return tpl.Element, nil
		}
		return 0, nil
	case "weapon":
		if entry != nil {
			return entry.Weapon, nil
		}
		if tpl, ok := rt.Chars.ByName[lp.Name]; ok {
			return tpl.Weapon, nil
		}
		return 0, nil
	case "normal_attack":
		if entry != nil && entry.NormalAttackID >= 0 {
			if ref, ok := rt.Skills.ByID[entry.NormalAttackID]; ok {
				return ref, nil
			}
		}
		return nil, nil
	default:
		return nil, fmt.Errorf("LazyCharProxy: unknown field %q", field)
	}
}

// --- Lazy Skill Ref (shared-load talent reference to a char's skill) ---
//
// LazySkillRef mirrors *SkillRef's role as a DSL-level skill handle,
// but resolves to a concrete *SkillRef at each use via
// (CurrentContextPlayer, CharName, SkillName). Talent DSL captures
// `local 蝶火_skill = get_skill(赤蝶, "蝶火")` at load time (when
// CurrentContextPlayer = -1) and uses the captured reference in
// `ctx.skill_index == 蝶火_skill` comparisons and `invoke_skill(蝶火_skill)`
// calls at hook-fire time (when CurrentContextPlayer is set).
//
// Equality with a concrete *SkillRef is handled by the interpreter's
// valueEqual helper, which calls LazySkillRef.Resolve. Invocation is
// handled by builtinInvokeSkill, which calls Resolve before dispatch.
type LazySkillRef struct {
	CharName  string
	SkillName string
}

// Resolve returns the concrete *SkillRef for the current runtime
// context, or nil if no matching skill is registered (e.g. the current
// context player has no char named CharName).
func (ls *LazySkillRef) Resolve(rt *Runtime) *SkillRef {
	p := rt.CurrentContextPlayer
	if p < 0 || p > 1 {
		return nil
	}
	for c := 0; c < MaxChars; c++ {
		slot := rt.Chars.BySlot[p][c]
		if slot == nil || slot.Name != ls.CharName {
			continue
		}
		skillID, ok := slot.Skills[ls.SkillName]
		if !ok {
			return nil
		}
		if ref, ok := rt.Skills.ByID[skillID]; ok {
			return ref
		}
		return nil
	}
	return nil
}
