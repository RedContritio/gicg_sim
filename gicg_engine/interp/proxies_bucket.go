package interp

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
)

// Multi-slot counter proxies: PerCharProxy (2×MaxChars grid),
// PerPlayerView (CounterEntry.ByPlayer[p] narrowed view),
// CounterGroupProxy (all counters sharing a Tag).

type PerCharProxy struct {
	IDs     [2 * MaxChars]int // [p0c0, p0c1, p0c2, p1c0, p1c1, p1c2]
	RefKind int
}

func (pc *PerCharProxy) resolve(rt *Runtime) int {
	return pc.IDs[rt.CurrentContextPlayer*MaxChars+rt.CurrentOwnerChar]
}

func (pc *PerCharProxy) resolveAt(rt *Runtime, p, c int) int {
	rp := rt.ResolvePlayer(p)
	if rp < 0 || rp > 1 || c < 0 || c >= MaxChars {
		// Invalid indices (commonly ctx.target_* when no target resolved).
		// Return a sentinel so CallMethod can no-op cleanly.
		return -1
	}
	return pc.IDs[rp*MaxChars+c]
}

func (pc *PerCharProxy) CallMethod(rt *Runtime, method string, args []Value) (Value, error) {
	g := rt.Game
	switch method {
	case "get":
		raw := g.Counters[pc.resolve(rt)].Value
		if pc.RefKind != RefKindNone {
			return wrapRef(rt, pc.RefKind, raw), nil
		}
		return raw, nil
	case "set":
		v, err := unwrapRef(pc.RefKind, args[0])
		if err != nil {
			return nil, err
		}
		g.WriteCounter(pc.resolve(rt), engine.OpSet, v)
		return nil, nil
	case "add":
		if pc.RefKind != RefKindNone {
			return nil, refArithForbidden(pc.RefKind, "add")
		}
		v, _ := ToInt(args[0])
		g.WriteCounter(pc.resolve(rt), engine.OpAdd, v)
		return nil, nil
	case "sub":
		if pc.RefKind != RefKindNone {
			return nil, refArithForbidden(pc.RefKind, "sub")
		}
		v, _ := ToInt(args[0])
		g.WriteCounter(pc.resolve(rt), engine.OpSub, v)
		return nil, nil
	case "get_at":
		p, _ := ToInt(args[0])
		c, _ := ToInt(args[1])
		id := pc.resolveAt(rt, p, c)
		if id < 0 {
			if pc.RefKind != RefKindNone {
				return nil, nil
			}
			return 0, nil
		}
		raw := g.Counters[id].Value
		if pc.RefKind != RefKindNone {
			return wrapRef(rt, pc.RefKind, raw), nil
		}
		return raw, nil
	case "set_at":
		p, _ := ToInt(args[0])
		c, _ := ToInt(args[1])
		v, err := unwrapRef(pc.RefKind, args[2])
		if err != nil {
			return nil, err
		}
		if id := pc.resolveAt(rt, p, c); id >= 0 {
			g.WriteCounter(id, engine.OpSet, v)
		}
		return nil, nil
	case "add_at":
		if pc.RefKind != RefKindNone {
			return nil, refArithForbidden(pc.RefKind, "add_at")
		}
		p, _ := ToInt(args[0])
		c, _ := ToInt(args[1])
		v, _ := ToInt(args[2])
		if id := pc.resolveAt(rt, p, c); id >= 0 {
			g.WriteCounter(id, engine.OpAdd, v)
		}
		return nil, nil
	case "sub_at":
		if pc.RefKind != RefKindNone {
			return nil, refArithForbidden(pc.RefKind, "sub_at")
		}
		p, _ := ToInt(args[0])
		c, _ := ToInt(args[1])
		v, _ := ToInt(args[2])
		if id := pc.resolveAt(rt, p, c); id >= 0 {
			g.WriteCounter(id, engine.OpSub, v)
		}
		return nil, nil
	case "decay_all":
		if pc.RefKind != RefKindNone {
			return nil, refArithForbidden(pc.RefKind, "decay_all")
		}
		p, _ := ToInt(args[0])
		rp := rt.ResolvePlayer(p)
		for c := 0; c < MaxChars; c++ {
			id := pc.IDs[rp*MaxChars+c]
			if g.Counters[id].Value > 0 {
				g.WriteCounter(id, engine.OpSub, 1)
			}
		}
		return nil, nil
	case "fill_all":
		p, _ := ToInt(args[0])
		v, err := unwrapRef(pc.RefKind, args[1])
		if err != nil {
			return nil, err
		}
		rp := rt.ResolvePlayer(p)
		for c := 0; c < MaxChars; c++ {
			g.WriteCounter(pc.IDs[rp*MaxChars+c], engine.OpSet, v)
		}
		return nil, nil
	case "cmin":
		return g.Counters[pc.IDs[0]].Min, nil
	case "cmax":
		return g.Counters[pc.IDs[0]].Max, nil
	default:
		return nil, fmt.Errorf("PerCharProxy: unknown method %q", method)
	}
}

func (pc *PerCharProxy) AllCounterIDs() []int {
	return pc.IDs[:]
}

// --- PerPlayer View (bound to a specific Player constant) ---

type PerPlayerView struct {
	Inner *PerPlayerProxy
	Bind  int // Player.Own or Player.Enemy
}

func (v *PerPlayerView) resolvedID(rt *Runtime) int {
	return v.Inner.IDs[rt.ResolvePlayer(v.Bind)]
}

func (v *PerPlayerView) CallMethod(rt *Runtime, method string, args []Value) (Value, error) {
	g := rt.Game
	id := v.resolvedID(rt)
	switch method {
	case "get":
		return g.Counters[id].Value, nil
	case "set":
		val, _ := ToInt(args[0])
		g.WriteCounter(id, engine.OpSet, val)
		return nil, nil
	case "add":
		val, _ := ToInt(args[0])
		g.WriteCounter(id, engine.OpAdd, val)
		return nil, nil
	case "sub":
		val, _ := ToInt(args[0])
		g.WriteCounter(id, engine.OpSub, val)
		return nil, nil
	case "cmin":
		return g.Counters[v.Inner.IDs[0]].Min, nil
	case "cmax":
		return g.Counters[v.Inner.IDs[0]].Max, nil
	default:
		return nil, fmt.Errorf("PerPlayerView: unknown method %q", method)
	}
}

// CounterGroupProxy lives in proxies_group.go.
