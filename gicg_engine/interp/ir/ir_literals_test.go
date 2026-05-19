package ir

// Literal + load coverage per TEST_PLAN.md section 2 (T-001..T-091).
// Covers LocalDecl shapes, literal kinds (Num/Bool/Nil out of range),
// Ident lookup paths, BinOp/UnaryOp full operator set, and DotAccess
// variants. Each case is a small, self-contained AST → expected ops.

import (
	"reflect"
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestLiteralsAndBinOps(t *testing.T) {
	const (
		ctxF = AddrCtxField
		enum = AddrEnum
		nr   = NullReg
	)
	tokVal := int16(engine.TokCtxValue)
	tokHit := int16(engine.TokCtxHit)
	tokElemFire := int16(engine.TokElementFire)

	cases := []struct {
		name     string
		src      string
		bindings map[string]TypedBinding
		wantOps  []Op
		wantErr  string
	}{
		// --- LocalDecl shapes (T-001..T-004) -----------------------
		{
			name:    "T-001_local_with_imm",
			src:     `local x = 5`,
			wantOps: []Op{{Opcode: OpLoadImm, Dst: 0, Op1: 5}},
		},
		{
			name: "T-004_multi_name_local",
			src:  `local a, b = 1, 2`,
			wantOps: []Op{
				{Opcode: OpLoadImm, Dst: 0, Op1: 1},
				{Opcode: OpLoadImm, Dst: 1, Op1: 2},
			},
		},
		// --- NumberLit boundaries (T-050..T-057) -------------------
		{
			name:    "T-051_zero",
			src:     `local x = 0`,
			wantOps: []Op{{Opcode: OpLoadImm, Dst: 0, Op1: 0}},
		},
		{
			// Parser generates UnaryOp(NEG, NumberLit(1)), not NumberLit(-1).
			name: "T-052_negative",
			src:  `local x = -1`,
			wantOps: []Op{
				{Opcode: OpLoadImm, Dst: 0, Op1: 1},
				{Opcode: OpUnaryOp, Dst: 1, Op1: UnaryNeg, Op2: 0},
			},
		},
		{
			name:    "T-053_max_int16",
			src:     `local x = 32767`,
			wantOps: []Op{{Opcode: OpLoadImm, Dst: 0, Op1: 32767}},
		},
		{
			name:    "T-055_above_int16_max",
			src:     `local x = 32768`,
			wantErr: "out of int16 range",
		},
		// --- BoolLit / NilLit (T-060..T-063) -----------------------
		{
			name:    "T-060_bool_true",
			src:     `local x = true`,
			wantOps: []Op{{Opcode: OpLoadImm, Dst: 0, Op1: 1}},
		},
		{
			name:    "T-061_bool_false",
			src:     `local x = false`,
			wantOps: []Op{{Opcode: OpLoadImm, Dst: 0, Op1: 0}},
		},
		{
			name:    "T-062_nil_uses_OpLoadNil",
			src:     `local x = nil`,
			wantOps: []Op{{Opcode: OpLoadNil, Dst: 0}},
		},
		// --- BinOp full set (T-080..T-083) -------------------------
		{
			name: "T-080_arith_add",
			src:  `ctx.value = ctx.value + 1`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokVal, Op3: nr},
				{Opcode: OpLoadImm, Dst: 1, Op1: 1},
				{Opcode: OpBinOp, Dst: 2, Op1: BinAdd, Op2: 0, Op3: 1},
				{Opcode: OpStoreAddr, Dst: 2, Op1: ctxF, Op2: tokVal, Op3: nr},
			},
		},
		{
			name: "T-082_ordering_le",
			src:  `if ctx.value <= 0 then return end`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokVal, Op3: nr},
				{Opcode: OpLoadImm, Dst: 1, Op1: 0},
				{Opcode: OpBinOp, Dst: 2, Op1: BinLe, Op2: 0, Op3: 1},
				{Opcode: OpCJump, Op1: 2, Op2: 6},
				{Opcode: OpReturn},
				{Opcode: OpJump, Op1: 6},
			},
		},
		{
			name: "T-083_logic_or",
			src:  `if ctx.hit or ctx.paid then return end`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokHit, Op3: nr},
				{Opcode: OpLoadAddr, Dst: 1, Op1: ctxF, Op2: int16(engine.TokCtxPaid), Op3: nr},
				{Opcode: OpBinOp, Dst: 2, Op1: BinOr, Op2: 0, Op3: 1},
				{Opcode: OpCJump, Op1: 2, Op2: 6},
				{Opcode: OpReturn},
				{Opcode: OpJump, Op1: 6},
			},
		},
		// --- UnaryOp NEG (T-091) -----------------------------------
		{
			name: "T-091_unary_neg",
			src:  `ctx.value = -ctx.value`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokVal, Op3: nr},
				{Opcode: OpUnaryOp, Dst: 1, Op1: UnaryNeg, Op2: 0},
				{Opcode: OpStoreAddr, Dst: 1, Op1: ctxF, Op2: tokVal, Op3: nr},
			},
		},
		// --- DotAccess (T-100..T-103) ------------------------------
		{
			name: "T-100_ctx_field_load",
			src:  `local v = ctx.value`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokVal, Op3: nr},
			},
		},
		{
			name: "T-101_enum_load",
			src:  `local e = Element.Fire`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: enum, Op2: tokElemFire, Op3: nr},
			},
		},
		{
			// OQ-3: ch.hp ≡ ch:hp() when ch is Char-bound.
			name:     "T-102_char_attr_field_style",
			src:     `local h = ch.hp`,
			bindings: map[string]TypedBinding{"ch": {Kind: BindingChar, ID: 11}},
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: AddrLocalVar, Op2: 11, Op3: nr},
				{Opcode: OpLoadAddr, Dst: 1, Op1: AddrCharAttr, Op2: int16(engine.TokMHp), Op3: 0},
			},
		},
		{
			name:    "T-103_dot_on_unbound_ident_rejects",
			src:     `local v = foo.bar`,
			wantErr: "unsupported DotAccess",
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
