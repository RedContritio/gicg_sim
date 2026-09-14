package interp

import "fmt"

func (rt *Runtime) registerBuffProgressBuiltins() {
	global := rt.Interp.Global
	global.SetLocal("selected_buff", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		if len(args) != 0 || rt.currentHookContext == nil || rt.currentHookContext.TargetBuffID == 0 {
			return nil, fmt.Errorf("selected_buff requires a selected buff target")
		}
		id := rt.currentHookContext.TargetBuffID
		counter, independent := rt.Game.SelectedBuffCounter(id)
		proxy := &CounterProxy{ID: counter}
		if independent {
			proxy.InstanceID = id
		}
		return proxy, nil
	}))
	global.SetLocal("buff_progress", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		if len(args) != 0 || rt.currentHookContext == nil || rt.currentHookContext.BuffID == 0 {
			return nil, fmt.Errorf("buff_progress requires an instance hook and no arguments")
		}
		return rt.Game.BuffProgress(rt.currentHookContext.BuffID)
	}))
	global.SetLocal("set_buff_progress", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		if len(args) != 1 || rt.currentHookContext == nil || rt.currentHookContext.BuffID == 0 {
			return nil, fmt.Errorf("set_buff_progress requires an instance hook and value")
		}
		value, ok := ToInt(args[0])
		if !ok {
			return nil, fmt.Errorf("buff progress must be an integer")
		}
		return nil, rt.Game.SetBuffProgress(rt.currentHookContext.BuffID, value)
	}))
	global.SetLocal("get_dice_total", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		if len(args) != 1 {
			return nil, fmt.Errorf("get_dice_total requires player")
		}
		p, ok := ToInt(args[0])
		if !ok {
			return nil, fmt.Errorf("dice player must be an integer")
		}
		p = rt.ResolvePlayer(p)
		if p < 0 || p > 1 {
			return nil, fmt.Errorf("invalid dice player")
		}
		total := 0
		for _, count := range rt.DicePool(p) {
			total += count
		}
		return total, nil
	}))
}
