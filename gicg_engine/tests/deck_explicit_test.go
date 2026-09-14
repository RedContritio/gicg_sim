package tests

// F4 deck construction contract tests — fail-loud implicit overflow,
// explicit per-player deck declaration (GameConfig.Players[i].Deck),
// padding interaction, and the no-padding regression path. These run
// through factory.NewGame so they exercise the same path production
// (capi GameNew / gicg_actor) uses.

import (
	"strings"
	"testing"

	"gicg_mono/gicg_engine/factory"
)

// deckCfg builds a 赤蝶 vs 墨客 v_legacy GameConfig with the given
// card pool. Padding / explicit decks are set by each test.
func deckCfg(cardPool []string) factory.GameConfig {
	cfg := factory.GameConfig{
		DataDir:  dataDir,
		Pools:    []string{"v_legacy"},
		Seed:     42,
		CardPool: cardPool,
	}
	cfg.Players[0].Chars = []factory.CharDef{{Name: "赤蝶"}}
	cfg.Players[1].Chars = []factory.CharDef{{Name: "墨客"}}
	return cfg
}

// initDeckNames returns player pi's InitDeck as a name multiset.
func initDeckNames(h *factory.GameHandle, pi int) map[string]int {
	refNames := map[int]string{}
	for name, card := range h.RT.Cards.ByName {
		refNames[card.Ref] = name
	}
	out := map[string]int{}
	for _, inst := range h.Game.Players[pi].InitDeck {
		out[refNames[inst.Ref]]++
	}
	return out
}

func wantErrContaining(t *testing.T, err error, subs ...string) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected NewGame error containing %v, got nil", subs)
	}
	for _, s := range subs {
		if !strings.Contains(err.Error(), s) {
			t.Fatalf("error %q does not contain %q", err.Error(), s)
		}
	}
}

func TestDeck_ImplicitOverflowErrors(t *testing.T) {
	// 4 requirement-free cards, target 3 → pre-F4 this silently kept the
	// byte-order head [佛跳墙 占星 反制] and dropped 玄冰. Now: error
	// naming the dropped card and pointing at [scenario].deck_0.
	cfg := deckCfg([]string{"佛跳墙", "占星", "反制", "玄冰"})
	cfg.DeckPadding = &factory.DeckPaddingJSON{Card: "碌碌无为", TargetSize: 3}
	_, err := factory.NewGame(cfg)
	wantErrContaining(t, err, "玄冰", "deck_0", "exceed deck_padding.target_size=3")
}

func TestDeck_ExplicitHappyPath_MultisetAndPaddingFill(t *testing.T) {
	cfg := deckCfg([]string{"佛跳墙", "占星", "玄冰"})
	cfg.DeckPadding = &factory.DeckPaddingJSON{Card: "碌碌无为", TargetSize: 5}
	cfg.Players[0].Deck = []string{"佛跳墙", "佛跳墙", "玄冰"} // multiset: duplicates allowed
	cfg.Players[1].Deck = []string{"占星"}
	h, err := factory.NewGame(cfg)
	if err != nil {
		t.Fatalf("NewGame: %v", err)
	}
	got0 := initDeckNames(h, 0)
	want0 := map[string]int{"佛跳墙": 2, "玄冰": 1, "碌碌无为": 2}
	for n, c := range want0 {
		if got0[n] != c {
			t.Errorf("P0 deck[%s] = %d, want %d (full: %v)", n, got0[n], c, got0)
		}
	}
	if len(h.Game.Players[0].InitDeck) != 5 {
		t.Errorf("P0 InitDeck len = %d, want 5", len(h.Game.Players[0].InitDeck))
	}
	got1 := initDeckNames(h, 1)
	if got1["占星"] != 1 || got1["碌碌无为"] != 4 || len(h.Game.Players[1].InitDeck) != 5 {
		t.Errorf("P1 deck = %v, want 占星×1 + 碌碌无为×4", got1)
	}
}

func TestDeck_ExplicitUnknownCardErrors(t *testing.T) {
	cfg := deckCfg([]string{"佛跳墙"})
	cfg.DeckPadding = &factory.DeckPaddingJSON{Card: "碌碌无为", TargetSize: 5}
	cfg.Players[0].Deck = []string{"佛跳墙", "不存在的卡"}
	_, err := factory.NewGame(cfg)
	wantErrContaining(t, err, "不存在的卡", "not declared")
}

func TestDeck_ExplicitIneligibleCardErrors(t *testing.T) {
	// 铁弓 is a bow weapon — neither 赤蝶 (polearm) nor 墨客 (sword)
	// can equip it, so it fails CardEligibleFor on P0.
	cfg := deckCfg([]string{"铁弓"})
	cfg.DeckPadding = &factory.DeckPaddingJSON{Card: "碌碌无为", TargetSize: 5}
	cfg.Players[0].Deck = []string{"铁弓"}
	_, err := factory.NewGame(cfg)
	wantErrContaining(t, err, "铁弓", "eligibility")
}

func TestDeck_ExplicitTalentCardWrongCharErrors(t *testing.T) {
	// 蝶鳞 requires_char 赤蝶 — declaring it in 墨客's (P1) deck errors.
	cfg := deckCfg([]string{"蝶鳞"})
	cfg.DeckPadding = &factory.DeckPaddingJSON{Card: "碌碌无为", TargetSize: 5}
	cfg.Players[1].Deck = []string{"蝶鳞"}
	_, err := factory.NewGame(cfg)
	wantErrContaining(t, err, "蝶鳞", "eligibility")
}

func TestDeck_ExplicitEmptyErrors(t *testing.T) {
	// Empty non-nil deck = unexpected input — must error, not silently
	// build an all-filler deck. Python new_game rejects it client-side;
	// this locks the Go side for direct factory / game_spec callers.
	cfg := deckCfg([]string{"佛跳墙"})
	cfg.DeckPadding = &factory.DeckPaddingJSON{Card: "碌碌无为", TargetSize: 5}
	cfg.Players[0].Deck = []string{}
	_, err := factory.NewGame(cfg)
	wantErrContaining(t, err, "deck player 0", "empty")
}

func TestDeck_ExplicitOverflowErrors(t *testing.T) {
	cfg := deckCfg([]string{"佛跳墙", "占星", "反制", "玄冰"})
	cfg.DeckPadding = &factory.DeckPaddingJSON{Card: "碌碌无为", TargetSize: 3}
	cfg.Players[0].Deck = []string{"佛跳墙", "占星", "反制", "玄冰"}
	_, err := factory.NewGame(cfg)
	wantErrContaining(t, err, "explicit deck has 4 cards", "target_size=3")
}

func TestDeck_PaddingCardMissingErrors(t *testing.T) {
	// 1 eligible card < target 5 needs padding, but the padding card
	// does not exist in the pool → pre-F4 this silently produced a
	// 1-card deck; now it errors.
	cfg := deckCfg([]string{"佛跳墙"})
	cfg.DeckPadding = &factory.DeckPaddingJSON{Card: "没有这张卡", TargetSize: 5}
	_, err := factory.NewGame(cfg)
	wantErrContaining(t, err, "没有这张卡", "padding card")
}

func TestDeck_NoPaddingNoExplicit_FullEligibleSet(t *testing.T) {
	// Regression: DeckPadding nil → deck = full eligible set, any size.
	cfg := deckCfg([]string{"佛跳墙", "占星", "玄冰"})
	h, err := factory.NewGame(cfg)
	if err != nil {
		t.Fatalf("NewGame: %v", err)
	}
	for pi := 0; pi < 2; pi++ {
		if n := len(h.Game.Players[pi].InitDeck); n != 3 {
			t.Errorf("P%d InitDeck len = %d, want 3 (full eligible set)", pi, n)
		}
	}
}

func TestDeck_ExplicitNoPadding_UsedAsIs(t *testing.T) {
	cfg := deckCfg([]string{"佛跳墙", "占星"})
	cfg.Players[0].Deck = []string{"佛跳墙", "佛跳墙"}
	h, err := factory.NewGame(cfg)
	if err != nil {
		t.Fatalf("NewGame: %v", err)
	}
	got := initDeckNames(h, 0)
	if got["佛跳墙"] != 2 || len(h.Game.Players[0].InitDeck) != 2 {
		t.Errorf("P0 deck = %v, want 佛跳墙×2 exactly", got)
	}
	// P1 has no explicit deck and no padding → full eligible set (2).
	if n := len(h.Game.Players[1].InitDeck); n != 2 {
		t.Errorf("P1 InitDeck len = %d, want 2", n)
	}
}

func TestDeck_ResetRebuildsExplicitDeck(t *testing.T) {
	cfg := deckCfg([]string{"佛跳墙", "占星", "玄冰"})
	cfg.DeckPadding = &factory.DeckPaddingJSON{Card: "碌碌无为", TargetSize: 5}
	cfg.Players[0].Deck = []string{"佛跳墙", "玄冰", "玄冰"}
	h, err := factory.NewGame(cfg)
	if err != nil {
		t.Fatalf("NewGame: %v", err)
	}
	before := initDeckNames(h, 0)
	h.RT.ResetDynamic(7)
	after := initDeckNames(h, 0)
	for n, c := range before {
		if after[n] != c {
			t.Errorf("post-reset deck[%s] = %d, want %d", n, after[n], c)
		}
	}
	if len(h.Game.Players[0].InitDeck) != 5 {
		t.Errorf("post-reset P0 InitDeck len = %d, want 5", len(h.Game.Players[0].InitDeck))
	}
}
