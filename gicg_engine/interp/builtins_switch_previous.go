package interp

import "fmt"

// builtinForceSwitchPrevious cycles backwards, skipping defeated characters.
// ForceSwitchTo owns event dispatch and resumable effect execution.
func (rt *Runtime) builtinForceSwitchPrevious(args []Value) (Value, error) {
	if len(args) != 1 {
		return nil, fmt.Errorf("force_switch_previous: expected player")
	}
	p, ok := ToInt(args[0])
	if !ok {
		return nil, fmt.Errorf("force_switch_previous: player must be integer")
	}
	rp := rt.ResolvePlayer(p)
	if rp < 0 || rp >= len(rt.Game.Players) {
		return nil, fmt.Errorf("force_switch_previous: invalid player %d", rp)
	}
	pl := &rt.Game.Players[rp]
	n := len(pl.Chars)
	if pl.ActiveChar < 0 || pl.ActiveChar >= n {
		return nil, nil
	}
	for offset := 1; offset < n; offset++ {
		index := (pl.ActiveChar - offset + n) % n
		if pl.Chars[index].Alive {
			rt.Game.ForceSwitchTo(rp, index)
			break
		}
	}
	return nil, nil
}
