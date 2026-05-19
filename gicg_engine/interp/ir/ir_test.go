package ir

import (
	"fmt"
	"reflect"
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// parseBody parses a hook-body string (statements only — no surrounding
// `function(ctx) … end`) into a *interp.Chunk. Shared with integration tests.
func parseBody(t *testing.T, src string) *interp.Chunk {
	t.Helper()
	toks, err := interp.Tokenize([]byte(src))
	if err != nil {
		t.Fatalf("tokenize: %v", err)
	}
	chunk, err := interp.Parse(toks)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	return chunk
}

func TestCompileHookIR(t *testing.T) {
	// Aliases to keep golden tables narrow.
	const (
		ctxF = AddrCtxField
		cnt  = AddrCounter
		attr = AddrCharAttr
		enum = AddrEnum
		nr   = NullReg
	)
	_ = attr // attr is exercised only via the integration tests' char-attr fixtures
	tokVal := int16(engine.TokCtxValue)
	tokHit := int16(engine.TokCtxHit)
	tokPaid := int16(engine.TokCtxPaid)
	tokSrc := int16(engine.TokCtxSource)
	tokAP := int16(engine.TokCtxActorPlayer)
	tokSrcSkill := int16(engine.TokSourceSkill)
	tokElemFire := int16(engine.TokElementFire)
	tokDealDmg := int16(engine.TokDealDamage)
	tokGetActive := int16(engine.TokGetActiveChar)
	tokMHp := int16(engine.TokMHp)
	tokMAddAt := int16(engine.TokMAddAt)
	tokMCmin := int16(engine.TokMCmin)
	tokMDecayAll := int16(engine.TokMDecayAll)

	cases := []struct {
		name     string
		src      string
		bindings map[string]TypedBinding
		wantOps  []Op
		wantErr  string
	}{
		{
			name:    "empty_body",
			src:     `return`,
			wantOps: []Op{{Opcode: OpReturn}},
		},
		{
			name: "unconditional_assign",
			src:  `ctx.value = 5`,
			wantOps: []Op{
				{Opcode: OpLoadImm, Dst: 0, Op1: 5},
				{Opcode: OpStoreAddr, Dst: 0, Op1: ctxF, Op2: tokVal, Op3: nr},
			},
		},
		{
			name: "conditional_return",
			src:  `if ctx.source ~= Source.Skill then return end`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokSrc, Op3: nr},
				{Opcode: OpLoadAddr, Dst: 1, Op1: enum, Op2: tokSrcSkill, Op3: nr},
				{Opcode: OpBinOp, Dst: 2, Op1: BinNeq, Op2: 0, Op3: 1},
				{Opcode: OpCJump, Op1: 2, Op2: 6},
				{Opcode: OpReturn},
				{Opcode: OpJump, Op1: 6},
			},
		},
		{
			name: "if_then_assign",
			src:  `if ctx.hit then ctx.value = ctx.value + 2 end`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokHit, Op3: nr},
				{Opcode: OpCJump, Op1: 0, Op2: 7},
				{Opcode: OpLoadAddr, Dst: 1, Op1: ctxF, Op2: tokVal, Op3: nr},
				{Opcode: OpLoadImm, Dst: 2, Op1: 2},
				{Opcode: OpBinOp, Dst: 3, Op1: BinAdd, Op2: 1, Op3: 2},
				{Opcode: OpStoreAddr, Dst: 3, Op1: ctxF, Op2: tokVal, Op3: nr},
				{Opcode: OpJump, Op1: 7},
			},
		},
		{
			name: "if_else",
			src:  `if ctx.hit then ctx.value = 1 else ctx.value = 2 end`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokHit, Op3: nr},
				{Opcode: OpCJump, Op1: 0, Op2: 5},
				{Opcode: OpLoadImm, Dst: 1, Op1: 1},
				{Opcode: OpStoreAddr, Dst: 1, Op1: ctxF, Op2: tokVal, Op3: nr},
				{Opcode: OpJump, Op1: 7},
				{Opcode: OpLoadImm, Dst: 2, Op1: 2},
				{Opcode: OpStoreAddr, Dst: 2, Op1: ctxF, Op2: tokVal, Op3: nr},
			},
		},
		{
			name: "if_elseif_else",
			src:  `if ctx.hit then ctx.value = 1 elseif ctx.paid then ctx.value = 2 else ctx.value = 3 end`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokHit, Op3: nr},
				{Opcode: OpCJump, Op1: 0, Op2: 5},
				{Opcode: OpLoadImm, Dst: 1, Op1: 1},
				{Opcode: OpStoreAddr, Dst: 1, Op1: ctxF, Op2: tokVal, Op3: nr},
				{Opcode: OpJump, Op1: 12},
				{Opcode: OpLoadAddr, Dst: 2, Op1: ctxF, Op2: tokPaid, Op3: nr},
				{Opcode: OpCJump, Op1: 2, Op2: 10},
				{Opcode: OpLoadImm, Dst: 3, Op1: 2},
				{Opcode: OpStoreAddr, Dst: 3, Op1: ctxF, Op2: tokVal, Op3: nr},
				{Opcode: OpJump, Op1: 12},
				{Opcode: OpLoadImm, Dst: 4, Op1: 3},
				{Opcode: OpStoreAddr, Dst: 4, Op1: ctxF, Op2: tokVal, Op3: nr},
			},
		},
		{
			name:     "counter_get_set",
			src:      `buff:set_at(ctx.actor_player, 1) buff:get_at(ctx.actor_player)`,
			bindings: map[string]TypedBinding{"buff": {Kind: BindingCounter, ID: 7}},
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokAP, Op3: nr},
				{Opcode: OpLoadImm, Dst: 1, Op1: 1},
				{Opcode: OpStoreAddr, Dst: 1, Op1: cnt, Op2: 7, Op3: 0},
				{Opcode: OpLoadAddr, Dst: 2, Op1: ctxF, Op2: tokAP, Op3: nr},
				{Opcode: OpLoadAddr, Dst: 3, Op1: cnt, Op2: 7, Op3: 2},
			},
		},
		{
			// :add_at lowers to a single OpCall keyed on TokMAddAt
			// (Op2 = counter id, Op3 = arg-block base). The compiler
			// no longer encodes a load-binop-store policy — that's
			// the IR-3 interpreter's call.
			name:     "counter_add_now_one_op",
			src:      `buff:add_at(ctx.actor_player, 1)`,
			bindings: map[string]TypedBinding{"buff": {Kind: BindingCounter, ID: 7}},
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokAP, Op3: nr},
				{Opcode: OpLoadImm, Dst: 1, Op1: 1},
				{Opcode: OpLoadReg, Dst: 2, Op1: 0},
				{Opcode: OpLoadReg, Dst: 3, Op1: 1},
				{Opcode: OpCall, Dst: nr, Op1: tokMAddAt, Op2: 7, Op3: 2},
			},
		},
		{
			// :cmin similarly — receiver in OpCall.Op2, single arg in
			// the contiguous block at Op3. Regression guard against
			// re-introducing the old 3-op load-binop-store pattern.
			name:     "counter_cmin_now_one_op",
			src:      `buff:cmin(5)`,
			bindings: map[string]TypedBinding{"buff": {Kind: BindingCounter, ID: 7}},
			wantOps: []Op{
				{Opcode: OpLoadImm, Dst: 0, Op1: 5},
				{Opcode: OpLoadReg, Dst: 1, Op1: 0},
				{Opcode: OpCall, Dst: nr, Op1: tokMCmin, Op2: 7, Op3: 1},
			},
		},
		{
			// 0-arg counter effect — proves gatherArgs returns NullReg
			// for empty args (no contiguous block allocated).
			name:     "counter_decay_all_no_args",
			src:      `buff:decay_all()`,
			bindings: map[string]TypedBinding{"buff": {Kind: BindingCounter, ID: 7}},
			wantOps: []Op{
				{Opcode: OpCall, Dst: nr, Op1: tokMDecayAll, Op2: 7, Op3: nr},
			},
		},
		{
			name: "logic_and_or_not",
			src:  `if not (ctx.hit and ctx.paid) then return end`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokHit, Op3: nr},
				{Opcode: OpLoadAddr, Dst: 1, Op1: ctxF, Op2: tokPaid, Op3: nr},
				{Opcode: OpBinOp, Dst: 2, Op1: BinAnd, Op2: 0, Op3: 1},
				{Opcode: OpUnaryOp, Dst: 3, Op1: UnaryNot, Op2: 2},
				{Opcode: OpCJump, Op1: 3, Op2: 7},
				{Opcode: OpReturn},
				{Opcode: OpJump, Op1: 7},
			},
		},
		{
			name: "call_builtin",
			src:  `deal_damage(ctx.actor_player, 0, 0, 2, Element.Fire, Source.Skill)`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokAP, Op3: nr},
				{Opcode: OpLoadImm, Dst: 1, Op1: 0},
				{Opcode: OpLoadImm, Dst: 2, Op1: 0},
				{Opcode: OpLoadImm, Dst: 3, Op1: 2},
				{Opcode: OpLoadAddr, Dst: 4, Op1: enum, Op2: tokElemFire, Op3: nr},
				{Opcode: OpLoadAddr, Dst: 5, Op1: enum, Op2: tokSrcSkill, Op3: nr},
				{Opcode: OpLoadReg, Dst: 6, Op1: 0},
				{Opcode: OpLoadReg, Dst: 7, Op1: 1},
				{Opcode: OpLoadReg, Dst: 8, Op1: 2},
				{Opcode: OpLoadReg, Dst: 9, Op1: 3},
				{Opcode: OpLoadReg, Dst: 10, Op1: 4},
				{Opcode: OpLoadReg, Dst: 11, Op1: 5},
				{Opcode: OpCall, Dst: 12, Op1: tokDealDmg, Op2: 6, Op3: 6},
			},
		},
		{
			name: "char_attr",
			src:  `local active = get_active_char(ctx.actor_player) if active:hp() < 5 then return end`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokAP, Op3: nr},
				{Opcode: OpLoadReg, Dst: 1, Op1: 0},
				{Opcode: OpCall, Dst: 2, Op1: tokGetActive, Op2: 1, Op3: 1},
				{Opcode: OpLoadAddr, Dst: 3, Op1: attr, Op2: tokMHp, Op3: 2},
				{Opcode: OpLoadImm, Dst: 4, Op1: 5},
				{Opcode: OpBinOp, Dst: 5, Op1: BinLt, Op2: 3, Op3: 4},
				{Opcode: OpCJump, Op1: 5, Op2: 9},
				{Opcode: OpReturn},
				{Opcode: OpJump, Op1: 9},
			},
		},
		{
			name:    "undefined_ident",
			src:     `foo:set(1)`,
			wantErr: "undefined",
		},
		{
			name: "nested_binop",
			src:  `ctx.value = ctx.value * 2 + ctx.hit`,
			wantOps: []Op{
				{Opcode: OpLoadAddr, Dst: 0, Op1: ctxF, Op2: tokVal, Op3: nr},
				{Opcode: OpLoadImm, Dst: 1, Op1: 2},
				{Opcode: OpBinOp, Dst: 2, Op1: BinMul, Op2: 0, Op3: 1},
				{Opcode: OpLoadAddr, Dst: 3, Op1: ctxF, Op2: tokHit, Op3: nr},
				{Opcode: OpBinOp, Dst: 4, Op1: BinAdd, Op2: 2, Op3: 3},
				{Opcode: OpStoreAddr, Dst: 4, Op1: ctxF, Op2: tokVal, Op3: nr},
			},
		},
		{
			name:    "reg_overflow",
			src:     buildRegOverflowSrc(MaxRegs + 1),
			wantErr: fmt.Sprintf("%d registers", MaxRegs),
		},
	}
	// Contract-validation tests (scope rules, binding kind mismatch, etc.)
	// live in ir_contracts_test.go.

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

func buildRegOverflowSrc(n int) string {
	var sb strings.Builder
	for i := range n {
		fmt.Fprintf(&sb, "local v%d = %d ", i, i)
	}
	return sb.String()
}

func formatOps(ops []Op) string {
	var sb strings.Builder
	sb.WriteString("[\n")
	for i, op := range ops {
		fmt.Fprintf(&sb, "  %2d: %+v\n", i, op)
	}
	sb.WriteString("]")
	return sb.String()
}

// --- Integration: compile real DSL hooks (smoke only, no exact-op assert).
