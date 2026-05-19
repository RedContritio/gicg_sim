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
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			chunk := parseBody(t, tc.src)
			got, err := CompileHookIR(chunk, tc.bindings)
			if tc.wantErr != "" {
				if err == nil {
					t.Fatalf("expected error containing %q, got nil (ops=%v)", tc.wantErr, got)
				}
				if !strings.Contains(err.Error(), tc.wantErr) {
					t.Fatalf("expected error containing %q, got %q", tc.wantErr, err.Error())
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if !reflect.DeepEqual(got, tc.wantOps) {
				t.Fatalf("ops mismatch\nwant: %s\n got: %s", formatOps(tc.wantOps), formatOps(got))
			}
		})
	}
}
