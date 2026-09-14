package factory

import (
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

func TestFinalizeReportsEvenOneUnsupportedHook(t *testing.T) {
	g := &engine.Game{Hooks: engine.NewHookRegistry()}
	rt := interp.NewRuntime(g)
	for i := 0; i < 101; i++ {
		src := "return 1"
		if i == 100 {
			src = "missing_builtin()"
		}
		tokens, err := interp.Tokenize([]byte(src))
		if err != nil {
			t.Fatal(err)
		}
		body, err := interp.Parse(tokens)
		if err != nil {
			t.Fatal(err)
		}
		g.Hooks.Register(engine.Hook{Type: engine.HookSkillUse, BodyAny: body, Source: "fixture#0"})
	}
	ok, failures := finalizeHookIRs(g, rt)
	if ok != 100 || len(failures) != 1 || !strings.Contains(failures[0].Error(), "fixture") {
		t.Fatalf("expected complete compile diagnostics: ok=%d failures=%v", ok, failures)
	}
}
