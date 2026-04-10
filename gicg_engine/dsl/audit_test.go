package dsl

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
)

var dataDir = filepath.Join("..", "..", "data")

var forbidden = []struct {
	pattern *regexp.Regexp
	name    string
}{
	{regexp.MustCompile(`\bfor\b`), "for loop"},
	{regexp.MustCompile(`\bwhile\b`), "while loop"},
	{regexp.MustCompile(`\brepeat\b`), "repeat loop"},
	{regexp.MustCompile(`\bpairs\s*\(`), "pairs()"},
	{regexp.MustCompile(`\bipairs\s*\(`), "ipairs()"},
	{regexp.MustCompile(`\bmath\.\w+`), "math.*"},
	{regexp.MustCompile(`\bsetmetatable\s*\(`), "setmetatable()"},
	{regexp.MustCompile(`\brawset\s*\(`), "rawset()"},
	{regexp.MustCompile(`\bstring\.\w+`), "string.*"},
	{regexp.MustCompile(`\btable\.\w+`), "table.*"},
	{regexp.MustCompile(`\bio\.\w+`), "io.*"},
	{regexp.MustCompile(`\b_current_owner_player\b`), "_current_owner_player"},
	{regexp.MustCompile(`\bon_before_damage\s*\(`), "on_before_damage (use on_damage_boost)"},
}

// Allowed global function calls (whitelist)
var allowedFunctions = map[string]bool{
	// counter
	"declare_counter": true, "get_counter": true,
	"get_counter_group": true, "register_on_tag_write": true,
	// char
	"declare_char": true, "bind_char": true, "get_char": true,
	// skill
	"declare_skill": true, "get_skill": true, "invoke_skill": true,
	// card
	"declare_card": true, "get_card": true, "add_card": true,
	// damage/heal
	"deal_damage": true, "heal": true,
	// action
	"defer_fn": true, "get_active_char": true, "set_active_char": true,
	"get_next_char": true, "context_player": true, "force_switch_next": true,
	// register helpers
	"register_on_all_hp": true, "register_on_all_energy": true,
	// hooks
	"on_damage_boost": true, "on_reaction_damage": true,
	"on_damage_reduce": true, "on_after_damage": true,
	"on_action_check": true, "on_action_prepare": true,
	"on_skill_use": true, "on_card_play": true,
	"on_switch": true, "on_before_turn_flip": true,
	"on_round_start": true, "on_round_end": true,
	"on_round_end_post_summon": true, "on_round_end_decay": true,
	"on_round_end_final": true,
	"on_before_write": true, "on_after_write": true,
	"on_before_heal": true, "on_after_heal": true,
	"gain_energy": true, "consume_energy": true,
	"on_before_energy_gain": true, "on_after_energy_gain": true,
	"on_before_energy_consume": true, "on_after_energy_consume": true,
	// misc
	"cancel": true, "min": true, "max": true, "pcall": true,
	// system-level (used in system/ DSL files)
	"set_winner": true, "count_alive": true,
	"draw_card_self": true, "get_turn": true,
}

// Receiver types
const (
	typeUnknown = iota
	typeCounter
	typeCharProxy
	typeGroupProxy
	typeInt // skill_id, card_ref
)

// Methods allowed per receiver type
var methodsByType = map[int]map[string]bool{
	typeCounter: {
		"get": true, "set": true, "add": true, "sub": true,
		"cmin": true, "cmax": true,
		"get_at": true, "set_at": true, "add_at": true, "sub_at": true,
		"decay_all": true, "fill_all": true,
	},
	typeCharProxy: {
		"hp": true, "energy": true, "alive": true, "name": true,
		"element": true, "weapon": true,
		"owner_player": true, "owner_char": true,
	},
	typeGroupProxy: {
		"get": true, "set": true, "add": true, "sub": true,
		"get_at": true, "set_at": true, "add_at": true, "sub_at": true,
	},
}

// All allowed methods (union)
var allAllowedMethods map[string]bool

func init() {
	allAllowedMethods = map[string]bool{}
	for _, methods := range methodsByType {
		for m := range methods {
			allAllowedMethods[m] = true
		}
	}
}

// Type inference from assignments
var typePatterns = []struct {
	pattern *regexp.Regexp
	typ     int
}{
	{regexp.MustCompile(`=\s*declare_counter\(`), typeCounter},
	{regexp.MustCompile(`=\s*get_counter\(`), typeCounter},
	{regexp.MustCompile(`=\s*get_char\(`), typeCharProxy},
	{regexp.MustCompile(`=\s*declare_char\(`), typeCharProxy},
	{regexp.MustCompile(`=\s*get_counter_group\(`), typeGroupProxy},
	{regexp.MustCompile(`=\s*declare_skill\(`), typeInt},
	{regexp.MustCompile(`=\s*get_skill\(`), typeInt},
	{regexp.MustCompile(`=\s*declare_card\(`), typeInt},
	{regexp.MustCompile(`=\s*get_card\(`), typeInt},
}

// Infer type of a variable returned by a method call
var methodReturnType = map[string]int{
	"hp":     typeCounter,
	"energy": typeCounter,
}

func collectLuaFiles(t *testing.T) []string {
	t.Helper()
	var files []string
	err := filepath.Walk(dataDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && strings.HasSuffix(path, ".lua") {
			files = append(files, path)
		}
		return nil
	})
	if err != nil {
		t.Fatalf("walk data dir: %v", err)
	}
	return files
}

func TestDSL_NoForbiddenConstructs(t *testing.T) {
	files := collectLuaFiles(t)
	for _, path := range files {
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read %s: %v", path, err)
		}
		rel, _ := filepath.Rel(dataDir, path)
		lines := strings.Split(string(data), "\n")

		for _, f := range forbidden {
			for i, line := range lines {
				trimmed := strings.TrimSpace(line)
				if strings.HasPrefix(trimmed, "--") {
					continue
				}
				if f.pattern.MatchString(line) {
					t.Errorf("%s:%d: forbidden: %s", rel, i+1, f.name)
				}
			}
		}
	}
}

func TestDSL_NoUnknownCalls(t *testing.T) {
	files := collectLuaFiles(t)

	funcCallRe := regexp.MustCompile(`(?:^|[^:])(\b[a-zA-Z_]\w*)\s*\(`)
	luaKeywords := map[string]bool{
		"function": true, "if": true, "elseif": true, "end": true,
		"local": true, "return": true, "then": true, "not": true,
		"and": true, "or": true, "true": true, "false": true, "nil": true,
	}

	for _, path := range files {
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read %s: %v", path, err)
		}
		rel, _ := filepath.Rel(dataDir, path)
		lines := strings.Split(string(data), "\n")

		for i, line := range lines {
			trimmed := strings.TrimSpace(line)
			if strings.HasPrefix(trimmed, "--") {
				continue
			}
			for _, m := range funcCallRe.FindAllStringSubmatch(line, -1) {
				name := m[1]
				if luaKeywords[name] || allowedFunctions[name] {
					continue
				}
				t.Errorf("%s:%d: unknown function call: %s", rel, i+1, name)
			}
		}
	}
}

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
