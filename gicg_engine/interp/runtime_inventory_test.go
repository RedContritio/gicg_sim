package interp

import (
	"reflect"
	"strings"
	"testing"
)

func TestRuntimeFieldInventory(t *testing.T) {
	groups := []string{
		// Immutable once loading finishes; copy identity on Clone, retain on reset.
		`Ruleset LoadedFiles DeckPadding ExplicitDecks`,
		// Per-runtime execution scratch; hook wrappers restore after dispatch.
		`CurrentOwnerPlayer CurrentOwnerChar CurrentContextPlayer CurrentCardTargetPlayer CurrentCardTargetChar DeferredFns currentHookContext`,
		// Loading scratch, never used to carry an effect between decisions.
		`CurrentSourceFile CurrentSourceHookIdx CurrentFileTalentOwner CurrentFileCharOwner`,
		// Game owns dynamic state; diagnostics are separate from simulation.
		`Game traceEnabled lastError`,
	}
	fields := map[string]bool{}
	for _, group := range groups {
		for _, field := range strings.Fields(group) {
			fields[field] = true
		}
	}
	typ := reflect.TypeOf(Runtime{})
	for i := 0; i < typ.NumField(); i++ {
		name := typ.Field(i).Name
		if !fields[name] {
			t.Errorf("unclassified Runtime.%s", name)
		}
		delete(fields, name)
	}
	if len(fields) != 0 {
		t.Errorf("stale Runtime fields: %v", fields)
	}
}
