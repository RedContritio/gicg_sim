package interp

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestLoadedHookCannotMutateSharedDefinitions(t *testing.T) {
	for _, body := range []string{
		"shared = shared + 1",
		"settings.value = 2",
		"settings[\"value\"] = 2",
		"local alias = settings\nalias.value = 2",
		"Element.Fire = 99",
	} {
		t.Run(body, func(t *testing.T) {
			g := &engine.Game{Hooks: engine.NewHookRegistry()}
			rt := NewRuntime(g)
			rt.RegisterBuiltins()
			path := filepath.Join(t.TempDir(), "immutable.lua")
			source := "local shared = 0\nlocal settings = { value = 1 }\non_skill_use(function(ctx)\n" + body + "\nend)"
			if err := os.WriteFile(path, []byte(source), 0600); err != nil {
				t.Fatal(err)
			}
			if err := rt.ExecFileSandboxed(path); err != nil {
				t.Fatal(err)
			}
			for attempt := 0; attempt < 2; attempt++ {
				branch := rt.Clone()
				var recovered any
				func() {
					defer func() { recovered = recover() }()
					branch.Game.FireEventHooks(engine.HookSkillUse, &engine.EventContext{ActorPlayer: 0})
				}()
				err, ok := recovered.(*engine.RuleError)
				if !ok || !strings.Contains(err.Error(), "shared rule") {
					t.Fatalf("shared mutation did not fail: %v", recovered)
				}
				if g.Failure != nil {
					t.Fatal("failed branch poisoned the source")
				}
			}
		})
	}
}

func TestFrozenDefinitionsAllowHookLocalMutation(t *testing.T) {
	outer := NewEnv(nil)
	outer.SetLocal("constant", 10)
	freezeDefinitions(outer)
	local := NewEnv(outer)
	local.SetLocal("count", 0)
	child := NewEnv(local)
	if err := child.setDSL("count", 2); err != nil {
		t.Fatal(err)
	}
	if got, _ := local.Get("count"); got != 2 {
		t.Fatal("deferred closure could not mutate its own captured hook-local value")
	}
	if err := child.setDSL("constant", 9); err == nil {
		t.Fatal("mutable local scope allowed mutation of shared parent")
	}
	table := NewTable()
	if err := table.setDSL("value", 3); err != nil {
		t.Fatal(err)
	}
}
