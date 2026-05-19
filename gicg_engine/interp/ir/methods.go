package ir

// Method and builtin-call lowering: the domain-specific policy layer
// that decides how counter methods (`:get`/`:set`/`:add`/...), char-attr
// reads (`:hp`/`:energy`/...), and top-level builtin calls (`deal_damage`,
// `gain_energy`, ...) translate to IR ops. Kept separate from compile.go
// (the generic AST visitor) because this is the part that changes when
// new DSL methods are added — pure data-driven dispatch on top of the
// shared compiler infrastructure.

import (
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

func (c *compiler) compileMethodCall(e *interp.MethodCall) (int16, error) {
	if _, ok := counterMethodArity[e.Method]; ok {
		return c.compileCounterMethod(e)
	}
	if _, ok := charAttrMethods[e.Method]; ok {
		return c.compileCharAttrMethod(e)
	}
	return 0, wrapErr(e, "unsupported method :%s", e.Method)
}

func (c *compiler) compileCounterMethod(e *interp.MethodCall) (int16, error) {
	obj, ok := e.Object.(*interp.Ident)
	if !ok {
		return 0, wrapErr(e, "counter method :%s on non-ident receiver", e.Method)
	}
	b, ok := c.bindings[obj.Name]
	if !ok {
		return 0, wrapErr(e, "undefined identifier %q as counter receiver for :%s", obj.Name, e.Method)
	}
	if b.Kind != BindingCounter {
		return 0, wrapErr(e, "identifier %q kind=%s is not a counter (for :%s)", obj.Name, b.Kind, e.Method)
	}
	if want := counterMethodArity[e.Method]; len(e.Args) != want {
		return 0, wrapErr(e, "counter :%s expects %d args, got %d", e.Method, want, len(e.Args))
	}
	cid := b.ID

	// Pure load/store subset → addressed memory ops. Everything else
	// falls through to OpCall (the compiler does not lower :add to
	// load-binop-store — that's the IR-3 interpreter's policy).
	switch e.Method {
	case "get":
		return c.emitLoadAddr(AddrCounter, cid, NullReg)
	case "get_at":
		ri, err := c.compileExpr(e.Args[0])
		if err != nil {
			return 0, err
		}
		return c.emitLoadAddr(AddrCounter, cid, ri)
	case "set", "set_at":
		return c.emitCounterStore(e, cid)
	}

	// counterMethodArity keys are a strict subset of methodMap keys
	// (both populated in tokenizer_maps.go) — invariant maintained at
	// the source; the lookup cannot fail. No defensive !ok branch.
	mid, _ := engine.LookupMethod(e.Method)
	base, err := c.gatherArgs(e.Args)
	if err != nil {
		return 0, err
	}
	c.emit(Op{Opcode: OpCall, Dst: NullReg, Op1: mid, Op2: cid, Op3: base})
	return NullReg, nil
}

// emitCounterStore covers :set and :set_at. Lua-style return: the call
// evaluates to the stored value (so `local x = buff:set(5)` binds x to
// the same register that held 5 before the store).
func (c *compiler) emitCounterStore(e *interp.MethodCall, cid int16) (int16, error) {
	idx := NullReg
	valIdx := 0
	if e.Method == "set_at" {
		ri, err := c.compileExpr(e.Args[0])
		if err != nil {
			return 0, err
		}
		idx = ri
		valIdx = 1
	}
	rv, err := c.compileExpr(e.Args[valIdx])
	if err != nil {
		return 0, err
	}
	c.emit(Op{Opcode: OpStoreAddr, Dst: rv, Op1: AddrCounter, Op2: cid, Op3: idx})
	return rv, nil
}

func (c *compiler) compileCharAttrMethod(e *interp.MethodCall) (int16, error) {
	if len(e.Args) != 0 {
		return 0, wrapErr(e, "char-attr method :%s takes 0 args, got %d", e.Method, len(e.Args))
	}
	// charAttrMethods keys are a subset of methodMap keys (both
	// populated in tokenizer_maps.go) — invariant maintained at source.
	mid, _ := engine.LookupMethod(e.Method)
	recv, err := c.compileExpr(e.Object)
	if err != nil {
		return 0, err
	}
	return c.emitLoadAddr(AddrCharAttr, mid, recv)
}

func (c *compiler) compileCall(e *interp.Call) (int16, error) {
	ident, ok := e.Func.(*interp.Ident)
	if !ok {
		return 0, wrapErr(e, "call on non-ident func %T", e.Func)
	}
	fid, ok := engine.LookupBuiltin(ident.Name)
	if !ok {
		return 0, wrapErr(e, "unknown builtin %q", ident.Name)
	}
	base, err := c.gatherArgs(e.Args)
	if err != nil {
		return 0, err
	}
	dst, err := c.allocReg()
	if err != nil {
		return 0, err
	}
	c.emit(Op{Opcode: OpCall, Dst: dst, Op1: fid, Op2: int16(len(e.Args)), Op3: base})
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
