package ir

// Call / TableCtor / FuncLit coverage per TEST_PLAN.md (T-170..T-193).
// Builtin calls, kwargs, defer_fn FuncLit handling, and rejection
// cases for unsupported call shapes.

import (
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestCallsAndKwargs(t *testing.T) {
	cases := []struct {
		name    string
		src     string
		check   func(t *testing.T, h CompiledHook)
		wantErr string
	}{
		{
			// T-172: multi-key kwargs — OpKwArg ops emitted in field order.
			name: "T-172_multi_kwargs",
			src:  `deal_damage(Target.EnemyActive, Element.Physical, 1, { source = Source.Skill, element = Element.Fire })`,
			check: func(t *testing.T, h CompiledHook) {
				var nKw, nCall int
				kwKeys := []int16{}
				for _, op := range h.MainOps {
					if op.Opcode == OpKwArg {
						nKw++
						kwKeys = append(kwKeys, op.Op1)
					}
					if op.Opcode == OpCall && op.Op1 == int16(engine.TokDealDamage) {
						nCall++
					}
				}
				if nKw != 2 {
					t.Errorf("want 2 OpKwArg, got %d", nKw)
				}
				if nCall != 1 {
					t.Errorf("want 1 OpCall TokDealDamage, got %d", nCall)
				}
				// TableCtor preserves Lua field order.
				if len(kwKeys) == 2 && (kwKeys[0] != int16(engine.TokKwSource) || kwKeys[1] != int16(engine.TokKwElement)) {
					t.Errorf("kwarg order wrong: got [%d, %d], want [TokKwSource=%d, TokKwElement=%d]",
						kwKeys[0], kwKeys[1], engine.TokKwSource, engine.TokKwElement)
				}
			},
		},
		{
			// T-175: 0-arg builtin call. Op2=0, Op3=NullReg.
			name: "T-175_zero_arg_call",
			src:  `local p = context_player()`,
			check: func(t *testing.T, h CompiledHook) {
				if len(h.MainOps) != 1 {
					t.Fatalf("want 1 op, got %d", len(h.MainOps))
				}
				op := h.MainOps[0]
				if op.Opcode != OpCall || op.Op1 != int16(engine.TokContextPlayer) {
					t.Errorf("want OpCall TokContextPlayer, got %+v", op)
				}
				if op.Op2 != 0 || op.Op3 != NullReg {
					t.Errorf("0-arg call should have Op2=0, Op3=NullReg, got Op2=%d Op3=%d", op.Op2, op.Op3)
				}
			},
		},
		{
			// T-182: empty TableCtor — 0 OpKwArgs preceding OpCall.
			name: "T-182_empty_table",
			src:  `deal_damage(Target.EnemyActive, Element.Physical, 1, {})`,
			check: func(t *testing.T, h CompiledHook) {
				var nKw int
				for _, op := range h.MainOps {
					if op.Opcode == OpKwArg {
						nKw++
					}
				}
				if nKw != 0 {
					t.Errorf("empty table should emit 0 OpKwArg, got %d", nKw)
				}
			},
		},
		{
			// T-193: nested defer_fn — Lambdas length ≥2; one lambda
			// contains OpDeferFn (the outer), one contains the OpCall
			// to heal (the inner). Inner lambda gets the lower index
			// because it's appended first (compiled depth-first).
			name: "T-193_nested_defer_fn",
			src:  `defer_fn(function() defer_fn(function() heal(Target.OwnActive, 1) end) end)`,
			check: func(t *testing.T, h CompiledHook) {
				if len(h.Lambdas) < 2 {
					t.Fatalf("want ≥2 lambdas, got %d", len(h.Lambdas))
				}
				var lambdaWithDefer, lambdaWithCall int
				for _, lam := range h.Lambdas {
					for _, op := range lam {
						if op.Opcode == OpDeferFn {
							lambdaWithDefer++
						}
						if op.Opcode == OpCall && op.Op1 == int16(engine.TokHeal) {
							lambdaWithCall++
						}
					}
				}
				if lambdaWithDefer != 1 {
					t.Errorf("want exactly 1 lambda with OpDeferFn (the outer), got %d", lambdaWithDefer)
				}
				if lambdaWithCall != 1 {
					t.Errorf("want exactly 1 lambda with OpCall TokHeal (the inner), got %d", lambdaWithCall)
				}
			},
		},
		// --- Error cases ----------------------------------------------
		{
			name:    "T-176_unknown_builtin",
			src:     `bogus_fn()`,
			wantErr: "unknown builtin",
		},
		{
			name:    "T-177_non_ident_func",
			src:     `(ctx.value + 1)(1)`,
			wantErr: "non-ident func",
		},
		{
			name:    "T-185_numeric_key_in_table",
			src:     `deal_damage(Target.EnemyActive, Element.Physical, 1, { foo = 0 })`,
			wantErr: "unknown kwarg key",
		},
		{
			name:    "T-190_funclit_in_local_decl",
			src:     `local f = function() end`,
			wantErr: "unsupported expression",
		},
		{
			// T-190: defer_fn(extra, FuncLit) — FuncLit not last arg rejected.
			name:    "T-190_funclit_not_last_arg",
			src:     `defer_fn(function() end, 1)`,
			wantErr: "unsupported expression",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			chunk := parseBody(t, tc.src)
			got, err := CompileHookIR(chunk, nil)
			if tc.wantErr != "" {
				if err == nil {
					t.Fatalf("want error containing %q, got nil (ops=%s)", tc.wantErr, formatOps(got.MainOps))
				}
				if !strings.Contains(err.Error(), tc.wantErr) {
					t.Fatalf("want error containing %q, got %q", tc.wantErr, err.Error())
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if tc.check != nil {
				tc.check(t, got)
			}
		})
	}
}
