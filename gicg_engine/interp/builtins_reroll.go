package interp

import "fmt"

func (rt *Runtime) builtinChooseReroll(args []Value) (Value, error) {
	if len(args) != 2 {
		return nil, fmt.Errorf("choose_reroll requires player and number of rolls")
	}
	p, validPlayer := ToInt(args[0])
	n, validCount := ToInt(args[1])
	if !validPlayer || !validCount || n <= 0 {
		return nil, fmt.Errorf("invalid choose_reroll arguments")
	}
	p = rt.ResolvePlayer(p)
	if p < 0 || p > 1 {
		return nil, fmt.Errorf("invalid choose_reroll player")
	}
	rt.Game.ChooseReroll(p, n)
	return nil, nil
}
