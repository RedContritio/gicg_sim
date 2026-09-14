package interp

import "fmt"

// errReturn is a sentinel used to implement early return.
type errReturn struct{}

func (errReturn) Error() string { return "return" }

// Interpreter executes DSL AST nodes. Stateless between executions: all
// per-game state lives on *Runtime, which is threaded through every eval
// method so that a cloned Runtime can drive its own execution without
// affecting the original.
type Interpreter struct {
	Global *Env // global environment with builtins and enums
}

func NewInterpreter() *Interpreter {
	return &Interpreter{
		Global: NewEnv(nil),
	}
}

// ExecChunk executes a chunk in the given environment using rt as the
// current runtime. All proxies, hook bodies, and method calls resolve
// their mutable game state through rt.
func (interp *Interpreter) ExecChunk(rt *Runtime, chunk *Chunk, env *Env) error {
	for _, stmt := range chunk.Stmts {
		if err := interp.execStmt(rt, stmt, env); err != nil {
			return err
		}
	}
	return nil
}

func (interp *Interpreter) execStmt(rt *Runtime, node Node, env *Env) error {
	switch n := node.(type) {
	case *LocalDecl:
		return interp.execLocalDecl(rt, n, env)
	case *Assign:
		return interp.execAssign(rt, n, env)
	case *IfStmt:
		return interp.execIf(rt, n, env)
	case *ReturnStmt:
		return errReturn{}
	case *ExprStmt:
		_, err := interp.eval(rt, n.Expr, env)
		return err
	default:
		return fmt.Errorf("line %d: unknown statement type %T", node.GetLine(), node)
	}
}

func (interp *Interpreter) execLocalDecl(rt *Runtime, n *LocalDecl, env *Env) error {
	vals := make([]Value, len(n.Names))
	for i, expr := range n.Exprs {
		v, err := interp.eval(rt, expr, env)
		if err != nil {
			return err
		}
		if i < len(vals) {
			vals[i] = v
		}
	}
	for i, name := range n.Names {
		if i < len(vals) {
			env.SetLocal(name, vals[i])
		} else {
			env.SetLocal(name, nil)
		}
	}
	return nil
}

func (interp *Interpreter) execAssign(rt *Runtime, n *Assign, env *Env) error {
	val, err := interp.eval(rt, n.Value, env)
	if err != nil {
		return err
	}
	switch target := n.Target.(type) {
	case *Ident:
		return env.setDSL(target.Name, val)
	case *DotAccess:
		obj, err := interp.eval(rt, target.Object, env)
		if err != nil {
			return err
		}
		switch o := obj.(type) {
		case *Table:
			return o.setDSL(target.Field, val)
		case FieldSetter:
			return o.SetField(rt, target.Field, val)
		default:
			return fmt.Errorf("line %d: cannot set field on %T", n.GetLine(), obj)
		}
	case *IndexAccess:
		obj, err := interp.eval(rt, target.Object, env)
		if err != nil {
			return err
		}
		idx, err := interp.eval(rt, target.Index, env)
		if err != nil {
			return err
		}
		t, ok := obj.(*Table)
		if !ok {
			return fmt.Errorf("line %d: cannot index %T", n.GetLine(), obj)
		}
		return t.setDSL(ToString(idx), val)
	default:
		return fmt.Errorf("line %d: cannot assign to %T", n.GetLine(), n.Target)
	}
}

func (interp *Interpreter) execIf(rt *Runtime, n *IfStmt, env *Env) error {
	cond, err := interp.eval(rt, n.Cond, env)
	if err != nil {
		return err
	}
	if ToBool(cond) {
		return interp.ExecChunk(rt, n.Body, env)
	}
	for _, ei := range n.ElseIfs {
		cond, err := interp.eval(rt, ei.Cond, env)
		if err != nil {
			return err
		}
		if ToBool(cond) {
			return interp.ExecChunk(rt, ei.Body, env)
		}
	}
	if n.ElseBody != nil {
		return interp.ExecChunk(rt, n.ElseBody, env)
	}
	return nil
}

// ExecFile parses and executes a DSL source in a sandboxed environment.
func (interp *Interpreter) ExecFile(rt *Runtime, src []byte, env *Env) error {
	tokens, err := Tokenize(src)
	if err != nil {
		return err
	}
	chunk, err := Parse(tokens)
	if err != nil {
		return err
	}
	return interp.ExecChunk(rt, chunk, env)
}

// Expression evaluation lives in eval_expr.go:
//   eval, evalBinOp, evalUnaryOp, evalCall, callClosure, evalMethodCall,
//   evalDotAccess, evalIndexAccess, evalTableCtor, evalArgs, valueEqual.
