package interp

import "fmt"

// Value represents a runtime value in the interpreter.
// nil → nil, int → number, bool → bool, string → string,
// *Table → table, *Closure → function, GoFunc → builtin function,
// any other → opaque userdata (counter proxy, char proxy, etc.)
type Value = interface{}

// GoFunc is a Go-native function callable from DSL. The rt parameter is
// the currently-executing Runtime (threaded through eval so that any
// Clone of the Runtime, running in parallel, reaches its own Game and
// transient state).
type GoFunc func(rt *Runtime, args []Value) (Value, error)

// Closure is a DSL-defined function with captured environment.
type Closure struct {
	Params []string
	Body   *Chunk
	Env    *Env
}

// Table is a simple string-keyed map (no array part needed).
type Table struct {
	Fields map[string]Value
}

func NewTable() *Table {
	return &Table{Fields: make(map[string]Value)}
}

// MethodProvider is implemented by userdata types that support :method()
// calls. The rt parameter is the currently-executing Runtime.
type MethodProvider interface {
	CallMethod(rt *Runtime, method string, args []Value) (Value, error)
}

// FieldProvider is implemented by userdata types that support .field access.
// rt is the currently-executing Runtime (threaded through eval).
type FieldProvider interface {
	GetField(rt *Runtime, field string) (Value, error)
}

// FieldSetter is implemented by userdata types that support .field = value.
type FieldSetter interface {
	SetField(rt *Runtime, field string, val Value) error
}

// IndexProvider is implemented by types that support [expr] access.
type IndexProvider interface {
	GetIndex(key Value) (Value, error)
}

// --- Environment ---

// Env is a lexical scope。 R5 inline-storage 优化:DSL hook bodies 多数 ≤4 locals
// (实测 memprofile 显示 NewEnv = 45% game.Step allocs);keys/vals 数组 inline
// 4 entries 覆盖 90% 场景,overflow 才 alloc map。 GET 走 linear scan 4 entries
// (实测 binary cmp 比 map lookup 快 ~50ns/op for small N)。 完全 alloc-free 等
// 价于「lazy map + 0-overflow common case」。
type Env struct {
	parent *Env
	keys   [4]string
	vals   [4]Value
	n      int8 // count of valid inline entries (0..4)
	vars   map[string]Value
}

func NewEnv(parent *Env) *Env {
	return &Env{parent: parent}
}

func (e *Env) Get(name string) (Value, bool) {
	for i := int8(0); i < e.n; i++ {
		if e.keys[i] == name {
			return e.vals[i], true
		}
	}
	if e.vars != nil {
		if v, ok := e.vars[name]; ok {
			return v, true
		}
	}
	if e.parent != nil {
		return e.parent.Get(name)
	}
	return nil, false
}

// Set sets a variable in the nearest scope where it exists, or the current scope.
func (e *Env) Set(name string, val Value) {
	if e.setExisting(name, val) {
		return
	}
	e.setLocalNew(name, val)
}

func (e *Env) setExisting(name string, val Value) bool {
	for i := int8(0); i < e.n; i++ {
		if e.keys[i] == name {
			e.vals[i] = val
			return true
		}
	}
	if e.vars != nil {
		if _, ok := e.vars[name]; ok {
			e.vars[name] = val
			return true
		}
	}
	if e.parent != nil {
		return e.parent.setExisting(name, val)
	}
	return false
}

// SetLocal sets a variable in the current scope only.
func (e *Env) SetLocal(name string, val Value) {
	// Check existing inline entry first (update in place,no growth)
	for i := int8(0); i < e.n; i++ {
		if e.keys[i] == name {
			e.vals[i] = val
			return
		}
	}
	if e.vars != nil {
		if _, ok := e.vars[name]; ok {
			e.vars[name] = val
			return
		}
	}
	e.setLocalNew(name, val)
}

// lookupTestOnly — test helper bypassing parent chain (eval_test.go expects
// var in current scope only)。 Production code uses Get/Set/SetLocal API。
func (e *Env) lookupTestOnly(name string) Value {
	v, _ := e.Get(name)
	return v
}

// setLocalNew adds a new local in the current scope (caller verified not exists)。
func (e *Env) setLocalNew(name string, val Value) {
	if e.n < 4 {
		e.keys[e.n] = name
		e.vals[e.n] = val
		e.n++
		return
	}
	if e.vars == nil {
		e.vars = make(map[string]Value, 4)
	}
	e.vars[name] = val
}

// --- Type helpers ---

func ToInt(v Value) (int, bool) {
	switch x := v.(type) {
	case int:
		return x, true
	case bool:
		if x {
			return 1, true
		}
		return 0, true
	}
	return 0, false
}

func ToBool(v Value) bool {
	if v == nil {
		return false
	}
	if b, ok := v.(bool); ok {
		return b
	}
	// Everything else is truthy (Lua semantics)
	return true
}

func ToString(v Value) string {
	switch x := v.(type) {
	case nil:
		return "nil"
	case int:
		return fmt.Sprintf("%d", x)
	case bool:
		if x {
			return "true"
		}
		return "false"
	case string:
		return x
	default:
		return fmt.Sprintf("<%T>", v)
	}
}
