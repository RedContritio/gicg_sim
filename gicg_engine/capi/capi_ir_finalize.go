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

// extractTopLevelBindings scans a parsed file chunk for top-level locals
// that hook bodies close over. Three shapes recognized:
//
//  1. `local X = declare_<kind>(...)` / `local X = get_<kind>(...)` —
//     domain bindings (counter / card / char / skill / reaction). The
//     compiler treats X as opaque AddrLocalVar with an engine-assigned
//     ID; the encoder embeds the ID as a categorical token.
//
//  2. `local X = <NumberLit>` / `local X = <BoolLit>` (RC2) — file-top
//     numeric/bool constant like `local INITIAL_HAND = 5`. Compiler
//     inlines the value as OpLoadImm at every read site, so the
//     constant is visible as a literal to the encoder.
//
//  3. `local X = <RecvIdent>:<method>(...)` (RC2) — bound to a known
//     char/counter binding's method, e.g. `local my_player =
//     赤蝶:owner_player()`. We don't statically resolve the value, so
//     X gets an opaque BindingChar placeholder ID; the IR compiler
//     treats every X reference as AddrLocalVar load.
//
// Anything else (general expressions, unknown method receivers) is
// skipped — the hook body will fail-loudly with "undefined identifier"
// if it tries to read those names, which is the desired behavior so the
// G2 coverage test catches new patterns at audit time.
func extractTopLevelBindings(chunk *interp.Chunk, nextID *int16) map[string]ir.TypedBinding {
	out := map[string]ir.TypedBinding{}
	// First pass: collect declare_*/get_* style bindings (need their
	// IDs available when the second pass classifies MethodCall extras).
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

			// Shape 2: numeric / bool constant — inline at compile time.
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

			// Shape 3: method-call placeholder (`local my_player = X:owner_player()`).
			// Only register if the receiver itself is a known binding to
			// avoid catching unknown identifiers; we don't care what the
			// value is — encoder treats it opaquely.
			if mc, ok := expr.(*interp.MethodCall); ok {
				if recvID, isIdent := mc.Object.(*interp.Ident); isIdent {
					if _, recvBound := out[recvID.Name]; recvBound {
						out[name] = ir.TypedBinding{Kind: ir.BindingChar, ID: *nextID}
						*nextID++
						continue
					}
				}
			}

			// Shape 1: declare_*/get_* call.
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
				// Reactions don't have a get_*: they're declared once per
				// reaction key in data/system/reactions/*.lua and the
				// handle is passed verbatim to set_reaction_kind(...).
				kind = ir.BindingReaction
			case strings.HasPrefix(ident.Name, "on_"):
				// RC2: `local prepare_id = on_action_prepare(function(ctx) ... end)`
				// captures the hook's runtime ID for later `was_applied(ctx, prepare_id)`
				// queries. The ID is an opaque int — encoder treats it as
				// a Skill-kind placeholder (any opaque kind would do; Skill
				// is the closest semantic).
				kind = ir.BindingSkill
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
