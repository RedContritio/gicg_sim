package interp

import "fmt"

func (rt *Runtime) registerBuffInstanceBuiltins() {
	global := rt.Interp.Global
	spawn := func(rt *Runtime, args []Value) (Value, error) {
		if len(args) != 3 && len(args) != 5 {
			return nil, fmt.Errorf("spawn_buff(template,value,duration[,player,char])")
		}
		value, valid := ToInt(args[1])
		duration, validDuration := ToInt(args[2])
		if !valid || !validDuration {
			return nil, fmt.Errorf("buff quantities must be integers")
		}
		p, c := rt.CurrentContextPlayer, -1
		if len(args) == 5 {
			var okP, okC bool
			p, okP = ToInt(args[3])
			c, okC = ToInt(args[4])
			if !okP || !okC {
				return nil, fmt.Errorf("invalid buff owner")
			}
		} else if p >= 0 && p < 2 {
			c = rt.Game.Players[p].ActiveChar
		}
		if p < 0 || p > 1 || c < -1 || c >= MaxChars {
			return nil, fmt.Errorf("invalid buff owner")
		}

		id := buffSlot(args[0], p, c)
		if id < 0 || rt.Game.Counters[id].BuffIndex < 0 {
			return nil, fmt.Errorf("spawn_buff requires registered template")
		}
		return rt.Game.SpawnBuff(rt.Game.Counters[id].BuffIndex, value, duration)
	}
	global.SetLocal("spawn_buff", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		_, err := spawn(rt, args)
		return nil, err // lifecycle IDs remain internal
	}))
	global.SetLocal("spawn_support_buff", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		ctx := rt.currentHookContext
		if len(args) != 3 || ctx == nil || ctx.ActorPlayer < 0 || ctx.ActorPlayer > 1 {
			return nil, fmt.Errorf("spawn_support_buff requires card-play context and template,value,duration")
		}
		if _, ok := args[0].(*PerPlayerProxy); !ok {
			return nil, fmt.Errorf("spawn_support_buff requires a PerPlayer template")
		}
		p := ctx.ActorPlayer
		supports := rt.Game.Players[p].Supports
		index := len(supports) - 1
		if index < 0 || supports[index].Ref != ctx.CardRef || supports[index].BuffID != 0 {
			return nil, fmt.Errorf("spawn_support_buff requires a newly entered unbound support")
		}
		ownerArgs := append(append([]Value(nil), args...), p, -1)
		id, err := spawn(rt, ownerArgs)
		if err != nil {
			return nil, err
		}
		rt.Game.Players[p].Supports[index].BuffID = id.(uint64)
		return nil, nil
	}))
	global.SetLocal("buff_duration", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		if rt.currentHookContext == nil || rt.currentHookContext.BuffID == 0 {
			return nil, fmt.Errorf("buff_duration requires an instance hook")
		}
		return rt.Game.BuffRemaining(rt.currentHookContext.BuffID), nil
	}))
	global.SetLocal("set_buff_duration", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		if len(args) != 1 || rt.currentHookContext == nil || rt.currentHookContext.BuffID == 0 {
			return nil, fmt.Errorf("set_buff_duration requires instance hook and duration")
		}
		duration, ok := ToInt(args[0])
		if !ok {
			return nil, fmt.Errorf("duration must be integer")
		}
		return nil, rt.Game.SetBuffRemaining(rt.currentHookContext.BuffID, duration)
	}))
}
