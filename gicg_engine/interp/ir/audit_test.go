package ir

// DSL audit tool: walks data/pools/**/*.lua, parses each file via the
// existing interp parser, and dumps statistics needed to design the
// IR opcode set + test matrix (IR-1.5 design pass).
//
// Skipped by default. Run with:
//   AUDIT=1 go test ./gicg_engine/interp/ir/ -run TestAudit_DSL -v -count=1
//
// Output: /tmp/dsl_audit_report.txt (overwritten each run).

import (
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"

	"gicg_mono/gicg_engine/interp"
)

func TestAudit_DSL(t *testing.T) {
	if os.Getenv("AUDIT") == "" {
		t.Skip("set AUDIT=1 to run the DSL audit and dump /tmp/dsl_audit_report.txt")
	}

	poolsRoot := "../../../data/pools"
	files, err := findLuaFiles(poolsRoot)
	if err != nil {
		t.Fatalf("find lua: %v", err)
	}
	t.Logf("found %d .lua files under %s", len(files), poolsRoot)

	s := newAuditStats()
	for _, f := range files {
		s.analyzeFile(f)
	}

	out := s.Format()
	if err := os.WriteFile("/tmp/dsl_audit_report.txt", []byte(out), 0644); err != nil {
		t.Fatalf("write report: %v", err)
	}
	t.Logf("report written: /tmp/dsl_audit_report.txt (%d bytes)", len(out))
}

// ---------------------------------------------------------------------------

type auditStats struct {
	totalFiles  int
	parseOK     int
	parseErrors []string

	// hook reg: on_X(function(ctx) ... end) — count per hook name + count of files containing it
	hookCounts map[string]int
	hookFiles  map[string]map[string]struct{} // hook → set of files

	// top-level binding: local X = Y(...) — what Y is called
	bindingCalls map[string]int // declare_counter, declare_card, ...; also non-declare locals tracked

	// Counter scope detected from declare_counter(name, Scope.PerXxx, ...)
	// key: counter local name → scope token (e.g. "PerPlayer")
	counterScopes map[string]string // local_name → scope_str (PerPlayer / PerChar / etc.)

	// Per-hook-body stats
	nodeCounts    map[string]int            // AST node type → count (across all hook bodies)
	methodShapes  map[string]map[int]int    // method_name → (n_args → count)
	methodByScope map[string]map[string]int // method_name → scope_str → count (counter methods only)
	callShapes    map[string]map[int]int    // builtin_func → (n_args → count)
	callHasTable  map[string]int            // builtin_func → count_with_TableCtor_arg
	tableCtorIn   map[string]int            // builtin_func calling with table arg → count
	tableCtorKeys map[string]int            // every TableCtor key seen → count
	unsupNodes    map[string][]string       // node type → list of "file:hook" contexts

	// Hook-body-only AST node counts (separate from top-level scan)
	hookBodyNodeCounts map[string]int
}

func newAuditStats() *auditStats {
	return &auditStats{
		hookCounts:         map[string]int{},
		hookFiles:          map[string]map[string]struct{}{},
		bindingCalls:       map[string]int{},
		counterScopes:      map[string]string{},
		nodeCounts:         map[string]int{},
		methodShapes:       map[string]map[int]int{},
		methodByScope:      map[string]map[string]int{},
		callShapes:         map[string]map[int]int{},
		callHasTable:       map[string]int{},
		tableCtorIn:        map[string]int{},
		tableCtorKeys:      map[string]int{},
		unsupNodes:         map[string][]string{},
		hookBodyNodeCounts: map[string]int{},
	}
}

func (s *auditStats) analyzeFile(path string) {
	s.totalFiles++
	src, err := os.ReadFile(path)
	if err != nil {
		s.parseErrors = append(s.parseErrors, fmt.Sprintf("read %s: %v", path, err))
		return
	}
	toks, err := interp.Tokenize(src)
	if err != nil {
		s.parseErrors = append(s.parseErrors, fmt.Sprintf("tokenize %s: %v", path, err))
		return
	}
	chunk, err := interp.Parse(toks)
	if err != nil {
		s.parseErrors = append(s.parseErrors, fmt.Sprintf("parse %s: %v", path, err))
		return
	}
	s.parseOK++

	// Reset per-file binding scope map (counter scope is per-file context).
	fileCounterScopes := map[string]string{}

	// Top-level: collect bindings from `local X = declare_*(...)` patterns
	// and hook registrations from `on_*(function(ctx) ... end)` calls.
	for _, stmt := range chunk.Stmts {
		s.walkNode(stmt, false, "", "")
		switch st := stmt.(type) {
		case *interp.LocalDecl:
			for i, name := range st.Names {
				if i >= len(st.Exprs) {
					continue
				}
				if call, ok := st.Exprs[i].(*interp.Call); ok {
					if ident, ok := call.Func.(*interp.Ident); ok {
						s.bindingCalls[ident.Name]++
						if ident.Name == "declare_counter" && len(call.Args) >= 2 {
							scope := extractScopeArg(call.Args[1])
							if scope != "" {
								fileCounterScopes[name] = scope
								s.counterScopes[name] = scope
							}
						}
					}
				}
			}
		case *interp.ExprStmt:
			if call, ok := st.Expr.(*interp.Call); ok {
				if ident, ok := call.Func.(*interp.Ident); ok {
					if strings.HasPrefix(ident.Name, "on_") {
						s.hookCounts[ident.Name]++
						if s.hookFiles[ident.Name] == nil {
							s.hookFiles[ident.Name] = map[string]struct{}{}
						}
						s.hookFiles[ident.Name][path] = struct{}{}
						// Walk hook body separately tagged.
						if len(call.Args) > 0 {
							if fl, ok := call.Args[len(call.Args)-1].(*interp.FuncLit); ok {
								s.walkHookBody(fl.Body, fileCounterScopes, path, ident.Name)
							}
						}
					}
				}
			}
		}
	}
}

func (s *auditStats) walkHookBody(ch *interp.Chunk, scopes map[string]string, file, hook string) {
	for _, stmt := range ch.Stmts {
		s.walkNode(stmt, true, file, hook)
	}
	// Detect method calls on declared counter idents → record scope.
	collectMethodCalls(ch, func(mc *interp.MethodCall) {
		ident, ok := mc.Object.(*interp.Ident)
		if !ok {
			return
		}
		scope := scopes[ident.Name]
		if scope == "" {
			scope = "Unknown"
		}
		if s.methodByScope[mc.Method] == nil {
			s.methodByScope[mc.Method] = map[string]int{}
		}
		s.methodByScope[mc.Method][scope]++
	})
}

func (s *auditStats) walkNode(n interp.Node, inHookBody bool, file, hook string) {
	if n == nil {
		return
	}
	tn := typeName(n)
	s.nodeCounts[tn]++
	if inHookBody {
		s.hookBodyNodeCounts[tn]++
	}
	switch v := n.(type) {
	case *interp.Chunk:
		for _, s2 := range v.Stmts {
			s.walkNode(s2, inHookBody, file, hook)
		}
	case *interp.LocalDecl:
		for _, e := range v.Exprs {
			s.walkNode(e, inHookBody, file, hook)
		}
	case *interp.Assign:
		s.walkNode(v.Target, inHookBody, file, hook)
		s.walkNode(v.Value, inHookBody, file, hook)
	case *interp.IfStmt:
		s.walkNode(v.Cond, inHookBody, file, hook)
		s.walkNode(v.Body, inHookBody, file, hook)
		for _, ei := range v.ElseIfs {
			s.walkNode(ei.Cond, inHookBody, file, hook)
			s.walkNode(ei.Body, inHookBody, file, hook)
		}
		if v.ElseBody != nil {
			s.walkNode(v.ElseBody, inHookBody, file, hook)
		}
	case *interp.ExprStmt:
		s.walkNode(v.Expr, inHookBody, file, hook)
	case *interp.BinOp:
		s.walkNode(v.Left, inHookBody, file, hook)
		s.walkNode(v.Right, inHookBody, file, hook)
	case *interp.UnaryOp:
		s.walkNode(v.Expr, inHookBody, file, hook)
	case *interp.DotAccess:
		s.walkNode(v.Object, inHookBody, file, hook)
	case *interp.IndexAccess:
		s.walkNode(v.Object, inHookBody, file, hook)
		s.walkNode(v.Index, inHookBody, file, hook)
		if inHookBody {
			s.unsupNodes["IndexAccess"] = appendCtx(s.unsupNodes["IndexAccess"], file, hook)
		}
	case *interp.MethodCall:
		s.walkNode(v.Object, inHookBody, file, hook)
		for _, a := range v.Args {
			s.walkNode(a, inHookBody, file, hook)
		}
		if inHookBody {
			if s.methodShapes[v.Method] == nil {
				s.methodShapes[v.Method] = map[int]int{}
			}
			s.methodShapes[v.Method][len(v.Args)]++
		}
	case *interp.Call:
		s.walkNode(v.Func, inHookBody, file, hook)
		funcName := ""
		if id, ok := v.Func.(*interp.Ident); ok {
			funcName = id.Name
		}
		hasTable := false
		for _, a := range v.Args {
			s.walkNode(a, inHookBody, file, hook)
			if _, ok := a.(*interp.TableCtor); ok {
				hasTable = true
			}
		}
		if inHookBody && funcName != "" {
			if s.callShapes[funcName] == nil {
				s.callShapes[funcName] = map[int]int{}
			}
			s.callShapes[funcName][len(v.Args)]++
			if hasTable {
				s.callHasTable[funcName]++
				s.tableCtorIn[funcName]++
			}
		}
	case *interp.TableCtor:
		for _, f := range v.Fields {
			s.tableCtorKeys[f.Key]++
			s.walkNode(f.Value, inHookBody, file, hook)
		}
	case *interp.FuncLit:
		s.walkNode(v.Body, inHookBody, file, hook)
		if inHookBody {
			s.unsupNodes["FuncLit"] = appendCtx(s.unsupNodes["FuncLit"], file, hook)
		}
	}
}

func (s *auditStats) Format() string {
	var b strings.Builder
	fmt.Fprintf(&b, "=== DSL audit (IR-1.5 design pass) ===\n\n")
	fmt.Fprintf(&b, "Files scanned: %d   parsed ok: %d   parse errors: %d\n", s.totalFiles, s.parseOK, len(s.parseErrors))
	if len(s.parseErrors) > 0 {
		fmt.Fprintf(&b, "\nParse errors (first 10):\n")
		for i, e := range s.parseErrors {
			if i >= 10 {
				fmt.Fprintf(&b, "  ... +%d more\n", len(s.parseErrors)-10)
				break
			}
			fmt.Fprintf(&b, "  - %s\n", e)
		}
	}

	fmt.Fprintf(&b, "\n--- Hook registrations (%d distinct) ---\n", len(s.hookCounts))
	for _, kv := range sortedByValueDesc(s.hookCounts) {
		fmt.Fprintf(&b, "  %-32s %5d calls in %d files\n", kv.k, kv.v, len(s.hookFiles[kv.k]))
	}

	fmt.Fprintf(&b, "\n--- Top-level binding sources (%d distinct func names) ---\n", len(s.bindingCalls))
	for _, kv := range sortedByValueDesc(s.bindingCalls) {
		fmt.Fprintf(&b, "  %-32s %5d\n", kv.k, kv.v)
	}

	fmt.Fprintf(&b, "\n--- Counter scope distribution (from declare_counter Scope arg) ---\n")
	scopeBucket := map[string]int{}
	for _, sc := range s.counterScopes {
		scopeBucket[sc]++
	}
	for _, kv := range sortedByValueDesc(scopeBucket) {
		fmt.Fprintf(&b, "  %-32s %5d distinct counter names\n", kv.k, kv.v)
	}

	fmt.Fprintf(&b, "\n--- Hook-body AST node frequencies ---\n")
	for _, kv := range sortedByValueDesc(s.hookBodyNodeCounts) {
		fmt.Fprintf(&b, "  %-32s %5d\n", kv.k, kv.v)
	}

	fmt.Fprintf(&b, "\n--- Method call shapes (method → n_args distribution) ---\n")
	methods := sortedKeys(s.methodShapes)
	for _, m := range methods {
		fmt.Fprintf(&b, "  :%s  ", m)
		shapeKeys := sortedIntKeys(s.methodShapes[m])
		for _, k := range shapeKeys {
			fmt.Fprintf(&b, "%d-arg=%d  ", k, s.methodShapes[m][k])
		}
		// Add scope breakdown if available.
		if sb := s.methodByScope[m]; len(sb) > 0 {
			fmt.Fprintf(&b, "  [by scope: ")
			for _, kv := range sortedByValueDesc(sb) {
				fmt.Fprintf(&b, "%s=%d ", kv.k, kv.v)
			}
			fmt.Fprintf(&b, "]")
		}
		fmt.Fprintf(&b, "\n")
	}

	fmt.Fprintf(&b, "\n--- Builtin call shapes (func → n_args distribution; * = ever uses TableCtor arg) ---\n")
	calls := sortedKeys(s.callShapes)
	for _, c := range calls {
		marker := ""
		if s.callHasTable[c] > 0 {
			marker = "* "
		}
		fmt.Fprintf(&b, "  %s%-32s  ", marker, c)
		shapeKeys := sortedIntKeys(s.callShapes[c])
		for _, k := range shapeKeys {
			fmt.Fprintf(&b, "%d-arg=%d  ", k, s.callShapes[c][k])
		}
		if s.callHasTable[c] > 0 {
			fmt.Fprintf(&b, "  [table-arg in %d calls]", s.callHasTable[c])
		}
		fmt.Fprintf(&b, "\n")
	}

	fmt.Fprintf(&b, "\n--- TableCtor usage: caller funcs ---\n")
	for _, kv := range sortedByValueDesc(s.tableCtorIn) {
		fmt.Fprintf(&b, "  %s: %d calls\n", kv.k, kv.v)
	}
	fmt.Fprintf(&b, "\n--- TableCtor keys observed (top 30 by freq) ---\n")
	keys := sortedByValueDesc(s.tableCtorKeys)
	for i, kv := range keys {
		if i >= 30 {
			break
		}
		fmt.Fprintf(&b, "  %s: %d occurrences\n", kv.k, kv.v)
	}

	fmt.Fprintf(&b, "\n--- Unsupported AST nodes appearing in hook bodies ---\n")
	if len(s.unsupNodes) == 0 {
		fmt.Fprintf(&b, "  (none)\n")
	}
	for tn, ctxs := range s.unsupNodes {
		fmt.Fprintf(&b, "  %s: %d uses\n", tn, len(ctxs))
		uniq := map[string]int{}
		for _, c := range ctxs {
			uniq[c]++
		}
		i := 0
		for c, n := range uniq {
			if i >= 8 {
				fmt.Fprintf(&b, "    ... +%d more contexts\n", len(uniq)-i)
				break
			}
			fmt.Fprintf(&b, "    - %s (×%d)\n", c, n)
			i++
		}
	}

	return b.String()
}

// ---------- helpers ----------

func findLuaFiles(root string) ([]string, error) {
	var out []string
	err := filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !d.IsDir() && strings.HasSuffix(path, ".lua") {
			out = append(out, path)
		}
		return nil
	})
	sort.Strings(out)
	return out, err
}

func typeName(n any) string {
	t := reflect.TypeOf(n)
	if t.Kind() == reflect.Pointer {
		t = t.Elem()
	}
	return t.Name()
}

func extractScopeArg(n interp.Node) string {
	d, ok := n.(*interp.DotAccess)
	if !ok {
		return ""
	}
	obj, ok := d.Object.(*interp.Ident)
	if !ok || obj.Name != "Scope" {
		return ""
	}
	return d.Field
}

// collectMethodCalls walks all stmts in a chunk and calls f for every MethodCall.
func collectMethodCalls(ch *interp.Chunk, f func(*interp.MethodCall)) {
	var walk func(n interp.Node)
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
			walk(v.Object)
		case *interp.IndexAccess:
			walk(v.Object)
			walk(v.Index)
		case *interp.MethodCall:
			f(v)
			walk(v.Object)
			for _, a := range v.Args {
				walk(a)
			}
		case *interp.Call:
			walk(v.Func)
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
	walk(ch)
}

func appendCtx(s []string, file, hook string) []string {
	return append(s, fmt.Sprintf("%s::%s", filepath.Base(file), hook))
}
