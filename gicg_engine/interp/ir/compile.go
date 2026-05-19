package ir

import (
	"fmt"
	"maps"
	"reflect"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// CompiledHook = MainOps + per-defer_fn Lambdas; OpDeferFn in MainOps indexes Lambdas.
type CompiledHook struct {
	MainOps []Op
	Lambdas [][]Op
}

// CompileHookIR walks a hook-body AST → 3-address-code IR.
// declareBindings: closure-captured ident → typed ID; read-only.
func CompileHookIR(body *interp.Chunk, declareBindings map[string]TypedBinding) (CompiledHook, error) {
	lambdas := [][]Op{}
	c := &compiler{
		scope:              map[string]int16{},
		currentChunkLocals: map[string]struct{}{},
		bindings:           declareBindings,
		lambdas:            &lambdas,
	}
	if err := c.compileChunk(body); err != nil {
		return CompiledHook{}, err
	}
	return CompiledHook{MainOps: c.ops, Lambdas: lambdas}, nil
}

type compiler struct {
	regNext int16
	scope   map[string]int16
	// currentChunkLocals = names LocalDecl'd in this chunk; cross-block reassign rejected.
	currentChunkLocals map[string]struct{}
	bindings           map[string]TypedBinding
	ops                []Op
	// lambdas is a SHARED pointer to the root compiler's lambda list —
	// sub-compilers for nested defer_fn append to the same flat slice so
	// every OpDeferFn anywhere in the tree carries a global lambda index.
	lambdas *[][]Op
}

// --- low-level emit helpers --------------------------------------------------

func (c *compiler) allocReg() (int16, error) {
	if c.regNext >= MaxRegs {
		return 0, fmt.Errorf("hook exceeds %d registers (got %d)", MaxRegs, c.regNext+1)
	}
	r := c.regNext
	c.regNext++
	return r, nil
}

func (c *compiler) emit(op Op) { c.ops = append(c.ops, op) }

// wrapErr stamps node type + line onto an error so each error site stays
// one line. Type is the unqualified Go name (e.g. "Assign") — the
// "*interp." prefix is dropped because it's noise the reader doesn't need.
func wrapErr(n interp.Node, format string, args ...any) error {
	t := reflect.TypeOf(n)
	if t.Kind() == reflect.Pointer {
		t = t.Elem()
	}
	return fmt.Errorf("ir: %s at line %d: %s", t.Name(), n.GetLine(), fmt.Sprintf(format, args...))
}

func (c *compiler) emitLoadImm(v int16) (int16, error) {
	r, err := c.allocReg()
	if err != nil {
		return 0, err
	}
	c.emit(Op{Opcode: OpLoadImm, Dst: r, Op1: v})
	return r, nil
}

func (c *compiler) emitLoadAddr(kind, addr, idx int16) (int16, error) {
	r, err := c.allocReg()
	if err != nil {
		return 0, err
	}
	c.emit(Op{Opcode: OpLoadAddr, Dst: r, Op1: kind, Op2: addr, Op3: idx})
	return r, nil
}

// emitArithOp covers OpBinOp / OpUnaryOp. op1 is always set (left for
// binary, sole operand for unary); op2 is 0 for unary.
func (c *compiler) emitArithOp(opcode, kind int16, op1, op2 int16) (int16, error) {
	r, err := c.allocReg()
	if err != nil {
		return 0, err
	}
	c.emit(Op{Opcode: opcode, Dst: r, Op1: kind, Op2: op1, Op3: op2})
	return r, nil
}

// --- statements --------------------------------------------------------------

func (c *compiler) compileChunk(ch *interp.Chunk) error {
	// Chunk-boundary scope: outer-scope reassignments propagate (Lua semantics —
	// `local x; if cond then x = 5 end` must update x post-block); only LOCALly
	// declared names fall out of scope at exit. Shadowing (inner `local x`
	// over outer `x`) restores outer's binding on exit.
	savedScope := maps.Clone(c.scope)
	savedLocals := c.currentChunkLocals
	c.currentChunkLocals = map[string]struct{}{}
	for _, s := range ch.Stmts {
		if err := c.compileStmt(s); err != nil {
			return err
		}
	}
	for name := range c.currentChunkLocals {
		if old, was := savedScope[name]; was {
			c.scope[name] = old // restore shadowed outer
		} else {
			delete(c.scope, name) // remove inner-only local
		}
	}
	c.currentChunkLocals = savedLocals
	return nil
}

func (c *compiler) compileStmt(n interp.Node) error {
	switch s := n.(type) {
	case *interp.LocalDecl:
		for i, name := range s.Names {
			var (
				r   int16
				err error
			)
			if i < len(s.Exprs) {
				r, err = c.compileExpr(s.Exprs[i])
			} else {
				r, err = c.emitLoadImm(0)
			}
			if err != nil {
				return err
			}
			c.scope[name] = r
			c.currentChunkLocals[name] = struct{}{}
		}
		return nil
	case *interp.Assign:
		return c.compileAssign(s)
	case *interp.IfStmt:
		return c.compileIf(s)
	case *interp.ReturnStmt:
		c.emit(Op{Opcode: OpReturn})
		return nil
	case *interp.ExprStmt:
		_, err := c.compileExpr(s.Expr)
		return err
	default:
		return wrapErr(n, "unsupported statement node")
	}
}

// Stmt-level lowering for Assign + If lives in stmts.go.

// --- expressions -------------------------------------------------------------

func (c *compiler) compileExpr(n interp.Node) (int16, error) {
	switch e := n.(type) {
	case *interp.NumberLit:
		if e.Value < -32768 || e.Value > 32767 {
			return 0, wrapErr(n, "number literal %d out of int16 range", e.Value)
		}
		return c.emitLoadImm(int16(e.Value))
	case *interp.BoolLit:
		v := int16(0)
		if e.Value {
			v = 1
		}
		return c.emitLoadImm(v)
	case *interp.NilLit:
		// nil ≠ 0 / false — engine distinguishes "unset" (e.g. fill_all(p, nil)).
		r, err := c.allocReg()
		if err != nil {
			return 0, err
		}
		c.emit(Op{Opcode: OpLoadNil, Dst: r})
		return r, nil
	case *interp.StringLit:
		// RC2: string literals appear in hook bodies as get_counter name
		// args ("alive_count") and similar lookup keys. The actual string
		// content is opaque to the obs encoder (no embedding budget for
		// per-string-content tokens), so lower to OpLoadImm 0 — a stable
		// placeholder. The semantic info that matters for the encoder
		// (the builtin being called and surrounding control flow) is
		// preserved in the surrounding OpCall.
		return c.emitLoadImm(0)
	case *interp.TableCtor:
		// RC2: positional-arg TableCtor (not the trailing-kwargs slot —
		// that path is handled in compileCall before gatherArgs). E.g.
		// `set_at({player = Player.All}, 0)` passes a literal table as
		// first positional. The table content is opaque to the obs
		// encoder, so lower to OpLoadNil — encoder distinguishes
		// "table arg present" from "missing arg" via NullReg.
		return c.emitLoadImm(0)
	case *interp.Ident:
		if r, ok := c.scope[e.Name]; ok {
			return r, nil
		}
		if b, ok := c.bindings[e.Name]; ok {
			// RC2: file-top numeric/bool constants (e.g. `local INITIAL_HAND = 5`)
			// inline at every read as OpLoadImm — keeps the value visible to
			// the encoder as a literal embedding rather than an opaque
			// AddrLocalVar load (which would be a single token for all
			// constants in the file).
			if b.Kind == BindingConst {
				return c.emitLoadImm(b.ConstValue)
			}
			return c.emitLoadAddr(AddrLocalVar, b.ID, NullReg)
		}
		// RC2: bare `ctx` — every hook body's enclosing FuncLit has
		// `ctx` as its sole parameter (the hook context proxy). Bare
		// references (`cost_total(ctx)`, `cost_mod(ctx, ...)`) lower to
		// an AddrCtxField load with sentinel addr_id=0 meaning "ctx self".
		// `ctx.field` style is unaffected (compileDotAccess short-circuits).
		if e.Name == "ctx" {
			return c.emitLoadAddr(AddrCtxField, 0, NullReg)
		}
		return 0, wrapErr(n, "undefined identifier %q", e.Name)
	case *interp.BinOp:
		kind, ok := binOpKindByString[e.Op]
		if !ok {
			return 0, wrapErr(e, "unknown binary operator %q", e.Op)
		}
		rl, err := c.compileExpr(e.Left)
		if err != nil {
			return 0, err
		}
		rr, err := c.compileExpr(e.Right)
		if err != nil {
			return 0, err
		}
		return c.emitArithOp(OpBinOp, kind, rl, rr)
	case *interp.UnaryOp:
		kind, ok := unaryOpKindByString[e.Op]
		if !ok {
			return 0, wrapErr(e, "unknown unary operator %q", e.Op)
		}
		re, err := c.compileExpr(e.Expr)
		if err != nil {
			return 0, err
		}
		return c.emitArithOp(OpUnaryOp, kind, re, 0)
	case *interp.DotAccess:
		return c.compileDotAccess(e)
	case *interp.IndexAccess:
		return c.compileIndexAccess(e)
	case *interp.MethodCall:
		return c.compileMethodCall(e)
	case *interp.Call:
		return c.compileCall(e)
	default:
		return 0, wrapErr(n, "unsupported expression node %T", n)
	}
}

func (c *compiler) compileDotAccess(e *interp.DotAccess) (int16, error) {
	obj, ok := e.Object.(*interp.Ident)
	if !ok {
		return 0, wrapErr(e, "DotAccess on non-ident receiver %T", e.Object)
	}
	if obj.Name == "ctx" {
		id, ok := engine.LookupCtxField(e.Field)
		if !ok {
			return 0, wrapErr(e, "unknown ctx field %q", e.Field)
		}
		return c.emitLoadAddr(AddrCtxField, id, NullReg)
	}
	if id, ok := engine.LookupEnum(obj.Name + "." + e.Field); ok {
		return c.emitLoadAddr(AddrEnum, id, NullReg)
	}
	// OQ-3: char-attr field-style. `ch.hp` ≡ `ch:hp()` when `ch` is a
	// Char-binding receiver. Audit confirms field-style usage in
	// v_legacy (以牙还牙, 星愿). Method-style continues to work via
	// compileMethodCall.
	if b, bok := c.bindings[obj.Name]; bok && b.Kind == BindingChar {
		if _, isAttr := charAttrMethods[e.Field]; isAttr {
			mid, _ := engine.LookupMethod(e.Field)
			recv, err := c.emitLoadAddr(AddrLocalVar, b.ID, NullReg)
			if err != nil {
				return 0, err
			}
			return c.emitLoadAddr(AddrCharAttr, mid, recv)
		}
	}
	// RC2: scope-local char-attr field-style. `local c = _char_by_slot[p][i];
	// c.weapon` — `c` is a hook-body local (lives in c.scope) holding a
	// char proxy; field access on a known char-attr method lowers to
	// AddrCharAttr with the scope-local reg as receiver. Without this
	// path the compiler rejected ~10 v_legacy weapon/energy/element/
	// normal_attack reads through `_char_by_slot` lookups.
	if recvReg, isScopeLocal := c.scope[obj.Name]; isScopeLocal {
		if _, isAttr := charAttrMethods[e.Field]; isAttr {
			mid, _ := engine.LookupMethod(e.Field)
			return c.emitLoadAddr(AddrCharAttr, mid, recvReg)
		}
	}
	return 0, wrapErr(e, "unsupported DotAccess on %s.%s", obj.Name, e.Field)
}

// Method-call and builtin-call lowering lives in methods.go (domain-
// specific dispatch policy, separate concern from the generic AST visitor).
