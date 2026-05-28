package dsl

import (
	"os"
	"path/filepath"
	"regexp"
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
	"invoke_skill_silent": true,
	"set_preparing":       true, "get_preparing": true, "clear_preparing": true,
	"add_dice": true,
	// card
	"declare_card": true, "get_card": true, "add_card": true,
	// damage/heal
	"deal_damage": true, "heal": true,
	// action
	"defer_fn": true, "get_active_char": true, "set_active_char": true,
	"get_next_char": true, "context_player": true, "force_switch": true,
	"draw_card": true, "has_card_in_own_hand": true,
	"roll_dice": true, "clear_dice_pool": true, "get_dice_count": true,
	// cost modification API
	"cost_mod": true, "cost_total": true, "was_applied": true,
	// hooks
	"on_damage_boost": true, "on_reaction_damage": true,
	"on_damage_reduce": true, "on_after_damage": true,
	"on_action_check": true, "on_action_prepare": true,
	"on_skill_use": true, "on_card_play": true,
	"on_switch": true, "on_before_turn_flip": true,
	"on_round_start": true, "on_round_end": true,
	"on_round_end_post_summon": true, "on_round_end_decay": true,
	"on_round_end_final": true,
	"on_death":           true, "on_revive": true,
	"on_before_write": true, "on_after_write": true,
	"on_before_heal": true, "on_after_heal": true,
	"on_shield_absorb": true,
	// Damage pipeline hooks — builtins_hook.go:142-146 注册。
	"on_damage_type": true, "on_damage_add": true,
	"on_damage_mul":         true,
	"on_damage_reduce_buff": true,
	// Support zone API — builtins_support.go。
	"remove_support": true,
	"gain_energy":    true, "consume_energy": true,
	"on_before_energy_gain": true, "on_after_energy_gain": true,
	"on_before_energy_consume": true, "on_after_energy_consume": true,
	// misc
	"cancel": true, "min": true, "max": true, "pcall": true,
	// system-level (used in system/ DSL files)
	"set_winner": true, "get_turn": true,
	"build_deck": true, "deal_initial_hand": true,
	// ADR-0019 §B.3 — DSL declare_reaction("X") registry + set_reaction_kind(R_X)
	// 写 PendingReactionKind。 builtin 实装在 interp/builtins.go:80-100,system/
	// reactions/*.lua 使用。 audit whitelist 之前漏列。
	"declare_reaction": true, "set_reaction_kind": true,
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
