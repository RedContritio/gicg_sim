package interp

import "fmt"

func (rt *Runtime) registerEnergyTransferBuiltins() {
	player := func(rt *Runtime, v Value) (int, error) {
		p, ok := ToInt(v)
		if !ok {
			return -1, fmt.Errorf("energy transfer player must be integer")
		}
		p = rt.ResolvePlayer(p)
		if p < 0 || p > 1 {
			return -1, fmt.Errorf("invalid energy transfer player")
		}
		return p, nil
	}
	background := func(rt *Runtime, p int) []int {
		var ids []int
		for slot, ch := range rt.Game.Players[p].Chars {
			if ch.Alive && slot != rt.Game.Players[p].ActiveChar {
				ids = append(ids, rt.Chars.BySlot[p][slot].EnergyCounterID)
			}
		}
		return ids
	}
	rt.Interp.Global.SetLocal("background_energy", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		if len(args) != 1 {
			return nil, fmt.Errorf("background_energy requires player")
		}
		p, err := player(rt, args[0])
		if err != nil {
			return nil, err
		}
		total := 0
		for _, id := range background(rt, p) {
			total += rt.Game.ReadCounter(id)
		}
		return total, nil
	}))
	rt.Interp.Global.SetLocal("transfer_energy_from_background", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		if len(args) != 3 {
			return nil, fmt.Errorf("transfer_energy_from_background requires player, amount per source, source limit")
		}
		p, err := player(rt, args[0])
		if err != nil {
			return nil, err
		}
		amount, ok := ToInt(args[1])
		limit, valid := ToInt(args[2])
		if !ok || !valid || amount < 0 || limit < 0 {
			return nil, fmt.Errorf("invalid energy transfer quantities")
		}
		active := rt.Game.Players[p].ActiveChar
		if active < 0 || !rt.Game.Players[p].Chars[active].Alive {
			return nil, fmt.Errorf("energy transfer requires a living active character")
		}
		target := rt.Chars.BySlot[p][active].EnergyCounterID
		total, sources := 0, 0
		// Snapshot donors before writes; transfer does not stop at the receiver's cap.
		for _, id := range background(rt, p) {
			before := rt.Game.ReadCounter(id)
			if before <= 0 || sources >= limit {
				continue
			}
			rt.Game.ConsumeEnergy(id, min(amount, before))
			total += max(0, before-rt.Game.ReadCounter(id))
			sources++
		}
		if total > 0 {
			rt.Game.GainEnergy(target, total)
		}
		return nil, nil
	}))
}
