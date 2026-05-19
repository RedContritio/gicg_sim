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
	if _, ok := counterMethods[e.Method]; ok {
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
	// Arity validation removed in IR-1.6 — see counterMethods doc comment.
	cid := b.ID

	// Pure load/store subset → addressed memory ops:
	//   :get               (0-arg)          → OpLoadAddr  (idx=NullReg)
	//   :set(v)            (1-arg)          → OpStoreAddr (idx=NullReg, src=v)
	//   :get_at(i)         (1-arg PerPlayer) → OpLoadAddr  (idx=i)
	//   :set_at(i,v)       (2-arg PerPlayer) → OpStoreAddr (idx=i, src=v)
	// Multi-index (PerChar) :get_at(p,c) / :set_at(p,c,v) fall through to
	// OpCall — single-idx OpLoadAddr can't carry the extra index.
	switch {
	case e.Method == "get" && len(e.Args) == 0:
		return c.emitLoadAddr(AddrCounter, cid, NullReg)
	case e.Method == "get_at" && len(e.Args) == 1:
		ri, err := c.compileExpr(e.Args[0])
		if err != nil {
			return 0, err
		}
		return c.emitLoadAddr(AddrCounter, cid, ri)
	case e.Method == "set" && len(e.Args) == 1:
		return c.emitCounterStore(e, cid)
	case e.Method == "set_at" && len(e.Args) == 2:
		return c.emitCounterStore(e, cid)
	}

	// counterMethods keys are a strict subset of methodMap keys
	// (both populated in tokenizer_maps.go) — invariant guarded by
	// TestContract_MethodSetsResolve; no defensive !ok branch needed.
	mid, _ := engine.LookupMethod(e.Method)
	base, err := c.gatherArgs(e.Args)
	if err != nil {
		return 0, err
	}
	dst := int16(NullReg)
	if _, returns := counterMethodsReturnValue[e.Method]; returns {
		dst, err = c.allocReg()
		if err != nil {
			return 0, err
		}
	}
	c.emit(Op{Opcode: OpCall, Dst: dst, Op1: mid, Op2: cid, Op3: base})
	return dst, nil
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

	// Special: defer_fn(function() ... end) — emit OpDeferFn + populate Lambdas
	// instead of OpCall. The FuncLit body compiles into a sub-IR appended to
	// c.lambdas; the OpDeferFn op carries the lambda index.
	if ident.Name == "defer_fn" && len(e.Args) == 1 {
		if fl, isFn := e.Args[0].(*interp.FuncLit); isFn {
			return c.compileDeferFn(e, fl)
		}
	}

	// Optional trailing TableCtor = kwargs. Separate from positional.
	posArgs := e.Args
	var kwargs *interp.TableCtor
	if n := len(posArgs); n > 0 {
		if tc, isTable := posArgs[n-1].(*interp.TableCtor); isTable {
			kwargs = tc
			posArgs = posArgs[:n-1]
		}
	}

	base, err := c.gatherArgs(posArgs)
	if err != nil {
		return 0, err
	}
	if kwargs != nil {
		if err := c.emitKwArgs(ident.Name, kwargs); err != nil {
			return 0, err
		}
	}
	dst, err := c.allocReg()
	if err != nil {
		return 0, err
	}
	c.emit(Op{Opcode: OpCall, Dst: dst, Op1: fid, Op2: int16(len(posArgs)), Op3: base})
	return dst, nil
}

// emitKwArgs emits one OpKwArg per TableCtor field — keys looked up
// in kwArgMap, values compiled to regs. Must run immediately before
// the consuming OpCall (IR-3 reads pending kwargs at OpCall dispatch).
func (c *compiler) emitKwArgs(callerName string, tc *interp.TableCtor) error {
	for _, fld := range tc.Fields {
		keyTok, ok := engine.LookupKwArg(fld.Key)
		if !ok {
			return wrapErr(tc, "unknown kwarg key %q for %s", fld.Key, callerName)
		}
		valReg, err := c.compileExpr(fld.Value)
		if err != nil {
			return err
		}
		c.emit(Op{Opcode: OpKwArg, Op1: keyTok, Op2: valReg})
	}
	return nil
}

// compileDeferFn compiles a `defer_fn(function() ... end)` call into
// an OpDeferFn op + lambda body in c.lambdas. The lambda gets a fresh
// scope (Lua-style closures over outer locals not supported; audit
// confirms current 3 defer_fn uses don't reference outer locals) but
// shares closure-captured bindings from the parent hook.
func (c *compiler) compileDeferFn(e *interp.Call, fl *interp.FuncLit) (int16, error) {
	sub := &compiler{
		scope:              map[string]int16{},
		currentChunkLocals: map[string]struct{}{},
		bindings:           c.bindings,
		lambdas:            c.lambdas, // shared pointer — nested defer_fn lands in the root list
	}
	if err := sub.compileChunk(fl.Body); err != nil {
		return 0, wrapErr(e, "compiling defer_fn lambda: %v", err)
	}
	lambdaIdx := int16(len(*c.lambdas))
	*c.lambdas = append(*c.lambdas, sub.ops)
	c.emit(Op{Opcode: OpDeferFn, Op1: lambdaIdx})
	return NullReg, nil
}

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
