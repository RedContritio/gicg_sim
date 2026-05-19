package ir

// Integration smoke against real DSL fixtures from data/pools/. Guards
// against regressions that pass unit goldens but break on real hook bodies
// (e.g., AST shapes not covered by the synthetic table cases).

import (
	"os"
	"testing"

	"gicg_mono/gicg_engine/interp"
)

// extractHookBody finds a top-level `<hook>(function(ctx) BODY end)` call
// in src and returns BODY as a *Chunk. Lives here (not ir_test.go) because
// only the integration cases consume it.
func extractHookBody(t *testing.T, src, hookName string) *interp.Chunk {
	t.Helper()
	chunk := parseBody(t, src)
	for _, stmt := range chunk.Stmts {
		es, ok := stmt.(*interp.ExprStmt)
		if !ok {
			continue
		}
		call, ok := es.Expr.(*interp.Call)
		if !ok {
			continue
		}
		id, ok := call.Func.(*interp.Ident)
		if !ok || id.Name != hookName {
			continue
		}
		// Last arg is the FuncLit (some hooks like on_reaction_damage take prio first).
		if len(call.Args) == 0 {
			continue
		}
		fl, ok := call.Args[len(call.Args)-1].(*interp.FuncLit)
		if !ok {
			continue
		}
		return fl.Body
	}
	t.Fatalf("hook %q not found in src", hookName)
	return nil
}

func TestCompileHookIR_RealHookTestBasic(t *testing.T) {
	src, err := os.ReadFile("../../../data/pools/test_basic/cards/测试卡_增幅.lua")
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}
	bindings := map[string]TypedBinding{
		"ref":  {Kind: BindingCard, ID: 100},
		"buff": {Kind: BindingCounter, ID: 7},
	}
	for _, hook := range []string{"on_card_play", "on_damage_mul"} {
		body := extractHookBody(t, string(src), hook)
		ops, err := CompileHookIR(body, bindings)
		if err != nil {
			t.Fatalf("hook %s: compile error: %v", hook, err)
		}
		if len(ops) == 0 {
			t.Fatalf("hook %s: empty op slice", hook)
		}
	}
}

func TestCompileHookIR_RealHookLegacy(t *testing.T) {
	src, err := os.ReadFile("../../../data/pools/v_legacy/cards/L4/玄冰.lua")
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}
	// 玄冰's on_card_play uses only :set + ctx.card_ref + ref — fully supported.
	body := extractHookBody(t, string(src), "on_card_play")
	bindings := map[string]TypedBinding{
		"ref":    {Kind: BindingCard, ID: 200},
		"active": {Kind: BindingCounter, ID: 11},
	}
	ops, err := CompileHookIR(body, bindings)
	if err != nil {
		t.Fatalf("compile error: %v", err)
	}
	if len(ops) == 0 {
		t.Fatalf("empty op slice")
	}
}
