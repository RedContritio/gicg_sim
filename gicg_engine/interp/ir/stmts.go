package ir

// Statement-level lowering: assignment validation + if/elseif/else
// control-flow patching. compile.go owns the visitor dispatch
// (compileChunk → compileStmt) and the simpler stmt cases
// (LocalDecl / ReturnStmt / ExprStmt). The two cases below need
// non-trivial logic — scope rules + jump-target patching — and
// live here as their own concern.

import (
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

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
