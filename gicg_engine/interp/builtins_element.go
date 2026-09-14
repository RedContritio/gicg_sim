package interp

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
)

func (rt *Runtime) builtinApplyElement(args []Value) (Value, error) {
	if len(args) != 2 {
		return nil, fmt.Errorf("apply_element expects target and element")
	}
	elem, ok := ToInt(args[1])
	if !ok {
		return nil, fmt.Errorf("apply_element expects an element")
	}
	var ids []int
	if ch, ok := args[0].(*CharProxy); ok && ch != nil && ch.Entry != nil {
		ids = []int{ch.Entry.HPCounterID}
	} else if target, ok := ToInt(args[0]); ok {
		ids = rt.resolveTargetHP(target)
	} else {
		return nil, fmt.Errorf("apply_element expects a character or target enum")
	}
	for _, id := range ids {
		rt.Game.ApplyElement(id, engine.Element(elem))
	}
	return nil, nil
}

func (rt *Runtime) builtinHeal(args []Value) (Value, error) {
	target, _ := ToInt(args[0])
	value, _ := ToInt(args[1])

	hpIDs := rt.resolveTargetHP(target)
	if ch, ok := args[0].(*CharProxy); ok && ch != nil && ch.Entry != nil {
		hpIDs = nil
		if rt.Game.Players[ch.Entry.PlayerIdx].Chars[ch.Entry.CharIdx].Alive {
			hpIDs = []int{ch.Entry.HPCounterID}
		}
	}
	for _, hpID := range hpIDs {
		rt.Game.Heal(hpID, value)
	}
	return nil, nil
}
