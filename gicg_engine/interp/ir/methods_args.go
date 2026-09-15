package ir

// Call-frame and index-access lowering. gatherArgs builds the contiguous
// OpCall argument frame shared by every call-shaped lowering in
// methods.go; compileIndexAccess lowers the engine bridge globals
// (_chars[i], _char_by_slot[p][c]) onto that same frame shape.

import (
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// compileIndexAccess: only the engine bridge globals (_chars[i],
// _char_by_slot[p][c]) are supported. Compiler emits OpCall with the
// bridge's token ID; IR-3 dispatches to runtime bridge resolution.
// Other IndexAccess shapes (object indexing, table indexing, ...) reject.
func (c *compiler) compileIndexAccess(e *interp.IndexAccess) (int16, error) {
	var args []interp.Node
	var bridgeName string
	if obj, ok := e.Object.(*interp.Ident); ok {
		bridgeName = obj.Name
		args = []interp.Node{e.Index}
	} else if innerIdx, ok := e.Object.(*interp.IndexAccess); ok {
		if innerObj, ok := innerIdx.Object.(*interp.Ident); ok {
			bridgeName = innerObj.Name
			args = []interp.Node{innerIdx.Index, e.Index}
		}
	}
	if bridgeName == "" {
		return 0, wrapErr(e, "unsupported IndexAccess on %T", e.Object)
	}
	bridgeTok, ok := engine.LookupBridge(bridgeName)
	if !ok {
		return 0, wrapErr(e, "unknown bridge global %q", bridgeName)
	}
	base, err := c.gatherArgs(args)
	if err != nil {
		return 0, err
	}
	dst, err := c.allocReg()
	if err != nil {
		return 0, err
	}
	c.emit(Op{Opcode: OpCall, Dst: dst, Op1: bridgeTok, Op2: int16(len(args)), Op3: base})
	return dst, nil
}

// gatherArgs compiles each arg, reserves a contiguous reg block for the
// call's argument frame, copies args in via OpLoadReg, and returns the
// base reg of that frame (NullReg if 0 args).
//
// The reserve loop (allocReg called N times after the first) is
// intentional — we need N consecutive register indices and want the
// per-reg overflow check to fire for any of them.
func (c *compiler) gatherArgs(args []interp.Node) (int16, error) {
	if len(args) == 0 {
		return NullReg, nil
	}
	argRegs := make([]int16, 0, len(args))
	for _, a := range args {
		r, err := c.compileExpr(a)
		if err != nil {
			return 0, err
		}
		argRegs = append(argRegs, r)
	}
	first, err := c.allocReg()
	if err != nil {
		return 0, err
	}
	for range len(argRegs) - 1 {
		if _, err := c.allocReg(); err != nil {
			return 0, err
		}
	}
	for i, r := range argRegs {
		c.emit(Op{Opcode: OpLoadReg, Dst: first + int16(i), Op1: r})
	}
	return first, nil
}
