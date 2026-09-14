package factory

// IR-2.b finalization: after all DSL files have been loaded (system
// files + char declarations + per-binding char files + shared cards),
// walk every registered hook, extract closure-captured bindings from
// the file the hook was registered in, compile the hook body AST →
// IR, and attach as engine.Hook.Repr. The engine package itself
// doesn't import interp/ir (would cycle); this file lives in factory/
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
// Every compile or capacity error is returned to the factory. A partial rule
// observation is not an acceptable training environment.
func finalizeHookIRs(g *engine.Game, rt *interp.Runtime) (okN int, failures []error) {
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
		fileBindings[base] = extractTopLevelBindings(chunk, &nextID)
	}

	diag := os.Getenv("IR_DIAG") != ""
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
		if h.CounterParam != "" {
			local := make(map[string]ir.TypedBinding, len(bindings)+1)
			for k, v := range bindings {
				local[k] = v
			}
			local[h.CounterParam] = ir.TypedBinding{Kind: ir.BindingCounter, ID: nextID}
			nextID++
			bindings = local
		}
		compiled, err := ir.CompileHookIR(body, bindings)
		if err == nil && compiled.ObsOpCount() > engine.ObsMaxOpsPerHook {
			err = fmt.Errorf("rule observation needs %d ops, capacity is %d", compiled.ObsOpCount(), engine.ObsMaxOpsPerHook)
		}
		if err != nil {
			failures = append(failures, fmt.Errorf("hook %d source %q: %w", h.ID, h.Source, err))
			if diag {
				fmt.Fprintf(os.Stderr, "[IR-DIAG-FAIL] source=%q nbindings=%d err=%v\n", h.Source, len(bindings), err)
			}
			continue
		}
		h.Repr = compiled
		okN++
	}
	return okN, failures
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
