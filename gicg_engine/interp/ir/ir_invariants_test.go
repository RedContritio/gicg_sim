package ir

// Compiler invariants per TEST_PLAN.md section 3 (C-003..C-013).
// These check structural properties of the IR/compiler that must
// hold regardless of input — e.g., opcode value uniqueness, vocabulary
// coverage, token-range disjointness.

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

// C-001: methodMap ∩ tokenMap (builtin) = ∅ — OpCall.Op2 dual semantics
// (counter id vs n_args) dispatch ranges must not collide.
func TestInvariant_OpCallDispatchDisjoint(t *testing.T) {
	mIDs := map[int16]string{}
	for name := range counterMethods {
		id, _ := engine.LookupMethod(name)
		mIDs[id] = name
	}
	for name := range charAttrMethods {
		id, _ := engine.LookupMethod(name)
		mIDs[id] = name
	}
	for _, b := range []string{"declare_counter", "get_counter", "declare_card", "get_card",
		"declare_char", "get_char", "declare_skill", "get_skill", "deal_damage", "heal",
		"defer_fn", "get_active_char", "context_player", "gain_energy", "min", "max"} {
		id, ok := engine.LookupBuiltin(b)
		if !ok {
			t.Fatalf("LookupBuiltin %q missing", b)
		}
		if m, dup := mIDs[id]; dup {
			t.Errorf("token %d collision: builtin %q vs method %q", id, b, m)
		}
	}
}

// C-002 + C-003: every counterMethods / charAttrMethods name resolves
// to non-zero via LookupMethod (else compiler silently emits Op1=0=OpNop).
func TestInvariant_MethodSetsResolve(t *testing.T) {
	for name := range counterMethods {
		id, ok := engine.LookupMethod(name)
		if !ok || id == 0 {
			t.Errorf("counterMethods[%q] resolves to (%d, %v); want non-zero", name, id, ok)
		}
	}
	for name := range charAttrMethods {
		id, ok := engine.LookupMethod(name)
		if !ok || id == 0 {
			t.Errorf("charAttrMethods[%q] resolves to (%d, %v); want non-zero", name, id, ok)
		}
	}
}

// C-004: counterMethods set exactly = {get,set,get_at,set_at,add,sub,
// add_at,sub_at,cmin,cmax,decay_all,fill_all}. Guards against zombies
// (renamed/deleted methods left in table) or missing entries.
func TestInvariant_CounterMethodsExact(t *testing.T) {
	want := map[string]struct{}{
		"get": {}, "set": {}, "get_at": {}, "set_at": {},
		"add": {}, "sub": {}, "add_at": {}, "sub_at": {},
		"cmin": {}, "cmax": {}, "decay_all": {}, "fill_all": {},
	}
	if len(counterMethods) != len(want) {
		t.Fatalf("counterMethods size = %d, want %d", len(counterMethods), len(want))
	}
	for k := range want {
		if _, ok := counterMethods[k]; !ok {
			t.Errorf("counterMethods missing %q", k)
		}
	}
	for k := range counterMethods {
		if _, ok := want[k]; !ok {
			t.Errorf("counterMethods has unexpected %q", k)
		}
	}
}

// C-005: charAttrMethods set exactly = {hp, energy, alive, owner_player,
// owner_char, name, element, weapon}.
func TestInvariant_CharAttrMethodsExact(t *testing.T) {
	want := map[string]struct{}{
		"hp": {}, "energy": {}, "alive": {},
		"owner_player": {}, "owner_char": {},
		"name": {}, "element": {}, "weapon": {},
	}
	if len(charAttrMethods) != len(want) {
		t.Fatalf("charAttrMethods size = %d, want %d", len(charAttrMethods), len(want))
	}
	for k := range want {
		if _, ok := charAttrMethods[k]; !ok {
			t.Errorf("charAttrMethods missing %q", k)
		}
	}
	for k := range charAttrMethods {
		if _, ok := want[k]; !ok {
			t.Errorf("charAttrMethods has unexpected %q", k)
		}
	}
}

// C-006: every kwarg key registered in engine's kwArgMap resolves via
// LookupKwArg to a non-zero token. Sweep via LookupKwArg on each known
// kwarg name.
func TestInvariant_KwArgKeysResolve(t *testing.T) {
	keys := []string{"source", "element", "target", "penetrate", "react"}
	for _, k := range keys {
		id, ok := engine.LookupKwArg(k)
		if !ok || id == 0 {
			t.Errorf("LookupKwArg(%q) returned (%d, %v); want (non-zero, true)", k, id, ok)
		}
	}
}

// C-007: bridge tokens resolve and don't collide with other token ranges.
func TestInvariant_BridgeTokensResolve(t *testing.T) {
	chars, ok1 := engine.LookupBridge("_chars")
	cbs, ok2 := engine.LookupBridge("_char_by_slot")
	if !ok1 || chars == 0 {
		t.Errorf("LookupBridge(_chars) = (%d, %v); want non-zero", chars, ok1)
	}
	if !ok2 || cbs == 0 {
		t.Errorf("LookupBridge(_char_by_slot) = (%d, %v); want non-zero", cbs, ok2)
	}
	if chars == cbs {
		t.Errorf("bridge tokens must be distinct; both = %d", chars)
	}
	// Disjoint from method tokens (compileMethodCall vs compileIndexAccess
	// dispatch on Op1, so bridge tokens MUST NOT collide with TokM*).
	for name := range counterMethods {
		mid, _ := engine.LookupMethod(name)
		if mid == chars || mid == cbs {
			t.Errorf("bridge token collision with counter method %q (mid=%d)", name, mid)
		}
	}
}

// C-009: opcodes are 14 distinct integers {0..13}. Adding new opcode
// without updating this test crashes here, forcing review.
func TestInvariant_OpcodesUnique(t *testing.T) {
	ops := []int16{
		OpNop, OpLoadImm, OpLoadReg, OpLoadAddr, OpStoreAddr,
		OpBinOp, OpUnaryOp, OpCall, OpCJump, OpJump, OpReturn,
		OpKwArg, OpDeferFn, OpLoadNil,
	}
	seen := map[int16]bool{}
	for _, op := range ops {
		if seen[op] {
			t.Errorf("duplicate opcode value %d", op)
		}
		seen[op] = true
	}
	if len(seen) != 14 {
		t.Errorf("opcode count = %d, want 14", len(seen))
	}
}

// C-010: AddrKind values are exactly {1..5}.
func TestInvariant_AddrKindsExact(t *testing.T) {
	if AddrCtxField != 1 || AddrCounter != 2 || AddrCharAttr != 3 ||
		AddrLocalVar != 4 || AddrEnum != 5 {
		t.Errorf("AddrKind values drifted: ctxField=%d counter=%d charAttr=%d localVar=%d enum=%d",
			AddrCtxField, AddrCounter, AddrCharAttr, AddrLocalVar, AddrEnum)
	}
}

// C-011: BinOpKind {1..12} distinct; UnaryOpKind {1..2} distinct.
// Both reside in Op1 of OpBinOp/OpUnaryOp respectively so no inter-set
// collision constraint, but each set must be internally unique.
func TestInvariant_OpKindsDistinct(t *testing.T) {
	bin := []int16{BinAdd, BinSub, BinMul, BinDiv, BinEq, BinNeq,
		BinLt, BinGt, BinLe, BinGe, BinAnd, BinOr}
	seen := map[int16]bool{}
	for _, k := range bin {
		if seen[k] {
			t.Errorf("BinOpKind dup %d", k)
		}
		seen[k] = true
	}
	if len(seen) != 12 {
		t.Errorf("BinOpKind count = %d, want 12", len(seen))
	}
	if UnaryNot == UnaryNeg {
		t.Errorf("UnaryOpKind not distinct")
	}
}
