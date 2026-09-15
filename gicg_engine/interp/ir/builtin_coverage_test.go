package ir

// G2 — RC2 coverage audit. Walks every .lua under data/system and data/pools,
// extracts hook bodies (on_*(function(ctx) ... end)), and enumerates:
//   - Call.Func.Ident.Name → expected to resolve via engine.LookupBuiltin
//   - bare Ident.Name in non-receiver position → expected to be local-scope,
//     in declareBindings (declare_*/get_*), or a top-level numeric const
//     (handled by extractTopLevelBindings extension).
//   - DotAccess where receiver is enum-style (e.g. CostSlot.Any) →
//     expected to resolve via engine.LookupEnum.
//
// Failures here mean the IR compiler will reject those hook bodies, which is
// the root cause of the high finalizeHookIRs fail rate (G1 fires when
// fail_rate > 2%).
//
// Test PASSES with zero missing-builtin/enum reports after RC2. This is a
// permanent regression guard: any newly-introduced DSL builtin that lacks
// a Tok* + tokenMap entry surfaces here, not at runtime.

import (
	"os"
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

func TestCoverage_HookBuiltinsAndEnums(t *testing.T) {
	roots := []string{
		"../../../data/system",
		"../../../data/pools",
	}
	var files []string
	for _, root := range roots {
		f, err := findLuaFiles(root)
		if err != nil {
			t.Fatalf("walk %s: %v", root, err)
		}
		files = append(files, f...)
	}
	if len(files) == 0 {
		t.Fatalf("found 0 .lua under %v", roots)
	}

	missingBuiltins := map[string][]string{} // name → file:line list
	missingEnums := map[string][]string{}    // qualified name → file:line list

	for _, path := range files {
		// Parse on demand — the cache (interp.CachedChunk) is empty in a
		// pure unit-test context with no Runtime to call PreloadDSLFiles.
		src, err := os.ReadFile(path)
		if err != nil {
			t.Errorf("read %s: %v", path, err)
			continue
		}
		toks, err := interp.Tokenize(src)
		if err != nil {
			t.Errorf("tokenize %s: %v", path, err)
			continue
		}
		chunk, err := interp.Parse(toks)
		if err != nil {
			t.Errorf("parse %s: %v", path, err)
			continue
		}
		// Visit each `on_*(function(ctx) ... end)` body — those are the
		// closures the IR compiler walks at finalize time.
		for _, stmt := range chunk.Stmts {
			es, ok := stmt.(*interp.ExprStmt)
			if !ok {
				continue
			}
			call, ok := es.Expr.(*interp.Call)
			if !ok {
				continue
			}
			fnIdent, ok := call.Func.(*interp.Ident)
			if !ok || !strings.HasPrefix(fnIdent.Name, "on_") {
				continue
			}
			// Last arg may be the FuncLit. (Priority-form: `on_X(N, function...)`.)
			if len(call.Args) == 0 {
				continue
			}
			fl, ok := call.Args[len(call.Args)-1].(*interp.FuncLit)
			if !ok {
				continue
			}
			scanHookBody(fl.Body, path, missingBuiltins, missingEnums)
		}
	}

	if len(missingBuiltins) > 0 {
		names := sortedKeys(missingBuiltins)
		for _, n := range names {
			ctx := missingBuiltins[n]
			t.Errorf("unknown builtin %q used in %d hook(s), e.g. %s", n, len(ctx), ctx[0])
		}
	}
	if len(missingEnums) > 0 {
		names := sortedKeys(missingEnums)
		for _, n := range names {
			ctx := missingEnums[n]
			t.Errorf("unknown enum %q used in %d hook(s), e.g. %s", n, len(ctx), ctx[0])
		}
	}
}

// scanHookBody recursively walks a hook body chunk, recording any
// Call.Func.Ident.Name that engine.LookupBuiltin can't resolve and any
// EnumNS.X DotAccess that engine.LookupEnum can't resolve. defer_fn
// lambdas are visited transparently because they also become IR.
func scanHookBody(n interp.Node, path string, missBuiltins, missEnums map[string][]string) {
	var walk func(interp.Node)
	walk = func(n interp.Node) {
		if n == nil {
			return
		}
		switch v := n.(type) {
		case *interp.Chunk:
			for _, s := range v.Stmts {
				walk(s)
			}
		case *interp.LocalDecl:
			for _, e := range v.Exprs {
				walk(e)
			}
		case *interp.Assign:
			walk(v.Target)
			walk(v.Value)
		case *interp.IfStmt:
			walk(v.Cond)
			walk(v.Body)
			for _, ei := range v.ElseIfs {
				walk(ei.Cond)
				walk(ei.Body)
			}
			if v.ElseBody != nil {
				walk(v.ElseBody)
			}
		case *interp.ExprStmt:
			walk(v.Expr)
		case *interp.BinOp:
			walk(v.Left)
			walk(v.Right)
		case *interp.UnaryOp:
			walk(v.Expr)
		case *interp.DotAccess:
			// Enum-style: <NS>.<Field> on a bare Ident NS. Only treat
			// known enum namespaces as enum lookups (others may be
			// char-attr style `c.weapon`, handled at compile time by
			// scope-local fallback — NOT a coverage failure).
			if obj, ok := v.Object.(*interp.Ident); ok {
				if isEnumNamespace(obj.Name) {
					qual := obj.Name + "." + v.Field
					if _, ok := engine.LookupEnum(qual); !ok {
						missEnums[qual] = append(missEnums[qual], path+":"+lineStr(v))
					}
				}
			}
			walk(v.Object)
		case *interp.IndexAccess:
			walk(v.Object)
			walk(v.Index)
		case *interp.MethodCall:
			walk(v.Object)
			for _, a := range v.Args {
				walk(a)
			}
		case *interp.Call:
			if id, ok := v.Func.(*interp.Ident); ok {
				if _, ok := engine.LookupBuiltin(id.Name); !ok {
					missBuiltins[id.Name] = append(missBuiltins[id.Name], path+":"+lineStr(v))
				}
			}
			// FuncLit args (defer_fn body) recurse so nested compiles
			// also surface in coverage.
			for _, a := range v.Args {
				walk(a)
			}
		case *interp.TableCtor:
			for _, fld := range v.Fields {
				walk(fld.Value)
			}
		case *interp.FuncLit:
			walk(v.Body)
		}
	}
	walk(n)
}

// isEnumNamespace — true if `name` is a known enum table registered by
// builtins_enums.registerEnums. Hard-coded list because the registration
// loop builds runtime tables, not a static name set. Adding a new enum =
// add an entry here too (caught by C-005-style invariant if you forget).
func isEnumNamespace(name string) bool {
	switch name {
	case "Element", "Scope", "Player", "Op", "Tag", "DiceColor",
		"CostSlot", "Target", "CharKind", "Arkhe", "Source",
		"ActionKind", "Zone", "Weapon", "Slot", "Action", "RefKind":
		return true
	}
	return false
}

// lineStr extracts the AST node line as a string (best-effort fallback "?").
func lineStr(n interp.Node) string {
	if n == nil {
		return "?"
	}
	return itoa(n.GetLine())
}

func itoa(i int) string {
	if i == 0 {
		return "0"
	}
	neg := i < 0
	if neg {
		i = -i
	}
	var buf [20]byte
	p := len(buf)
	for i > 0 {
		p--
		buf[p] = byte('0' + i%10)
		i /= 10
	}
	if neg {
		p--
		buf[p] = '-'
	}
	return string(buf[p:])
}
