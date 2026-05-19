package ir

// Method-call coverage per TEST_PLAN.md (T-120..T-162). Counter
// methods compile to OpLoadAddr/OpStoreAddr (load/store fast path)
// for :get/:set/:get_at/:set_at (with constrained arity), else
// OpCall fall-through. Char-attr methods always OpLoadAddr AddrCharAttr.

import (
	"reflect"
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestCounterMethodCalls(t *testing.T) {
	const (
		ctxF = AddrCtxField
		cnt  = AddrCounter
		nr   = NullReg
	)
	bcnt := map[string]TypedBinding{"c": {Kind: BindingCounter, ID: 5}}
	tokAP := int16(engine.TokCtxActorPlayer)
	tokAC := int16(engine.TokCtxActorChar)

	cases := []struct {
		name     string
		src      string
		bindings map[string]TypedBinding
		wantOps  []Op
		wantErr  string
	}{
		{
			// T-120: :get → OpLoadAddr AddrCounter NullReg.
			name:     "T-120_counter_get",
			src:      `local v = c:get()`,
			bindings: bcnt,
			wantOps:  []Op{{Opcode: OpLoadAddr, Dst: 0, Op1: cnt, Op2: 5, Op3: nr}},
		},
		{
			// T-124: :set → OpStoreAddr.
			name:     "T-124_counter_set",
			src:      `c:set(7)`,
			bindings: bcnt,
			wantOps: []Op{
				{Opcode: OpLoadImm, Dst: 0, Op1: 7},
				{Opcode: OpStoreAddr, Dst: 0, Op1: cnt, Op2: 5, Op3: nr},
			},
		},
		{
			// T-128: :get_at 1-arg PerPlayer → OpLoadAddr with index reg.
			name:     "T-128_counter_get_at_1arg",
			src:      `local v = c:get_at(ctx.actor_player)`,
			bindings: bcnt,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokAP, Op3: nr},
				{Opcode: OpLoadAddr, Dst: 1, Op1: cnt, Op2: 5, Op3: 0},
			},
		},
		{
			// T-129: :get_at 2-arg PerChar → OpCall fall-through with Dst=reg
			// (counterMethodsReturnValue includes get_at multi-arg form).
			name:     "T-129_counter_get_at_2arg_perchar",
			src:      `local v = c:get_at(ctx.actor_player, ctx.actor_char)`,
			bindings: bcnt,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokAP, Op3: nr},
				{Opcode: OpLoadAddr, Dst: 1, Op1: ctxF, Op2: tokAC, Op3: nr},
				{Opcode: OpLoadReg, Dst: 2, Op1: 0},
				{Opcode: OpLoadReg, Dst: 3, Op1: 1},
				{Opcode: OpCall, Dst: 4, Op1: int16(engine.TokMGetAt), Op2: 5, Op3: 2},
			},
		},
		{
			// T-132: :add 1-arg.
			name:     "T-132_counter_add_1arg",
			src:      `c:add(1)`,
			bindings: bcnt,
			wantOps: []Op{
				{Opcode: OpLoadImm, Dst: 0, Op1: 1},
				{Opcode: OpLoadReg, Dst: 1, Op1: 0},
				{Opcode: OpCall, Dst: nr, Op1: int16(engine.TokMAdd), Op2: 5, Op3: 1},
			},
		},
		{
			// T-133: :add 0-arg (Self/ActiveStatus scope) — IR-1.6 must
			// not reject 0-arg variants (was rejected by old arity check).
			name:     "T-133_counter_add_0arg",
			src:      `c:add()`,
			bindings: bcnt,
			wantOps: []Op{
				{Opcode: OpCall, Dst: nr, Op1: int16(engine.TokMAdd), Op2: 5, Op3: nr},
			},
		},
		{
			// T-138: :sub_at 3-arg PerChar.
			name:     "T-138_counter_sub_at_3arg",
			src:      `c:sub_at(ctx.actor_player, ctx.actor_char, 1)`,
			bindings: bcnt,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokAP, Op3: nr},
				{Opcode: OpLoadAddr, Dst: 1, Op1: ctxF, Op2: tokAC, Op3: nr},
				{Opcode: OpLoadImm, Dst: 2, Op1: 1},
				{Opcode: OpLoadReg, Dst: 3, Op1: 0},
				{Opcode: OpLoadReg, Dst: 4, Op1: 1},
				{Opcode: OpLoadReg, Dst: 5, Op1: 2},
				{Opcode: OpCall, Dst: nr, Op1: int16(engine.TokMSubAt), Op2: 5, Op3: 3},
			},
		},
		{
			// T-140: :cmax returns value (Dst=reg) — counterMethodsReturnValue.
			name:     "T-140_counter_cmax_in_compare",
			src:      `if c:get() < c:cmax() then return end`,
			bindings: bcnt,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: cnt, Op2: 5, Op3: nr},
				{Opcode: OpCall, Dst: 1, Op1: int16(engine.TokMCmax), Op2: 5, Op3: nr},
				{Opcode: OpBinOp, Dst: 2, Op1: BinLt, Op2: 0, Op3: 1},
				{Opcode: OpCJump, Op1: 2, Op2: 6},
				{Opcode: OpReturn},
				{Opcode: OpJump, Op1: 6},
			},
		},
		{
			// T-142: :fill_all 2-arg PerChar — was rejected by IR-1 arity=1.
			name:     "T-142_counter_fill_all_2arg",
			src:      `c:fill_all(ctx.actor_player, 0)`,
			bindings: bcnt,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokAP, Op3: nr},
				{Opcode: OpLoadImm, Dst: 1, Op1: 0},
				{Opcode: OpLoadReg, Dst: 2, Op1: 0},
				{Opcode: OpLoadReg, Dst: 3, Op1: 1},
				{Opcode: OpCall, Dst: nr, Op1: int16(engine.TokMFillAll), Op2: 5, Op3: 2},
			},
		},
		// --- Method error cases (T-159..T-162) ---------------------
		{
			name:     "T-159_unknown_method",
			src:      `c:nonexistent()`,
			bindings: bcnt,
			wantErr:  "unsupported method",
		},
		{
			name:     "T-160_counter_method_on_card",
			src:      `r:get()`,
			bindings: map[string]TypedBinding{"r": {Kind: BindingCard, ID: 3}},
			wantErr:  "is not a counter",
		},
		{
			name:     "T-162_method_on_non_ident_receiver",
			src:      `(ctx.value + 1):get()`,
			bindings: bcnt,
			wantErr:  "non-ident receiver",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			chunk := parseBody(t, tc.src)
			got, err := CompileHookIR(chunk, tc.bindings)
			if tc.wantErr != "" {
				if err == nil {
					t.Fatalf("expected error containing %q, got nil", tc.wantErr)
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

// TestCharAttrMethods — T-150..T-158: each char-attr method emits
// OpLoadAddr AddrCharAttr with method-specific token. Parametrized
// over all 8 methods.
func TestCharAttrMethods(t *testing.T) {
	bch := map[string]TypedBinding{"ch": {Kind: BindingChar, ID: 9}}
	cases := []struct {
		method string
		tok    int
	}{
		{"hp", engine.TokMHp},
		{"energy", engine.TokMEnergy},
		{"alive", engine.TokMAlive},
		{"owner_player", engine.TokMOwnerPlayer},
		{"owner_char", engine.TokMOwnerChar},
		{"name", engine.TokMName},
		{"element", engine.TokMElement},
		{"weapon", engine.TokMWeapon},
	}
	for _, tc := range cases {
		t.Run("T-150_"+tc.method, func(t *testing.T) {
			src := `local v = ch:` + tc.method + `()`
			chunk := parseBody(t, src)
			got, err := CompileHookIR(chunk, bch)
			if err != nil {
				t.Fatalf("compile :%s: %v", tc.method, err)
			}
			want := []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: AddrLocalVar, Op2: 9, Op3: NullReg},
				{Opcode: OpLoadAddr, Dst: 1, Op1: AddrCharAttr, Op2: int16(tc.tok), Op3: 0},
			}
			if !reflect.DeepEqual(got.MainOps, want) {
				t.Fatalf(":%s ops mismatch\nwant: %s\n got: %s", tc.method, formatOps(want), formatOps(got.MainOps))
			}
		})
	}
}
