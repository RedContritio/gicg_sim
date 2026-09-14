package interp

import "fmt"

// builtinCostReduce implements a total discount with restricted slots first.
func (rt *Runtime) builtinCostReduce(args []Value) (Value, error) {
	if len(args) != 2 {
		return nil, fmt.Errorf("cost_reduce expects context and amount")
	}
	cp, ok := args[0].(*CtxProxy)
	if !ok || cp == nil || cp.Ctx == nil {
		return nil, fmt.Errorf("cost_reduce requires event context")
	}
	amount, valid := ToInt(args[1])
	if !valid || amount < 0 {
		return nil, fmt.Errorf("cost_reduce requires nonnegative integer amount")
	}
	before := cp.Ctx.Cost.ClampedTotal()
	cp.Ctx.Cost.Reduce(amount)
	if amount > 0 && cp.Ctx.Cost.ClampedTotal() == before {
		return nil, nil
	}
	if cp.Ctx.CurrentHookID >= 0 {
		if cp.Ctx.AppliedMods == nil {
			cp.Ctx.AppliedMods = make(map[int]bool)
		}
		cp.Ctx.MarkApplied()
	}
	return nil, nil
}
