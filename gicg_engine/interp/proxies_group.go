package interp

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
)

// CounterGroupProxy: all counters sharing a Tag. PerCharProxy +
// PerPlayerView live in proxies_bucket.go.

type CounterGroupProxy struct {
	Entries []*CounterEntry
}

func (cg *CounterGroupProxy) iterCounterIDs(rt *Runtime, pLo, pHi int, fn func(int)) {
	g := rt.Game
	for _, e := range cg.Entries {
		if e.OwnerPlayer >= 0 && (e.OwnerPlayer < pLo || e.OwnerPlayer > pHi) {
			continue
		}
		switch e.Scope {
		case ScopePerChar:
			pc := e.Ref.(*PerCharProxy)
			for p := pLo; p <= pHi; p++ {
				for c := 0; c < MaxChars; c++ {
					id := pc.IDs[p*MaxChars+c]
					if g.Counters[id].Value > 0 {
						fn(id)
					}
				}
			}
		case ScopePerPlayer:
			pp := e.Ref.(*PerPlayerProxy)
			for p := pLo; p <= pHi; p++ {
				if g.Counters[pp.IDs[p]].Value > 0 {
					fn(pp.IDs[p])
				}
			}
		case ScopeSelf, ScopeActiveStatus:
			// Self/ActiveStatus entries store per-slot IDs in SlotIDs;
			// entry.Ref is a summary SelfSlotProxy (OwnerName="").
			// Iterate only allocated slots (SlotIDs >= 0) within the
			// player range.
			for p := pLo; p <= pHi; p++ {
				for c := 0; c < MaxChars; c++ {
					id := e.SlotIDs[p*MaxChars+c]
					if id >= 0 && g.Counters[id].Value > 0 {
						fn(id)
					}
				}
			}
		default:
			cp := e.Ref.(*CounterProxy)
			if g.Counters[cp.ID].Value > 0 {
				fn(cp.ID)
			}
		}
	}
}

func (cg *CounterGroupProxy) resolvePlayerRange(rt *Runtime, args []Value) (int, int) {
	if len(args) == 0 {
		p := rt.CurrentContextPlayer
		return p, p
	}
	filter, ok := args[0].(*Table)
	if !ok {
		p := rt.CurrentContextPlayer
		return p, p
	}
	fp, ok := filter.Fields["player"]
	if !ok {
		p := rt.CurrentContextPlayer
		return p, p
	}
	pi, _ := ToInt(fp)
	if pi == PlayerOwn {
		p := rt.CurrentContextPlayer
		return p, p
	}
	if pi == PlayerEnemy {
		p := 1 - rt.CurrentContextPlayer
		return p, p
	}
	if pi == PlayerAll {
		return 0, 1
	}
	return pi, pi
}

func (cg *CounterGroupProxy) CallMethod(rt *Runtime, method string, args []Value) (Value, error) {
	g := rt.Game
	switch method {
	case "get":
		p := rt.CurrentContextPlayer
		count := 0
		cg.iterCounterIDs(rt, p, p, func(id int) { count++ })
		return count, nil
	case "set":
		p := rt.CurrentContextPlayer
		v, _ := ToInt(args[0])
		cg.iterCounterIDs(rt, p, p, func(id int) { g.WriteCounter(id, engine.OpSet, v) })
		return nil, nil
	case "add":
		p := rt.CurrentContextPlayer
		v, _ := ToInt(args[0])
		cg.iterCounterIDs(rt, p, p, func(id int) { g.WriteCounter(id, engine.OpAdd, v) })
		return nil, nil
	case "sub":
		p := rt.CurrentContextPlayer
		v, _ := ToInt(args[0])
		cg.iterCounterIDs(rt, p, p, func(id int) { g.WriteCounter(id, engine.OpSub, v) })
		return nil, nil
	case "get_at":
		pLo, pHi := cg.resolvePlayerRange(rt, args)
		count := 0
		cg.iterCounterIDs(rt, pLo, pHi, func(id int) { count++ })
		return count, nil
	case "set_at":
		pLo, pHi := cg.resolvePlayerRange(rt, args[:1])
		v, _ := ToInt(args[1])
		cg.iterCounterIDs(rt, pLo, pHi, func(id int) { g.WriteCounter(id, engine.OpSet, v) })
		return nil, nil
	case "add_at":
		pLo, pHi := cg.resolvePlayerRange(rt, args[:1])
		v, _ := ToInt(args[1])
		cg.iterCounterIDs(rt, pLo, pHi, func(id int) { g.WriteCounter(id, engine.OpAdd, v) })
		return nil, nil
	case "sub_at":
		pLo, pHi := cg.resolvePlayerRange(rt, args[:1])
		v, _ := ToInt(args[1])
		cg.iterCounterIDs(rt, pLo, pHi, func(id int) { g.WriteCounter(id, engine.OpSub, v) })
		return nil, nil
	default:
		return nil, fmt.Errorf("CounterGroupProxy: unknown method %q", method)
	}
}
