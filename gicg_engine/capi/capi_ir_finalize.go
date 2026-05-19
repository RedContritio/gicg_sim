package main

// IR-2.b finalization: after all DSL files have been loaded (system
// files + char declarations + per-binding char files + shared cards),
// walk every registered hook, extract closure-captured bindings from
// the file the hook was registered in, compile the hook body AST →
// IR, and attach as engine.Hook.Repr. The engine package itself
// doesn't import interp/ir (would cycle); this file lives in capi/
// where importing both is allowed.

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
	"gicg_mono/gicg_engine/interp/ir"
)

// finalizeHookIRs walks rt.LoadedFiles, extracts per-file top-level
// bindings (declare_*/get_* LocalDecls), then walks g.Hooks and compiles
// each hook body AST to ir.CompiledHook with the matching file's bindings.
// Compile errors are silently skipped — Hook.Repr stays nil, observation
// layer falls back to the legacy Tokens path. Total successful and failed
// compile counts are returned for diagnostic logging.
func finalizeHookIRs(g *engine.Game, rt *interp.Runtime) (okN, failN int) {
	// Build per-file-basename → bindings map. Use ascending placeholder
	// IDs so the same ident across two games sees the same TypedBinding.ID;
	// IDs need not match engine counter slots — encoder treats them as
	// opaque categorical tokens.
	fileBindings := map[string]map[string]ir.TypedBinding{}
	var nextID int16 = 1
	for _, path := range rt.LoadedFiles {
		chunk := interp.CachedChunk(path)
		if chunk == nil {
			continue
		}
		base := strings.TrimSuffix(filepath.Base(path), ".lua")
		if _, exists := fileBindings[base]; exists {
			continue // same file loaded twice; first wins
		}
		fileBindings[base] = extractTopLevelBindings(chunk, &nextID)
	}

	diag := os.Getenv("IR_DIAG") != ""
	for _, h := range g.Hooks.AllHooks() {
		body, ok := h.BodyAny.(*interp.Chunk)
		if !ok || body == nil {
			continue
		}
		// h.Source is "<file>#<idx>" (per builtins_counter_hooks.go:65-71)
		// to disambig multiple hooks within one file for the visualizer.
		// fileBindings is keyed by file basename (bindings are file-scoped
		// — every hook in the same file sees the same captured locals),
		// so strip the #idx suffix before lookup.
		sourceKey := h.Source
		if i := strings.IndexByte(sourceKey, '#'); i >= 0 {
			sourceKey = sourceKey[:i]
		}
		bindings := fileBindings[sourceKey]
		compiled, err := ir.CompileHookIR(body, bindings)
		if err != nil {
			failN++
			if diag {
				fmt.Fprintf(os.Stderr, "[IR-DIAG-FAIL] source=%q nbindings=%d err=%v\n", h.Source, len(bindings), err)
			}
			continue
		}
		h.Repr = compiled
		okN++
	}
	return okN, failN
}

// extractTopLevelBindings scans a parsed file chunk for top-level
// `local X = declare_<kind>(...)` / `local X = get_<kind>(...)` patterns
// and assigns sequential placeholder IDs. Mirrors the test helper at
// gicg_engine/interp/ir/ir_integration_test.go but lives here so capi
// doesn't depend on _test.go files.
func extractTopLevelBindings(chunk *interp.Chunk, nextID *int16) map[string]ir.TypedBinding {
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
			call, ok := ld.Exprs[i].(*interp.Call)
			if !ok {
				continue
			}
			ident, ok := call.Func.(*interp.Ident)
			if !ok {
				continue
			}
			var kind ir.TypedBindingKind
			switch ident.Name {
			case "declare_counter", "get_counter":
				kind = ir.BindingCounter
			case "declare_card", "get_card":
				kind = ir.BindingCard
			case "declare_char", "get_char":
				kind = ir.BindingChar
			case "declare_skill", "get_skill":
				kind = ir.BindingSkill
			case "declare_reaction":
				// Reactions don't have a get_*: they're declared once per
				// reaction key in data/system/reactions/*.lua and the
				// handle is passed verbatim to set_reaction_kind(...).
				kind = ir.BindingReaction
			default:
				continue
			}
			out[name] = ir.TypedBinding{Kind: kind, ID: *nextID}
			*nextID++
			// declare_card may return (ref, my_player, my_char) —
			// bind extras as opaque Char placeholders so hook bodies
			// referencing my_player/my_char compile.
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
