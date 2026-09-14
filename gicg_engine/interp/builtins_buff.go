package interp

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
)

func buffSlot(v Value, p, c int) int {
	switch r := v.(type) {
	case *CounterProxy:
		return r.ID
	case *PerPlayerProxy:
		if p >= 0 && p < 2 {
			return r.IDs[p]
		}
	case *PerCharProxy:
		if p >= 0 && p < 2 && c >= 0 && c < MaxChars {
			return r.IDs[p*MaxChars+c]
		}
	case *SelfSlotProxy:
		if p >= 0 && p < 2 && c >= 0 && c < MaxChars {
			return r.SlotIDs[p*MaxChars+c]
		}
	}
	return -1
}

func (rt *Runtime) builtinRegisterBuff(args []Value) (Value, error) {
	if len(args) < 1 {
		return nil, fmt.Errorf("register_buff requires counter")
	}
	_, ids, err := rt.hookOrder(args[0], engine.HookActionPrepare)
	if err != nil {
		return nil, err
	}
	var opts *Table
	if len(args) > 1 {
		opts, _ = args[1].(*Table)
	}
	for _, id := range ids {
		if id < 0 {
			continue
		}
		def := &rt.Game.BuffDefinitions[rt.Game.Counters[id].BuffIndex]
		p, c := rt.Game.GetCounterChar(id)[0], rt.Game.GetCounterChar(id)[1]
		if opts != nil {
			if v, ok := opts.Fields["independent"]; ok {
				def.Independent = ToBool(v)
				if def.Independent && (rt.Game.Counters[id].Init != 0 || rt.Game.Counters[id].Value != 0) {
					return nil, fmt.Errorf("independent template must start empty")
				}
			}
			if v, ok := opts.Fields["duration"]; ok {
				def.DurationID = buffSlot(v, p, c)
				if def.DurationID < 0 {
					return nil, fmt.Errorf("invalid buff duration binding")
				}
			}
			if v, ok := opts.Fields["progress"]; ok {
				def.ProgressID = buffSlot(v, p, c)
				if def.ProgressID < 0 {
					return nil, fmt.Errorf("invalid buff progress binding")
				}
			}
			if v, ok := opts.Fields["expires_round_end"]; ok {
				def.ExpiresRoundEnd = ToBool(v)
			}
			if v, ok := opts.Fields["remove_on_death"]; ok {
				def.RemoveOnDeath = ToBool(v)
			}
		}
	}
	return nil, nil
}
