// Package factory builds a fully-initialized game instance from a
// JSON-shaped GameConfig. It is imported by the c-shared capi shim
// (gicg_engine/capi/) and by Go-native consumers (gicg_actor/) — both
// drive game lifecycle through the same factory entry point, keeping
// initialization semantics single-sourced.
package factory

// GameConfig is the JSON-shaped game-init payload. Field tags match
// the wire format produced by Python (gicg_env / training cfg) and the
// Go-native actor pool — both call sites unmarshal into this struct.
type GameConfig struct {
	DataDir string `json:"data_dir"`
	// Pools selects which data/pools/<id>/ trees to load cards/chars
	// from. nil / empty defaults to ["v_legacy"] — the placeholder
	// pool ADR-0011 created from the pre-existing data/cards and
	// data/characters trees. Multiple pools union (sibling roots);
	// the rare cross-pool name conflict is resolved last-wins in
	// list order.
	Pools   []string   `json:"pools"`
	Players [2]PConfig `json:"players"`
	Seed    int64      `json:"seed"`
	// CardPool restricts which cards are loaded for this game by their
	// declared name (filename minus ".lua"). nil means "load every card
	// under data/cards"; an explicit empty slice means "load nothing"
	// (no cards declared in the ruleset). When DeckPadding is set, the
	// padding card name is auto-included regardless of CardPool.
	CardPool []string `json:"card_pool"`
	// DeckPadding optionally pads short decks to a fixed length using a
	// named card. nil = no padding (deck length equals eligible-card
	// count). Lifts the previous engine-level "碌碌无为" hardcode out to
	// caller config — see ADR-0011.
	DeckPadding *DeckPaddingJSON `json:"deck_padding,omitempty"`
	// Obs controls per-game obs assembly + shuffle application. When
	// the caller omits the field (pre-obs-config Python callers), Obs is
	// the zero value (all false) — handled by NewGame via
	// NewDefaultObsConfig fallback so legacy behavior is preserved.
	Obs *ObsConfigJSON `json:"obs,omitempty"`
	// MaxRounds caps episode length. 0 (omitempty) keeps legacy
	// unbounded behavior; > 0 force-terminates with Winner=2 after the
	// round-end phase of that round. Used by curriculum Stage 0 to set
	// a deterministic 3-round ceiling.
	MaxRounds int `json:"max_rounds,omitempty"`
	// FixDice, when of length DiceColorCount (8), replaces the random
	// per-round dice roll with these exact per-color counts. Length 0
	// / nil = random roll (default). Curriculum Stage 0 uses this to
	// eliminate dice stochasticity.
	FixDice []int `json:"fix_dice,omitempty"`
}

// DeckPaddingJSON mirrors training cfg's [scenario.deck_padding]:
//
//	deck_padding = { card = "碌碌无为", target_size = 15 }
//
// NewGame translates this into interp.DeckPaddingSpec on the Runtime.
type DeckPaddingJSON struct {
	Card       string `json:"card"`
	TargetSize int    `json:"target_size"`
}

// ObsConfigJSON mirrors the Python ObsConfig TOML schema. Using
// pointer-bool so zero-value = unspecified (→ legacy all-on default),
// distinguished from explicit false in JSON.
type ObsConfigJSON struct {
	IncludeCharSkillRefs *bool `json:"include_char_skill_refs"`
	ShuffleCounters      *bool `json:"shuffle_counters"`
	ShuffleHooks         *bool `json:"shuffle_hooks"`
	ShuffleCards         *bool `json:"shuffle_cards"`
	ShuffleSkillSlots    *bool `json:"shuffle_skill_slots"`
}

type PConfig struct {
	Chars []CharDef `json:"chars"`
}

type CharDef struct {
	Name string `json:"name"`
}
