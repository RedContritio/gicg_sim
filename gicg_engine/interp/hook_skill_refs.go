package interp

import "sort"

// hookSkillReferences collects typed schema references without executing DSL or
// reading counters. This is incidence, not a prediction of which hooks fire.
// Local scopes/aliases and captured helper closures retain lexical meaning.
func (rt *Runtime) hookSkillReferences(fn *Closure) []int {
	ids := map[int]bool{}
	visited := map[*Closure]bool{}
	var closure func(*Closure)
	var value func(Value)
	var walk func(Node, *Env)
	value = func(v Value) {
		switch x := v.(type) {
		case *SkillRef:
			ids[x.ID] = true
		case *LazySkillRef:
			// Definition IDs are shared across mirrors; actor binding is added
			// by the graph, never resolved using a live acting-player context.
			for id, ref := range rt.Skills.ByID {
				if ref.CharName == x.CharName && ref.Name == x.SkillName {
					ids[id] = true
				}
			}
		case *Closure:
			closure(x)
		}
	}
	resolve := func(n Node, env *Env) Value {
		if ident, ok := n.(*Ident); ok {
			v, _ := env.Get(ident.Name)
			return v
		}
		return nil
	}
	walk = func(n Node, env *Env) {
		switch x := n.(type) {
		case nil:
		case *Chunk:
			if x == nil {
				return
			}
			local := NewEnv(env)
			for _, stmt := range x.Stmts {
				walk(stmt, local)
			}
		case *LocalDecl:
			vals := make([]Value, len(x.Names))
			for i, expr := range x.Exprs {
				walk(expr, env)
				if i < len(vals) {
					vals[i] = resolve(expr, env)
				}
			}
			for i, name := range x.Names {
				env.SetLocal(name, vals[i])
			}
		case *Ident:
			value(resolve(x, env))
		case *IfStmt:
			walk(x.Cond, env)
			walk(x.Body, env)
			for _, branch := range x.ElseIfs {
				walk(branch.Cond, env)
				walk(branch.Body, env)
			}
			walk(x.ElseBody, env)
		case *Assign:
			walk(x.Value, env)
			if ident, ok := x.Target.(*Ident); ok {
				env.SetLocal(ident.Name, resolve(x.Value, env))
			} else {
				walk(x.Target, env)
			}
		case *ExprStmt:
			walk(x.Expr, env)
		case *BinOp:
			walk(x.Left, env)
			walk(x.Right, env)
		case *UnaryOp:
			walk(x.Expr, env)
		case *Call:
			walk(x.Func, env)
			for _, arg := range x.Args {
				walk(arg, env)
			}
		case *MethodCall:
			walk(x.Object, env)
			for _, arg := range x.Args {
				walk(arg, env)
			}
		case *DotAccess:
			walk(x.Object, env)
		case *IndexAccess:
			walk(x.Object, env)
			walk(x.Index, env)
		case *TableCtor:
			for _, field := range x.Fields {
				walk(field.Value, env)
			}
		case *FuncLit:
			local := NewEnv(env)
			for _, param := range x.Params {
				local.SetLocal(param, nil)
			}
			walk(x.Body, local)
		case *NumberLit, *StringLit, *BoolLit, *NilLit, *ReturnStmt:
		default:
			panic("unsupported AST node in skill reference metadata")
		}
	}
	closure = func(cl *Closure) {
		if cl == nil || visited[cl] {
			return
		}
		visited[cl] = true
		local := NewEnv(cl.Env)
		for _, param := range cl.Params {
			local.SetLocal(param, nil)
		}
		walk(cl.Body, local)
	}
	closure(fn)
	out := make([]int, 0, len(ids))
	for id := range ids {
		out = append(out, id)
	}
	sort.Ints(out)
	return out
}
