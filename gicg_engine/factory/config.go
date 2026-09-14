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
	// from. nil / empty defaults to ["v_legacy"]. Multiple pools union
	// sibling roots;
	// the rare cross-pool name conflict is resolved last-wins in
	// list order.
	Pools   []string   `json:"pools"`
	Players [2]PConfig `json:"players"`
	Seed    int64      `json:"seed"`
	// CardPool restricts which cards are loaded for this game by their
	// declared name. nil means "load every card in the selected pools";
	// an explicit empty slice means "load nothing"
	// (no cards declared in the ruleset). When DeckPadding is set, the
	// padding card name is auto-included regardless of CardPool.
	CardPool []string `json:"card_pool"`
	// DeckPadding optionally pads short decks to a fixed length using a
	// named card. nil = no padding (deck length equals eligible-card
	// count).
	DeckPadding *DeckPaddingJSON `json:"deck_padding,omitempty"`
	// Obs controls per-game obs assembly + shuffle application. When
	// the caller omits the field (pre-obs-config Python callers), Obs is
	// the zero value (all false) — handled by NewGame via
	// NewDefaultObsConfig fallback so legacy behavior is preserved.
	Obs *ObsConfigJSON `json:"obs,omitempty"`
	// MaxRounds adds an episode-length cap. 0 disables this additional
	// cap; > 0 force-terminates with Winner=2 after that round's end phase.
	MaxRounds int `json:"max_rounds,omitempty"`
	// FixDice, when of length DiceColorCount (8), replaces the random
	// per-round dice roll with these exact per-color counts. Length 0
	// / nil = random roll (default).
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
	// Deck pins this player's deck to an explicit card-name list
	// matching training cfg [scenario].deck_0/deck_1. It is a multiset;
	// duplicates allowed). nil = implicit path: deck is the full set of
	// declared cards eligible for this player, padded per DeckPadding.
	// Every name must already be declared in the ruleset (card_pool /
	// pool) — Deck never extends the loaded card set, so the obs card
	// vocabulary stays controlled by CardPool alone.
	Deck []string `json:"deck"`
}

type CharDef struct {
	Name string `json:"name"`
}
