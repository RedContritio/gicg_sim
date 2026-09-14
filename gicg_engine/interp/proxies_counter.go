package interp

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
)

// Per-slot counter proxies: CounterProxy (single fixed counter ID),
// PerPlayerProxy (pair of player-keyed counters), SelfSlotProxy
// (shared-load talent proxy that resolves its counter slot via
// find_slot at each access).

type CounterProxy struct {
	InstanceID uint64 // only a write callback's concrete instance argument
	ID         int
	RefKind    int
}

func (c *CounterProxy) CallMethod(rt *Runtime, method string, args []Value) (Value, error) {
	g := rt.Game
	if c.InstanceID != 0 {
		frame := g.CurrentEvent()
		frame.BuffID, frame.BuffCounterID = c.InstanceID, c.ID
		g.PushEvent(frame)
		defer g.PopEvent()
		defer g.DrainDeferred()
	}
	// Null proxy (ID < 0): returned by LazyCharProxy / LazyCharProxy-derived
	// counter accessors (e.g. hp(), energy()) when the current runtime
	// context player has no char matching the lazy's target name. Reads
	// return zero / nil ref; writes no-op. Matches the SelfSlotProxy
	// "slot not allocated" semantics so talent hooks that pass the active
	// guard handle cross-player reads uniformly.
	if c.ID < 0 {
		switch method {
		case "get":
			if c.RefKind != RefKindNone {
				return nil, nil
			}
			return 0, nil
		case "set", "add", "sub":
			return nil, nil
		case "cmin", "cmax":
			return 0, nil
		default:
			return nil, fmt.Errorf("CounterProxy(null): unknown method %q", method)
		}
	}
	switch method {
	case "get":
		raw := g.ReadCounter(c.ID)
		if c.RefKind != RefKindNone {
			return wrapRef(rt, c.RefKind, raw), nil
		}
		return raw, nil
	case "set":
		v, err := unwrapRef(c.RefKind, args[0])
		if err != nil {
			return nil, err
		}
		g.WriteCounter(c.ID, engine.OpSet, v)
		return nil, nil
	case "add":
		if c.RefKind != RefKindNone {
			return nil, refArithForbidden(c.RefKind, "add")
		}
		v, _ := ToInt(args[0])
		g.WriteCounter(c.ID, engine.OpAdd, v)
		return nil, nil
	case "sub":
		if c.RefKind != RefKindNone {
			return nil, refArithForbidden(c.RefKind, "sub")
		}
		v, _ := ToInt(args[0])
		g.WriteCounter(c.ID, engine.OpSub, v)
		return nil, nil
	case "cmin":
		return g.Counters[c.ID].Min, nil
	case "cmax":
		return g.Counters[c.ID].Max, nil
	default:
		return nil, fmt.Errorf("CounterProxy: unknown method %q", method)
	}
}

// --- PerPlayer Counter Proxy ---

type PerPlayerProxy struct {
	IDs     [2]int // counter IDs for player 0 and 1
	RefKind int
}

func (pp *PerPlayerProxy) resolve(rt *Runtime) int {
	return pp.IDs[rt.CurrentContextPlayer]
}

func (pp *PerPlayerProxy) resolveAt(rt *Runtime, args []Value) int {
	p, _ := ToInt(args[0])
	return pp.IDs[rt.ResolvePlayer(p)]
}

func (pp *PerPlayerProxy) CallMethod(rt *Runtime, method string, args []Value) (Value, error) {
	g := rt.Game
	switch method {
	case "get":
		raw := g.ReadCounter(pp.resolve(rt))
		if pp.RefKind != RefKindNone {
			return wrapRef(rt, pp.RefKind, raw), nil
		}
		return raw, nil
	case "set":
		v, err := unwrapRef(pp.RefKind, args[0])
		if err != nil {
			return nil, err
		}
		g.WriteCounter(pp.resolve(rt), engine.OpSet, v)
		return nil, nil
	case "add":
		if pp.RefKind != RefKindNone {
			return nil, refArithForbidden(pp.RefKind, "add")
		}
		v, _ := ToInt(args[0])
		g.WriteCounter(pp.resolve(rt), engine.OpAdd, v)
		return nil, nil
	case "sub":
		if pp.RefKind != RefKindNone {
			return nil, refArithForbidden(pp.RefKind, "sub")
		}
		v, _ := ToInt(args[0])
		g.WriteCounter(pp.resolve(rt), engine.OpSub, v)
		return nil, nil
	case "get_at":
		id := pp.resolveAt(rt, args)
		raw := g.ReadCounter(id)
		if pp.RefKind != RefKindNone {
			return wrapRef(rt, pp.RefKind, raw), nil
		}
		return raw, nil
	case "set_at":
		id := pp.resolveAt(rt, args)
		v, err := unwrapRef(pp.RefKind, args[1])
		if err != nil {
			return nil, err
		}
		g.WriteCounter(id, engine.OpSet, v)
		return nil, nil
	case "add_at":
		if pp.RefKind != RefKindNone {
			return nil, refArithForbidden(pp.RefKind, "add_at")
		}
		id := pp.resolveAt(rt, args)
		v, _ := ToInt(args[1])
		g.WriteCounter(id, engine.OpAdd, v)
		return nil, nil
	case "sub_at":
		if pp.RefKind != RefKindNone {
			return nil, refArithForbidden(pp.RefKind, "sub_at")
		}
		id := pp.resolveAt(rt, args)
		v, _ := ToInt(args[1])
		g.WriteCounter(id, engine.OpSub, v)
		return nil, nil
	case "cmin":
		return g.Counters[pp.IDs[0]].Min, nil
	case "cmax":
		return g.Counters[pp.IDs[0]].Max, nil
	default:
		return nil, fmt.Errorf("PerPlayerProxy: unknown method %q", method)
	}
}

// AllCounterIDs returns all counter IDs for write hook registration.
func (pp *PerPlayerProxy) AllCounterIDs() []int {
	return pp.IDs[:]
}

// --- SelfSlot Counter Proxy (shared-load talent reference to Scope.Self) ---
//
// SelfSlotProxy resolves Scope.Self / Scope.ActiveStatus counter access
// from a shared-load context (typically a talent card) by looking up
// the slot of OwnerName in the runtime's current context player, then
// reading/writing the counter allocated at that slot.
//
// Storage: SlotIDs is a 2*MaxChars table where entry (p*MaxChars+c)
// is the counter ID allocated for (player p, char slot c), or -1 if
// no counter was allocated at that slot (meaning the player has no
// char named OwnerName). The table is populated either by per-binding
// char-file declares (one slot per declare) or by shared-load talent
// declares (all slots where OwnerName's char binding exists).
//
// Access semantics:
//   - :get() / :set() / :add() / :sub() resolve via
//     (CurrentContextPlayer, find_slot(CurrentContextPlayer, OwnerName))
//   - If that slot has no counter (-1), read returns 0 and writes no-op,
//     matching the semantics "this player doesn't have the talent's
//     owner char".
type SelfSlotProxy struct {
	SlotIDs   [2 * MaxChars]int // -1 where no counter allocated
	OwnerName string
	RefKind   int
}

// resolve returns the counter ID for the current runtime context, or
// -1 if the current player has no char matching OwnerName.
func (sp *SelfSlotProxy) resolve(rt *Runtime) int {
	p := rt.CurrentContextPlayer
	if p < 0 || p > 1 {
		return -1
	}
	for c := 0; c < MaxChars; c++ {
		slot := rt.Chars.BySlot[p][c]
		if slot != nil && slot.Name == sp.OwnerName {
			return sp.SlotIDs[p*MaxChars+c]
		}
	}
	return -1
}

func (sp *SelfSlotProxy) CallMethod(rt *Runtime, method string, args []Value) (Value, error) {
	g := rt.Game
	id := sp.resolve(rt)
	switch method {
	case "get":
		if id < 0 {
			if sp.RefKind != RefKindNone {
				return nil, nil
			}
			return 0, nil
		}
		raw := g.ReadCounter(id)
		if sp.RefKind != RefKindNone {
			return wrapRef(rt, sp.RefKind, raw), nil
		}
		return raw, nil
	case "set":
		if id < 0 {
			return nil, nil
		}
		v, err := unwrapRef(sp.RefKind, args[0])
		if err != nil {
			return nil, err
		}
		g.WriteCounter(id, engine.OpSet, v)
		return nil, nil
	case "add":
		if sp.RefKind != RefKindNone {
			return nil, refArithForbidden(sp.RefKind, "add")
		}
		if id < 0 {
			return nil, nil
		}
		v, _ := ToInt(args[0])
		g.WriteCounter(id, engine.OpAdd, v)
		return nil, nil
	case "sub":
		if sp.RefKind != RefKindNone {
			return nil, refArithForbidden(sp.RefKind, "sub")
		}
		if id < 0 {
			return nil, nil
		}
		v, _ := ToInt(args[0])
		g.WriteCounter(id, engine.OpSub, v)
		return nil, nil
	case "cmin":
		// cmin/cmax are per-entry constants; read from any allocated slot.
		for _, sid := range sp.SlotIDs {
			if sid >= 0 {
				return g.Counters[sid].Min, nil
			}
		}
		return 0, nil
	case "cmax":
		for _, sid := range sp.SlotIDs {
			if sid >= 0 {
				return g.Counters[sid].Max, nil
			}
		}
		return 0, nil
	default:
		return nil, fmt.Errorf("SelfSlotProxy: unknown method %q", method)
	}
}

// AllCounterIDs returns the allocated counter IDs (skipping -1 slots).
// Used by write-hook registration so on_before_write / on_after_write
// for a SelfSlotProxy fires on every slot that actually has a counter.
func (sp *SelfSlotProxy) AllCounterIDs() []int {
	out := make([]int, 0, 2*MaxChars)
	for _, id := range sp.SlotIDs {
		if id >= 0 {
			out = append(out, id)
		}
	}
	return out
}

// --- PerChar Counter Proxy ---
