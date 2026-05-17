package dsl

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
)

func TestDSL_MethodTypeCheck(t *testing.T) {
	files := collectLuaFiles(t)

	assignRe := regexp.MustCompile(`local\s+(\S+)\s*=`)
	methodCallRe := regexp.MustCompile(`(\w+):(\w+)\(`)
	methodReturnRe := regexp.MustCompile(`local\s+(\S+)\s*=\s*(\w+):(\w+)\(`)

	for _, path := range files {
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read %s: %v", path, err)
		}
		rel, _ := filepath.Rel(dataDir, path)
		src := string(data)
		lines := strings.Split(src, "\n")

		// Build variable type map for this file
		varTypes := map[string]int{}

		for _, line := range lines {
			trimmed := strings.TrimSpace(line)
			if strings.HasPrefix(trimmed, "--") {
				continue
			}

			// Check direct assignments: local X = declare_counter(...)
			if m := assignRe.FindStringSubmatch(line); m != nil {
				varName := m[1]
				for _, tp := range typePatterns {
					if tp.pattern.MatchString(line) {
						varTypes[varName] = tp.typ
						break
					}
				}
			}

			// Check method return: local X = Y:hp()
			if m := methodReturnRe.FindStringSubmatch(line); m != nil {
				varName := m[1]
				method := m[3]
				if retType, ok := methodReturnType[method]; ok {
					varTypes[varName] = retType
				}
			}
		}

		// Check method calls against inferred types
		for i, line := range lines {
			trimmed := strings.TrimSpace(line)
			if strings.HasPrefix(trimmed, "--") {
				continue
			}

			for _, m := range methodCallRe.FindAllStringSubmatch(line, -1) {
				receiver := m[1]
				method := m[2]

				// Skip if method is universally unknown
				if !allAllowedMethods[method] {
					t.Errorf("%s:%d: unknown method :%s() on %s", rel, i+1, method, receiver)
					continue
				}

				// Type check if we know the receiver type
				recvType, known := varTypes[receiver]
				if !known {
					continue // can't infer, skip
				}

				allowedForType := methodsByType[recvType]
				if allowedForType != nil && !allowedForType[method] {
					typeName := []string{"unknown", "counter", "char_proxy", "group_proxy", "int"}[recvType]
					t.Errorf("%s:%d: method :%s() not valid on %s (type: %s)", rel, i+1, method, receiver, typeName)
				}

				// int type (skill_id, card_ref) should have no method calls
				if recvType == typeInt {
					t.Errorf("%s:%d: method :%s() called on %s (type: int, no methods expected)", rel, i+1, method, receiver)
				}
			}
		}
	}
}

func TestDSL_TokenFrequency(t *testing.T) {
	files := collectLuaFiles(t)

	apiCounts := map[string]int{}
	enumCounts := map[string]int{}
	ctxCounts := map[string]int{}
	methodCounts := map[string]int{}

	apiRe := map[string]*regexp.Regexp{}
	for api := range allowedFunctions {
		apiRe[api] = regexp.MustCompile(`\b` + regexp.QuoteMeta(api) + `\s*\(`)
	}
	enumRe := regexp.MustCompile(`\b(Element|Tag|Player|Zone|Scope|Op|Source|Target|Weapon|ActionKind|Action|Filter)\.(\w+)`)
	ctxRe := regexp.MustCompile(`ctx\.(\w+)`)
	methodRe := regexp.MustCompile(`:(\w+)\(`)

	for _, path := range files {
		data, _ := os.ReadFile(path)
		src := string(data)

		for api, re := range apiRe {
			if cnt := len(re.FindAllString(src, -1)); cnt > 0 {
				apiCounts[api] += cnt
			}
		}
		for _, m := range enumRe.FindAllStringSubmatch(src, -1) {
			enumCounts[m[1]+"."+m[2]]++
		}
		for _, m := range ctxRe.FindAllStringSubmatch(src, -1) {
			ctxCounts["ctx."+m[1]]++
		}
		for _, m := range methodRe.FindAllStringSubmatch(src, -1) {
			methodCounts[":"+m[1]+"()"]++
		}
	}

	t.Logf("=== %d DSL files ===", len(files))
	t.Logf("\n--- API Calls (%d unique) ---", len(apiCounts))
	for _, kv := range sortedCounts(apiCounts) {
		t.Logf("  %3d  %s", kv.count, kv.name)
	}
	t.Logf("\n--- Enum Access (%d unique) ---", len(enumCounts))
	for _, kv := range sortedCounts(enumCounts) {
		t.Logf("  %3d  %s", kv.count, kv.name)
	}
	t.Logf("\n--- ctx Fields (%d unique) ---", len(ctxCounts))
	for _, kv := range sortedCounts(ctxCounts) {
		t.Logf("  %3d  %s", kv.count, kv.name)
	}
	t.Logf("\n--- Method Calls (%d unique) ---", len(methodCounts))
	for _, kv := range sortedCounts(methodCounts) {
		t.Logf("  %3d  %s", kv.count, kv.name)
	}
}

type kv struct {
	name  string
	count int
}

func sortedCounts(m map[string]int) []kv {
	out := make([]kv, 0, len(m))
	for k, v := range m {
		out = append(out, kv{k, v})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].count > out[j].count })
	return out
}
