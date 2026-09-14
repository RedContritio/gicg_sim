package interp

import (
	engine "gicg_mono/gicg_engine"
	"reflect"
)

// WalkAST visits syntax only; it never follows runtime environments or executes DSL.
func WalkAST(node Node, visit func(Node)) {
	var walk func(reflect.Value)
	walk = func(v reflect.Value) {
		if !v.IsValid() {
			return
		}
		if v.Kind() == reflect.Interface || v.Kind() == reflect.Pointer {
			if v.IsNil() {
				return
			}
			if v.Kind() == reflect.Pointer && v.CanInterface() {
				if n, ok := v.Interface().(Node); ok {
					visit(n)
				}
			}
			walk(v.Elem())
			return
		}
		switch v.Kind() {
		case reflect.Struct:
			for i := 0; i < v.NumField(); i++ {
				if v.Type().Field(i).IsExported() {
					walk(v.Field(i))
				}
			}
		case reflect.Slice:
			for i := 0; i < v.Len(); i++ {
				walk(v.Index(i))
			}
		}
	}
	// Interface nodes and pointer nodes denote the same node; visit only pointers.
	walk(reflect.ValueOf(node))
}

func counterIDs(value Value) []int {
	switch c := value.(type) {
	case *CounterProxy:
		return []int{c.ID}
	case *PerPlayerProxy:
		return c.AllCounterIDs()
	case *PerCharProxy:
		return c.AllCounterIDs()
	case *SelfSlotProxy:
		return c.AllCounterIDs()
	}
	return nil
}

func hookCounterAccess(fn *Closure) []engine.HookCounterAccess {
	var out []engine.HookCounterAccess
	seen := map[*MethodCall]bool{}
	WalkAST(fn.Body, func(n Node) {
		call, ok := n.(*MethodCall)
		if !ok || seen[call] {
			return
		}
		seen[call] = true
		ident, ok := call.Object.(*Ident)
		if !ok {
			return
		}
		value, ok := fn.Env.Get(ident.Name)
		if !ok {
			return
		}
		ids := counterIDs(value)
		if len(ids) == 0 {
			return
		}
		out = append(out, engine.HookCounterAccess{Symbol: ident.Name, Method: call.Method, Line: call.GetLine(), CounterIDs: ids})
	})
	return out
}
