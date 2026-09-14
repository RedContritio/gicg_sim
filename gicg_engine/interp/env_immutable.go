package interp

import "fmt"

// Definitions captured by registered hooks are shared by all game clones.
// Mutable gameplay belongs in counters/zones, not in those lexical bindings.
// Hook-local scopes and tables created during execution remain writable.
func freezeDefinitions(root *Env) {
	envs := map[*Env]bool{}
	tables := map[*Table]bool{}
	var freezeEnv func(*Env)
	var freezeValue func(Value)
	freezeValue = func(v Value) {
		switch x := v.(type) {
		case *Table:
			if x == nil || tables[x] {
				return
			}
			tables[x] = true
			x.frozen = true
			for _, field := range x.Fields {
				freezeValue(field)
			}
		case *Closure:
			if x != nil {
				freezeEnv(x.Env)
			}
		}
	}
	freezeEnv = func(e *Env) {
		if e == nil || envs[e] {
			return
		}
		envs[e] = true
		e.frozen = true
		for i := int8(0); i < e.n; i++ {
			freezeValue(e.vals[i])
		}
		for _, v := range e.vars {
			freezeValue(v)
		}
		freezeEnv(e.parent)
	}
	freezeEnv(root)
}

func (e *Env) setDSL(name string, value Value) error {
	for scope := e; scope != nil; scope = scope.parent {
		found := false
		for i := int8(0); i < scope.n; i++ {
			found = found || scope.keys[i] == name
		}
		_, inMap := scope.vars[name]
		if found || inMap {
			if scope.frozen {
				return fmt.Errorf("cannot mutate shared rule binding %q; use a counter for gameplay state", name)
			}
			scope.SetLocal(name, value)
			return nil
		}
	}
	if e.frozen {
		return fmt.Errorf("cannot add shared rule binding %q", name)
	}
	e.SetLocal(name, value)
	return nil
}

func (t *Table) setDSL(key string, value Value) error {
	if t.frozen {
		return fmt.Errorf("cannot mutate shared rule table field %q; use a counter for gameplay state", key)
	}
	t.Fields[key] = value
	return nil
}
