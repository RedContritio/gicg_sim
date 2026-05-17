package interp

import "fmt"

// Expression evaluation. Statement evaluation + the Interpreter type live
// in eval.go.

func (interp *Interpreter) eval(rt *Runtime, node Node, env *Env) (Value, error) {
	switch n := node.(type) {
	case *NumberLit:
		return n.Value, nil
	case *StringLit:
		return n.Value, nil
	case *BoolLit:
		return n.Value, nil
	case *NilLit:
		return nil, nil
	case *Ident:
		v, ok := env.Get(n.Name)
		if !ok {
			return nil, nil // undefined variables are nil in Lua
		}
		return v, nil
	case *BinOp:
		return interp.evalBinOp(rt, n, env)
	case *UnaryOp:
		return interp.evalUnaryOp(rt, n, env)
	case *Call:
		return interp.evalCall(rt, n, env)
	case *MethodCall:
		return interp.evalMethodCall(rt, n, env)
	case *DotAccess:
		return interp.evalDotAccess(rt, n, env)
	case *IndexAccess:
		return interp.evalIndexAccess(rt, n, env)
	case *TableCtor:
		return interp.evalTableCtor(rt, n, env)
	case *FuncLit:
		return &Closure{Params: n.Params, Body: n.Body, Env: env}, nil
	default:
		return nil, fmt.Errorf("line %d: unknown expression type %T", node.GetLine(), node)
	}
}

func (interp *Interpreter) evalBinOp(rt *Runtime, n *BinOp, env *Env) (Value, error) {
	// Short-circuit for and/or
	if n.Op == "and" {
		left, err := interp.eval(rt, n.Left, env)
		if err != nil {
			return nil, err
		}
		if !ToBool(left) {
			return left, nil
		}
		return interp.eval(rt, n.Right, env)
	}
	if n.Op == "or" {
		left, err := interp.eval(rt, n.Left, env)
		if err != nil {
			return nil, err
		}
		if ToBool(left) {
			return left, nil
		}
		return interp.eval(rt, n.Right, env)
	}

	left, err := interp.eval(rt, n.Left, env)
	if err != nil {
		return nil, err
	}
	right, err := interp.eval(rt, n.Right, env)
	if err != nil {
		return nil, err
	}

	// Equality (works on any type)
	switch n.Op {
	case "==":
		return valueEqual(rt, left, right), nil
	case "~=":
		return !valueEqual(rt, left, right), nil
	}

	// Arithmetic and comparison (integers)
	li, lok := ToInt(left)
	ri, rok := ToInt(right)
	if !lok || !rok {
		return nil, fmt.Errorf("line %d: arithmetic on non-number (%T %s %T)", n.GetLine(), left, n.Op, right)
	}
	switch n.Op {
	case "+":
		return li + ri, nil
	case "-":
		return li - ri, nil
	case "*":
		return li * ri, nil
	case "/":
		if ri == 0 {
			return nil, fmt.Errorf("line %d: division by zero", n.GetLine())
		}
		return li / ri, nil
	case "<":
		return li < ri, nil
	case ">":
		return li > ri, nil
	case "<=":
		return li <= ri, nil
	case ">=":
		return li >= ri, nil
	default:
		return nil, fmt.Errorf("line %d: unknown operator %q", n.GetLine(), n.Op)
	}
}

// valueEqual is the interpreter's == implementation. It short-circuits
// for identity (Go's ==) but also resolves LazySkillRef against the
// runtime's current context so "ctx.skill_index == lazy_skill"
// comparisons work in shared-load talent hooks where lazy_skill
// captures (char_name, skill_name) and needs to be materialized against
// whichever binding is active at hook-fire time.
func valueEqual(rt *Runtime, a, b Value) bool {
	la, lok := a.(*LazySkillRef)
	rb, rok := b.(*LazySkillRef)
	if lok {
		a = la.Resolve(rt)
	}
	if rok {
		b = rb.Resolve(rt)
	}
	return a == b
}

func (interp *Interpreter) evalUnaryOp(rt *Runtime, n *UnaryOp, env *Env) (Value, error) {
	val, err := interp.eval(rt, n.Expr, env)
	if err != nil {
		return nil, err
	}
	switch n.Op {
	case "not":
		return !ToBool(val), nil
	case "-":
		i, ok := ToInt(val)
		if !ok {
			return nil, fmt.Errorf("line %d: unary minus on non-number", n.GetLine())
		}
		return -i, nil
	default:
		return nil, fmt.Errorf("line %d: unknown unary op %q", n.GetLine(), n.Op)
	}
}

func (interp *Interpreter) evalCall(rt *Runtime, n *Call, env *Env) (Value, error) {
	fn, err := interp.eval(rt, n.Func, env)
	if err != nil {
		return nil, err
	}
	args, err := interp.evalArgs(rt, n.Args, env)
	if err != nil {
		return nil, err
	}

	switch f := fn.(type) {
	case GoFunc:
		return f(rt, args)
	case *Closure:
		return interp.callClosure(rt, f, args)
	default:
		return nil, fmt.Errorf("line %d: attempt to call a %T value", n.GetLine(), fn)
	}
}

func (interp *Interpreter) callClosure(rt *Runtime, cl *Closure, args []Value) (Value, error) {
	callEnv := NewEnv(cl.Env)
	for i, param := range cl.Params {
		if i < len(args) {
			callEnv.SetLocal(param, args[i])
		} else {
			callEnv.SetLocal(param, nil)
		}
	}
	err := interp.ExecChunk(rt, cl.Body, callEnv)
	if _, ok := err.(errReturn); ok {
		return nil, nil // return exits the function
	}
	return nil, err
}

func (interp *Interpreter) evalMethodCall(rt *Runtime, n *MethodCall, env *Env) (Value, error) {
	obj, err := interp.eval(rt, n.Object, env)
	if err != nil {
		return nil, err
	}
	args, err := interp.evalArgs(rt, n.Args, env)
	if err != nil {
		return nil, err
	}
	if mp, ok := obj.(MethodProvider); ok {
		return mp.CallMethod(rt, n.Method, args)
	}
	return nil, fmt.Errorf("line %d: %T has no method %q", n.GetLine(), obj, n.Method)
}

func (interp *Interpreter) evalDotAccess(rt *Runtime, n *DotAccess, env *Env) (Value, error) {
	obj, err := interp.eval(rt, n.Object, env)
	if err != nil {
		return nil, err
	}
	switch o := obj.(type) {
	case *Table:
		return o.Fields[n.Field], nil
	case FieldProvider:
		return o.GetField(rt, n.Field)
	default:
		return nil, fmt.Errorf("line %d: cannot access field %q on %T", n.GetLine(), n.Field, obj)
	}
}

func (interp *Interpreter) evalIndexAccess(rt *Runtime, n *IndexAccess, env *Env) (Value, error) {
	obj, err := interp.eval(rt, n.Object, env)
	if err != nil {
		return nil, err
	}
	idx, err := interp.eval(rt, n.Index, env)
	if err != nil {
		return nil, err
	}
	switch o := obj.(type) {
	case *Table:
		return o.Fields[ToString(idx)], nil
	case IndexProvider:
		return o.GetIndex(idx)
	default:
		return nil, fmt.Errorf("line %d: cannot index %T", n.GetLine(), obj)
	}
}

func (interp *Interpreter) evalTableCtor(rt *Runtime, n *TableCtor, env *Env) (Value, error) {
	t := NewTable()
	for _, f := range n.Fields {
		val, err := interp.eval(rt, f.Value, env)
		if err != nil {
			return nil, err
		}
		t.Fields[f.Key] = val
	}
	return t, nil
}

func (interp *Interpreter) evalArgs(rt *Runtime, nodes []Node, env *Env) ([]Value, error) {
	args := make([]Value, len(nodes))
	for i, n := range nodes {
		v, err := interp.eval(rt, n, env)
		if err != nil {
			return nil, err
		}
		args[i] = v
	}
	return args, nil
}
