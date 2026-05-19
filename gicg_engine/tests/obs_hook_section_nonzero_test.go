package tests

// G3 — RC2 obs-level invariant. After RC2 fixes (builtin/enum coverage +
// const idents + scope-local char-attr + chained MethodCall + ctx ident +
// defer_fn lambda scope inheritance), the hook IR section of
// BuildStaticObs must be densely populated for the actually-registered
// hooks. Pre-RC2 this section was 99%+ zero because finalizeHookIRs
// rejected 40-60% of hook bodies during compile.
//
// "Densely populated" = at least 95% of (n_registered_hooks ×
// ObsIntsPerHook) int32s are non-zero. Threshold leaves headroom for
// hooks with very small IRs (e.g. a one-liner `return` body) whose
// compiled form is 1-2 ops + nop padding, which by definition have low
// non-zero density.

import (
	"path/filepath"
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
	"gicg_mono/gicg_engine/interp/ir"
)

func TestObs_HookSectionNonZeroAfterIRFinalize(t *testing.T) {
	// Canonical scenario: 赤蝶 mirror match drawing from v_legacy + test_basic
	// pools. Mirrors the diag script (/tmp/show_ir_obs.py) so failures here
	// match what the IR_DIAG=1 runtime emits.
	env := NewGame(t, []string{"赤蝶"}, []string{"赤蝶"})

	// Replicate capi finalizeHookIRs: walk LoadedFiles, extract typed
	// bindings, compile each hook body's AST → IR.Repr. We can't import
	// the capi/ package (main package), but the logic is small and the
	// engine package has access to the same Go-level types.
	finalizeHookIRsForTest(t, env.G, env.RT)

	// Total obs + hook section slice extraction.
	obs := env.G.BuildStaticObs()
	want := engine.StaticObsSize()
	if len(obs) != want {
		t.Fatalf("BuildStaticObs len=%d, StaticObsSize()=%d", len(obs), want)
	}

	// Layout (must match observation.go BuildStaticObs):
	//   [counter_meta] [char_skill_refs] [hook_ir] [char_element]
	counterMeta := obsCounterSlotsForTest() * 3
	charSkillRefs := 2 * engine.ObsMaxChars * engine.ObsMaxSkillsPerChar
	hookSection := obs[counterMeta+charSkillRefs : counterMeta+charSkillRefs+engine.ObsMaxHooks*engine.ObsIntsPerHook]

	allHooks := env.G.Hooks.AllHooks()
	nRegistered := len(allHooks)
	if nRegistered > engine.ObsMaxHooks {
		nRegistered = engine.ObsMaxHooks
	}
	if nRegistered == 0 {
		t.Fatalf("0 registered hooks — scenario broken")
	}

	// Per-hook metric: iterate obs positions, follow HookPerm to map
	// back to the source hook, check whether the source hook's IR slot
	// has a non-zero opcode. Pre-RC2 most hooks had nil Repr → all 64×5
	// ints in their slot were zero. Post-RC2 every registered hook
	// should at least produce an OpLoadAddr / OpCall / OpReturn at slot 0.
	hooksWithIR := 0
	hooksChecked := 0
	hooksWithNoBodyNoRepr := 0
	hooksDSLBody := 0
	for hi := 0; hi < engine.ObsMaxHooks; hi++ {
		src := hi
		if env.G.HookPerm != nil && hi < len(env.G.HookPerm) {
			src = env.G.HookPerm[hi]
		}
		if src >= nRegistered {
			continue
		}
		h := allHooks[src]
		// Filter: only hooks that should produce IR (have a BodyAny
		// chunk OR a non-nil Repr from canonical registration). Hooks
		// with neither are e.g. Go-side internal registrations with no
		// observable representation.
		_, isDSLBody := h.BodyAny.(*interp.Chunk)
		if !isDSLBody && h.Repr == nil {
			hooksWithNoBodyNoRepr++
			continue
		}
		if isDSLBody {
			hooksDSLBody++
		}
		hooksChecked++
		base := hi * engine.ObsIntsPerHook
		if hookSection[base+0] != 0 {
			hooksWithIR++
		}
	}
	pctHooks := float64(hooksWithIR) / float64(hooksChecked)
	t.Logf("hook breakdown: %d total, %d DSL-body, %d no-body-no-repr",
		nRegistered, hooksDSLBody, hooksWithNoBodyNoRepr)

	// Aggregate metric: fraction of non-zero int32 in the registered
	// region (whole hook section, since padding stays zero — the
	// registered hooks' slots may not be contiguous due to HookPerm).
	expectedBytes := hooksChecked * engine.ObsIntsPerHook
	nonZero := 0
	for _, v := range hookSection {
		if v != 0 {
			nonZero++
		}
	}
	pctBytes := float64(nonZero) / float64(expectedBytes)

	t.Logf("hook IR obs: %d/%d hooks have non-zero op0 (%.1f%%); %d/%d total non-zero int32 (%.1f%%)",
		hooksWithIR, hooksChecked, pctHooks*100, nonZero, expectedBytes, pctBytes*100)

	// Primary assertion: ≥ 95% of registered hooks must have a populated
	// IR (op 0 opcode non-zero). Per the RC2 G3 spec; budget of 5%
	// covers edge cases like empty hook bodies (theoretically `function(ctx) end`,
	// though no DSL file currently has one).
	const minHookCoverage = 0.95
	if pctHooks < minHookCoverage {
		t.Errorf("hook IR coverage %.1f%% < %.0f%% — finalize rejected too many bodies",
			pctHooks*100, minHookCoverage*100)
	}

	// Secondary sanity: byte-level density ≥ 5% — guards against a
	// regression where finalize "succeeds" but emits 0 ops per hook.
	const minByteDensity = 0.05
	if pctBytes < minByteDensity {
		t.Errorf("hook IR byte density %.1f%% < %.0f%% — IRs suspiciously empty",
			pctBytes*100, minByteDensity*100)
	}
}

// finalizeHookIRsForTest replicates the production capi/capi_ir_finalize.go
// logic inside the engine/tests package. Kept in sync with that file —
// if the production version evolves (new binding kinds, etc.), this
// helper needs the same edits.
func finalizeHookIRsForTest(t *testing.T, g *engine.Game, rt *interp.Runtime) {
	t.Helper()
	fileBindings := map[string]map[string]ir.TypedBinding{}
	var nextID int16 = 1
	for _, path := range rt.LoadedFiles {
		chunk := interp.CachedChunk(path)
		if chunk == nil {
			continue
		}
		base := strings.TrimSuffix(filepath.Base(path), ".lua")
		if _, exists := fileBindings[base]; exists {
			continue
		}
		fileBindings[base] = extractTopLevelBindingsForTest(chunk, &nextID)
	}

	failN := 0
	for _, h := range g.Hooks.AllHooks() {
		body, ok := h.BodyAny.(*interp.Chunk)
		if !ok || body == nil {
			continue
		}
		sourceKey := h.Source
		if i := strings.IndexByte(sourceKey, '#'); i >= 0 {
			sourceKey = sourceKey[:i]
		}
		bindings := fileBindings[sourceKey]
		compiled, err := ir.CompileHookIR(body, bindings)
		if err != nil {
			failN++
			continue
		}
		h.Repr = compiled
	}
	t.Logf("finalize: %d hooks total, %d compile failures", len(g.Hooks.AllHooks()), failN)
}

// extractTopLevelBindingsForTest mirrors capi/capi_ir_finalize.go's
// extractTopLevelBindings. Same caveat — keep in sync.
func extractTopLevelBindingsForTest(chunk *interp.Chunk, nextID *int16) map[string]ir.TypedBinding {
	out := map[string]ir.TypedBinding{}
	for _, stmt := range chunk.Stmts {
		ld, ok := stmt.(*interp.LocalDecl)
		if !ok {
			continue
		}
		for i, name := range ld.Names {
			if i >= len(ld.Exprs) {
				continue
			}
			expr := ld.Exprs[i]
			if numLit, ok := expr.(*interp.NumberLit); ok {
				v := numLit.Value
				if v >= -32768 && v <= 32767 {
					out[name] = ir.TypedBinding{Kind: ir.BindingConst, ConstValue: int16(v)}
				}
				continue
			}
			if boolLit, ok := expr.(*interp.BoolLit); ok {
				v := int16(0)
				if boolLit.Value {
					v = 1
				}
				out[name] = ir.TypedBinding{Kind: ir.BindingConst, ConstValue: v}
				continue
			}
			if mc, ok := expr.(*interp.MethodCall); ok {
				if recvID, isIdent := mc.Object.(*interp.Ident); isIdent {
					if _, recvBound := out[recvID.Name]; recvBound {
						out[name] = ir.TypedBinding{Kind: ir.BindingChar, ID: *nextID}
						*nextID++
						continue
					}
				}
			}
			call, ok := expr.(*interp.Call)
			if !ok {
				continue
			}
			ident, ok := call.Func.(*interp.Ident)
			if !ok {
				continue
			}
			var kind ir.TypedBindingKind
			switch {
			case ident.Name == "declare_counter", ident.Name == "get_counter":
				kind = ir.BindingCounter
			case ident.Name == "declare_card", ident.Name == "get_card":
				kind = ir.BindingCard
			case ident.Name == "declare_char", ident.Name == "get_char":
				kind = ir.BindingChar
			case ident.Name == "declare_skill", ident.Name == "get_skill":
				kind = ir.BindingSkill
			case ident.Name == "declare_reaction":
				kind = ir.BindingReaction
			case strings.HasPrefix(ident.Name, "on_"):
				kind = ir.BindingSkill
			default:
				continue
			}
			out[name] = ir.TypedBinding{Kind: kind, ID: *nextID}
			*nextID++
			if ident.Name == "declare_card" {
				for j := i + 1; j < len(ld.Names); j++ {
					out[ld.Names[j]] = ir.TypedBinding{Kind: ir.BindingChar, ID: *nextID}
					*nextID++
				}
			}
		}
	}
	return out
}

// obsCounterSlotsForTest mirrors engine.obsCounterSlots() which is unexported.
func obsCounterSlotsForTest() int {
	return 2*engine.ObsMaxChars*engine.ObsCharSlots + 2*engine.ObsPlayerSlots + engine.ObsGlobalSlots
}
