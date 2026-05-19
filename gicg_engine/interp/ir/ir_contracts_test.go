package ir

// Contract-validation tests for the AST→IR compiler: defensive guards
// (implicit-global reject, outer-scope reassign reject, binding kind
// mismatch) + coverage gaps the base golden table misses (set_at with
// expression index, Lua-like :set return value). Separate from
// ir_test.go (which covers the per-AST-node Op-emission contract).

import (
	"reflect"
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestCompilerContracts(t *testing.T) {
	const (
		ctxF = AddrCtxField
		cnt  = AddrCounter
		nr   = NullReg
	)
	tokVal := int16(engine.TokCtxValue)
	tokHit := int16(engine.TokCtxHit)

	cases := []struct {
		name     string
		src      string
		bindings map[string]TypedBinding
		wantOps  []Op
		wantErr  string
	}{
		{
			name:    "implicit_global_rejected",
			src:     `foo = 5`,
			wantErr: "implicit global not allowed",
		},
		{
			// Lua-style cross-block reassign of outer local — SSA model
			// can't propagate; reject at compile.
			name:    "outer_local_reassign_rejected",
			src:     `local x = 1 if ctx.hit then x = 5 end`,
			wantErr: "reassignment to outer-scope",
		},
		{
			// Same-chunk reassign — OK, rebinds name to fresh register.
			name: "same_chunk_reassign_ok",
			src:  `local x = 1 x = 2`,
			wantOps: []Op{
				{Opcode: OpLoadImm, Dst: 0, Op1: 1},
				{Opcode: OpLoadImm, Dst: 1, Op1: 2},
			},
		},
		{
			// Inner `local x` shadows outer — falls out of scope at chunk exit.
			name: "inner_local_shadow_ok",
			src:  `local x = 1 if ctx.hit then local x = 5 end`,
			wantOps: []Op{
				{Opcode: OpLoadImm, Dst: 0, Op1: 1},
				{Opcode: OpLoadAddr, Dst: 1, Op1: ctxF, Op2: tokHit, Op3: nr},
				{Opcode: OpCJump, Op1: 1, Op2: 5},
				{Opcode: OpLoadImm, Dst: 2, Op1: 5},
				{Opcode: OpJump, Op1: 5},
			},
		},
		{
			// Counter method on non-counter binding — error must show the
			// kind name (via TypedBindingKind.String), not raw int.
			name:     "kind_mismatch_not_counter",
			src:      `card:set_at(0, 1)`,
			bindings: map[string]TypedBinding{"card": {Kind: BindingCard, ID: 100}},
			wantErr:  "kind=Card is not a counter",
		},
		{
			// set_at with expr-as-index — exercises compileExpr recursion in emitCounterStore.
			name:     "set_at_index_expression",
			src:      `buff:set_at(ctx.value + 1, 5)`,
			bindings: map[string]TypedBinding{"buff": {Kind: BindingCounter, ID: 7}},
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokVal, Op3: nr},
				{Opcode: OpLoadImm, Dst: 1, Op1: 1},
				{Opcode: OpBinOp, Dst: 2, Op1: BinAdd, Op2: 0, Op3: 1},
				{Opcode: OpLoadImm, Dst: 3, Op1: 5},
				{Opcode: OpStoreAddr, Dst: 3, Op1: cnt, Op2: 7, Op3: 2},
			},
		},
		{
			// :set returns the stored value (Lua-like); chained read reuses the same reg.
			name:     "counter_set_returns_value",
			src:      `local x = buff:set(5) ctx.value = x`,
			bindings: map[string]TypedBinding{"buff": {Kind: BindingCounter, ID: 7}},
			wantOps: []Op{
				{Opcode: OpLoadImm, Dst: 0, Op1: 5},
				{Opcode: OpStoreAddr, Dst: 0, Op1: cnt, Op2: 7, Op3: nr},
				{Opcode: OpStoreAddr, Dst: 0, Op1: ctxF, Op2: tokVal, Op3: nr},
			},
		},
		// --- IR-1.6 Part B new behaviors ----------------------------
		{
			// T-003: nil emits OpLoadNil (NOT OpLoadImm 0). Engine
			// distinguishes nil from 0 (e.g. fill_all(p, nil)).
			name: "nil_distinct_from_zero",
			src:  `local x = nil`,
			wantOps: []Op{
				{Opcode: OpLoadNil, Dst: 0},
			},
		},
		{
			// T-110: _chars[i] → OpCall TokBridgeChars n_pos=1.
			name: "bridge_chars_1d",
			src:  `local c = _chars[ctx.actor_player]`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: int16(engine.TokCtxActorPlayer), Op3: nr},
				{Opcode: OpLoadReg, Dst: 1, Op1: 0},
				{Opcode: OpCall, Dst: 2, Op1: int16(engine.TokBridgeChars), Op2: 1, Op3: 1},
			},
		},
		{
			// T-111: _char_by_slot[p][c] → OpCall TokBridgeCharBySlot n_pos=2.
			name: "bridge_char_by_slot_2d",
			src:  `local ch = _char_by_slot[ctx.actor_player][ctx.actor_char]`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: int16(engine.TokCtxActorPlayer), Op3: nr},
				{Opcode: OpLoadAddr, Dst: 1, Op1: ctxF, Op2: int16(engine.TokCtxActorChar), Op3: nr},
				{Opcode: OpLoadReg, Dst: 2, Op1: 0},
				{Opcode: OpLoadReg, Dst: 3, Op1: 1},
				{Opcode: OpCall, Dst: 4, Op1: int16(engine.TokBridgeCharBySlot), Op2: 2, Op3: 2},
			},
		},
		{
			// T-141: counter :decay_all(1) — was rejected by IR-1's
			// arity=0 check; IR-1.6 removed arity validation.
			name:     "counter_decay_all_1arg_perchar",
			src:      `buff:decay_all(1)`,
			bindings: map[string]TypedBinding{"buff": {Kind: BindingCounter, ID: 7}},
			wantOps: []Op{
				{Opcode: OpLoadImm, Dst: 0, Op1: 1},
				{Opcode: OpLoadReg, Dst: 1, Op1: 0},
				{Opcode: OpCall, Dst: nr, Op1: int16(engine.TokMDecayAll), Op2: 7, Op3: 1},
			},
		},
		{
			// T-131: counter :set_at(p, c, v) — 3-arg PerChar form.
			// Was rejected by IR-1's arity=2 check.
			name:     "counter_set_at_3arg_perchar",
			src:      `buff:set_at(ctx.actor_player, ctx.actor_char, 0)`,
			bindings: map[string]TypedBinding{"buff": {Kind: BindingCounter, ID: 7}},
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: int16(engine.TokCtxActorPlayer), Op3: nr},
				{Opcode: OpLoadAddr, Dst: 1, Op1: ctxF, Op2: int16(engine.TokCtxActorChar), Op3: nr},
				{Opcode: OpLoadImm, Dst: 2, Op1: 0},
				{Opcode: OpLoadReg, Dst: 3, Op1: 0},
				{Opcode: OpLoadReg, Dst: 4, Op1: 1},
				{Opcode: OpLoadReg, Dst: 5, Op1: 2},
				{Opcode: OpCall, Dst: nr, Op1: int16(engine.TokMSetAt), Op2: 7, Op3: 3},
			},
		},
		{
			// T-171: TableCtor kwargs — single key. OpKwArg emitted
			// immediately before the OpCall consuming it.
			name: "tablector_kwargs_single",
			src:  `deal_damage(Target.EnemyActive, Element.Physical, 1, { source = Source.Skill })`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: AddrEnum, Op2: int16(engine.TokTargetEnemyActive), Op3: nr},
				{Opcode: OpLoadAddr, Dst: 1, Op1: AddrEnum, Op2: int16(engine.TokElementPhysical), Op3: nr},
				{Opcode: OpLoadImm, Dst: 2, Op1: 1},
				{Opcode: OpLoadReg, Dst: 3, Op1: 0},
				{Opcode: OpLoadReg, Dst: 4, Op1: 1},
				{Opcode: OpLoadReg, Dst: 5, Op1: 2},
				{Opcode: OpLoadAddr, Dst: 6, Op1: AddrEnum, Op2: int16(engine.TokSourceSkill), Op3: nr},
				{Opcode: OpKwArg, Op1: int16(engine.TokKwSource), Op2: 6},
				{Opcode: OpCall, Dst: 7, Op1: int16(engine.TokDealDamage), Op2: 3, Op3: 3},
			},
		},
		{
			// T-183 negative: TableCtor outside Call context rejected.
			name:    "tablector_outside_call_rejected",
			src:     `local t = { foo = 1 }`,
			wantErr: "unsupported expression node",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			chunk := parseBody(t, tc.src)
			got, err := CompileHookIR(chunk, tc.bindings)
			if tc.wantErr != "" {
				if err == nil {
					t.Fatalf("expected error containing %q, got nil (ops=%v)", tc.wantErr, got.MainOps)
				}
				if !strings.Contains(err.Error(), tc.wantErr) {
					t.Fatalf("expected error containing %q, got %q", tc.wantErr, err.Error())
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if !reflect.DeepEqual(got.MainOps, tc.wantOps) {
				t.Fatalf("ops mismatch\nwant: %s\n got: %s", formatOps(tc.wantOps), formatOps(got.MainOps))
			}
		})
	}
}

// T-173: defer_fn → OpDeferFn op + populated Lambdas (structural check).
func TestDeferFnLambdas(t *testing.T) {
	src := `defer_fn(function() deal_damage(Target.EnemyAll, Element.Ice, 1, { source = Source.Reaction }) end)`
	chunk := parseBody(t, src)
	got, err := CompileHookIR(chunk, nil)
	if err != nil {
		t.Fatalf("compile error: %v", err)
	}

	// MainOps: exactly 1 OpDeferFn, 0 OpCall.
	var nDeferFn, nCallDeferFn int
	for _, op := range got.MainOps {
		if op.Opcode == OpDeferFn {
			nDeferFn++
		}
		if op.Opcode == OpCall && op.Op1 == int16(engine.TokDeferFn) {
			nCallDeferFn++
		}
	}
	if nDeferFn != 1 {
		t.Errorf("MainOps: want 1 OpDeferFn, got %d (ops=%s)", nDeferFn, formatOps(got.MainOps))
	}
	if nCallDeferFn != 0 {
		t.Errorf("MainOps: want 0 OpCall(TokDeferFn) (replaced by OpDeferFn), got %d", nCallDeferFn)
	}

	// Lambdas: 1 lambda; contains OpCall TokDealDamage and OpKwArg TokKwSource.
	if len(got.Lambdas) != 1 {
		t.Fatalf("want 1 lambda, got %d", len(got.Lambdas))
	}
	var nLambdaCall, nLambdaKw int
	for _, op := range got.Lambdas[0] {
		if op.Opcode == OpCall && op.Op1 == int16(engine.TokDealDamage) {
			nLambdaCall++
		}
		if op.Opcode == OpKwArg && op.Op1 == int16(engine.TokKwSource) {
			nLambdaKw++
		}
	}
	if nLambdaCall != 1 {
		t.Errorf("Lambdas[0]: want 1 OpCall(TokDealDamage), got %d", nLambdaCall)
	}
	if nLambdaKw != 1 {
		t.Errorf("Lambdas[0]: want 1 OpKwArg(TokKwSource), got %d", nLambdaKw)
	}
}

// C-001: methodMap ∩ tokenMap = ∅ (OpCall.Op2 dual semantics unambiguous).
func TestContract_OpCallDispatchDisjoint(t *testing.T) {
	methods := []string{"get", "set", "add", "sub", "cmin", "cmax", "get_at", "set_at",
		"add_at", "sub_at", "decay_all", "fill_all", "hp", "energy", "alive",
		"owner_player", "owner_char", "name", "element", "weapon"}
	builtins := []string{"declare_counter", "get_counter", "declare_char", "get_char",
		"declare_skill", "get_skill", "invoke_skill", "declare_card", "get_card",
		"add_card", "deal_damage", "heal", "defer_fn", "get_active_char",
		"context_player", "gain_energy", "consume_energy", "min", "max"}
	methodIDs := map[int16]string{}
	for _, m := range methods {
		id, ok := engine.LookupMethod(m)
		if !ok {
			t.Fatalf("methodMap missing %q", m)
		}
		methodIDs[id] = m
	}
	for _, b := range builtins {
		id, ok := engine.LookupBuiltin(b)
		if !ok {
			t.Fatalf("tokenMap missing %q", b)
		}
		if m, dup := methodIDs[id]; dup {
			t.Errorf("token id %d collision: builtin %q and method %q (breaks OpCall Op2 dispatch)", id, b, m)
		}
	}
}

// C-002: every name in counterMethods/charAttrMethods resolves to a
// non-zero token via LookupMethod. Otherwise compiler silently emits
// OpCall(Op1=0=OpNop).
func TestContract_MethodSetsResolve(t *testing.T) {
	for name := range counterMethods {
		id, ok := engine.LookupMethod(name)
		if !ok || id == 0 {
			t.Errorf("counterMethods[%q]: LookupMethod returned (%d, %v); want (non-zero, true)", name, id, ok)
		}
	}
	for name := range charAttrMethods {
		id, ok := engine.LookupMethod(name)
		if !ok || id == 0 {
			t.Errorf("charAttrMethods[%q]: LookupMethod returned (%d, %v); want (non-zero, true)", name, id, ok)
		}
	}
}
