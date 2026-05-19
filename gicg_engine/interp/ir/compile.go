package ir

import (
	"fmt"
	"maps"
	"reflect"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// CompileHookIR walks a hook-body AST and emits 3-address-code IR.
// declareBindings supplies typed IDs for closure-captured idents; the
// map is treated read-only and caller retains ownership.
func CompileHookIR(body *interp.Chunk, declareBindings map[string]TypedBinding) ([]Op, error) {
	c := &compiler{
		scope:              map[string]int16{},
		currentChunkLocals: map[string]struct{}{},
		bindings:           declareBindings,
	}
	if err := c.compileChunk(body); err != nil {
		return nil, err
	}
	return c.ops, nil
}

type compiler struct {
	regNext int16
	scope   map[string]int16
	// currentChunkLocals = names LocalDecl'd in the current chunk; cross-block
	// reassignment of outer locals is rejected (SSA model can't propagate the write).
	currentChunkLocals map[string]struct{}
	bindings           map[string]TypedBinding
	ops                []Op
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
	// Snapshot+restore both scope and currentChunkLocals across the chunk boundary.
	savedScope := maps.Clone(c.scope)
	savedLocals := c.currentChunkLocals
	c.currentChunkLocals = map[string]struct{}{}
	for _, s := range ch.Stmts {
		if err := c.compileStmt(s); err != nil {
			return err
		}
	}
	c.scope = savedScope
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

func (c *compiler) compileAssign(a *interp.Assign) error {
	r, err := c.compileExpr(a.Value)
	if err != nil {
		return err
	}
	switch t := a.Target.(type) {
	case *interp.DotAccess:
		return c.compileAssignDotAccess(a, t, r)
	case *interp.Ident:
		if _, sameChunk := c.currentChunkLocals[t.Name]; sameChunk {
			c.scope[t.Name] = r
			return nil
		}
		if _, outerScope := c.scope[t.Name]; outerScope {
			return wrapErr(a, "reassignment to outer-scope local %q not supported (declare a fresh local instead)", t.Name)
		}
		if _, captured := c.bindings[t.Name]; captured {
			return wrapErr(a, "cannot assign to closure-captured ident %q", t.Name)
		}
		return wrapErr(a, "assign to undefined identifier %q (implicit global not allowed)", t.Name)
	default:
		return wrapErr(a, "unsupported assign target %T", a.Target)
	}
}

func (c *compiler) compileAssignDotAccess(a *interp.Assign, t *interp.DotAccess, valReg int16) error {
	obj, ok := t.Object.(*interp.Ident)
	if !ok || obj.Name != "ctx" {
		return wrapErr(a, "assign to DotAccess on non-ctx receiver")
	}
	id, ok := engine.LookupCtxField(t.Field)
	if !ok {
		return wrapErr(a, "unknown ctx field %q", t.Field)
	}
	c.emit(Op{Opcode: OpStoreAddr, Dst: valReg, Op1: AddrCtxField, Op2: id, Op3: NullReg})
	return nil
}

func (c *compiler) compileIf(s *interp.IfStmt) error {
	// Each arm: cond → CJump-false (target = next arm) → body → Jump (target = end).
	var endJumps []int
	emitArm := func(cond interp.Node, body *interp.Chunk) error {
		condReg, err := c.compileExpr(cond)
		if err != nil {
			return err
		}
		cjIdx := len(c.ops)
		c.emit(Op{Opcode: OpCJump, Op1: condReg, Op2: 0})
		if err := c.compileChunk(body); err != nil {
			return err
		}
		endJumps = append(endJumps, len(c.ops))
		c.emit(Op{Opcode: OpJump, Op1: 0})
		c.ops[cjIdx].Op2 = int16(len(c.ops))
		return nil
	}
	if err := emitArm(s.Cond, s.Body); err != nil {
		return err
	}
	for _, ei := range s.ElseIfs {
		if err := emitArm(ei.Cond, ei.Body); err != nil {
			return err
		}
	}
	if s.ElseBody != nil {
		if err := c.compileChunk(s.ElseBody); err != nil {
			return err
		}
	}
	end := int16(len(c.ops))
	for _, j := range endJumps {
		c.ops[j].Op1 = end
	}
	return nil
}

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
		// nil / false / 0 collapse intentionally: the IR-3 interpreter
		// only checks truthiness, never distinguishes the three encodings.
		return c.emitLoadImm(0)
	case *interp.Ident:
		if r, ok := c.scope[e.Name]; ok {
			return r, nil
		}
		if b, ok := c.bindings[e.Name]; ok {
			return c.emitLoadAddr(AddrLocalVar, b.ID, NullReg)
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
	case *interp.MethodCall:
		return c.compileMethodCall(e)
	case *interp.Call:
		return c.compileCall(e)
	default:
		return 0, wrapErr(n, "unsupported expression node")
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
	return 0, wrapErr(e, "unsupported DotAccess on %s.%s", obj.Name, e.Field)
}

// Method-call and builtin-call lowering lives in methods.go (domain-
// specific dispatch policy, separate concern from the generic AST visitor).
