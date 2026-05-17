package main

/*
#include <stdlib.h>
#include <string.h>
*/
import "C"

import (
	"encoding/json"
	"fmt"
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

// GameHandle holds a game instance with its interpreter runtime.
type GameHandle struct {
	Game *engine.Game
	RT   *interp.Runtime
	// SuspendedLog holds g.Log while ``GameLogSuspend`` has detached it
	// from the live game (nil when logging is active). See the
	// suspend/resume API for the MCTS-rollout use case.
	SuspendedLog *engine.EventLog
}

var (
	handleMu sync.Mutex
	handles  = map[int]*GameHandle{}
	nextID   = 1

	snapMu     sync.Mutex
	snapshots  = map[int]*engine.Game{}
	nextSnapID = 1
)

func storeHandle(h *GameHandle) int {
	handleMu.Lock()
	defer handleMu.Unlock()
	id := nextID
	nextID++
	handles[id] = h
	return id
}

func getHandle(id int) *GameHandle {
	handleMu.Lock()
	defer handleMu.Unlock()
	return handles[id]
}

func removeHandle(id int) {
	handleMu.Lock()
	defer handleMu.Unlock()
	delete(handles, id)
}

// GameConfig for JSON-based initialization
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
	// the zero value (all false) — handled by initGame via
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
// initGame translates this into interp.DeckPaddingSpec on the Runtime.
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

// resolveObsConfig merges the JSON-provided ObsConfigJSON (with
// optional per-field overrides) onto the legacy-all-on default.
// Missing (nil pointer) fields preserve the default.
func resolveObsConfig(j *ObsConfigJSON) engine.ObsConfig {
	out := engine.NewDefaultObsConfig()
	if j == nil {
		return out
	}
	if j.IncludeCharSkillRefs != nil {
		out.IncludeCharSkillRefs = *j.IncludeCharSkillRefs
	}
	if j.ShuffleCounters != nil {
		out.ShuffleCounters = *j.ShuffleCounters
	}
	if j.ShuffleHooks != nil {
		out.ShuffleHooks = *j.ShuffleHooks
	}
	if j.ShuffleCards != nil {
		out.ShuffleCards = *j.ShuffleCards
	}
	if j.ShuffleSkillSlots != nil {
		out.ShuffleSkillSlots = *j.ShuffleSkillSlots
	}
	return out
}

type PConfig struct {
	Chars []CharDef `json:"chars"`
}

type CharDef struct {
	Name string `json:"name"`
}

// Eagerly read + parse every *.lua file under the given data
// directory and populate the interp package's DSL cache. Call this
// once at training launch so mid-run DSL edits don't cause workers
// that haven't yet called GameNew to observe a partially-written
// file. Returns 0 on success, -1 on error (e.g. dataDir not a
// directory, parse error in some .lua file). Errors print to
// stderr.
//
// Safe to call multiple times — cache entries are already-parsed
// no-ops on re-preload.
//
//export DSLPreload
func DSLPreload(dataDir *C.char) C.int {
	root := C.GoString(dataDir)
	var paths []string
	err := filepath.Walk(root, func(p string, info os.FileInfo, e error) error {
		if e != nil {
			return e
		}
		if info.IsDir() {
			return nil
		}
		if strings.HasSuffix(p, ".lua") {
			paths = append(paths, p)
		}
		return nil
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "DSLPreload walk error: %v\n", err)
		return -1
	}
	if err := interp.PreloadDSLFiles(paths); err != nil {
		fmt.Fprintf(os.Stderr, "DSLPreload parse error: %v\n", err)
		return -1
	}
	return 0
}

//export GameNew
func GameNew(configJSON *C.char) C.int {
	var cfg GameConfig
	if err := json.Unmarshal([]byte(C.GoString(configJSON)), &cfg); err != nil {
		return -1
	}
	h, err := initGame(cfg)
	if err != nil {
		fmt.Fprintf(os.Stderr, "GameNew error: %v\n", err)
		return -1
	}
	return C.int(storeHandle(h))
}

//export GameFree
func GameFree(id C.int) {
	removeHandle(int(id))
}

//export GameClone
func GameClone(id C.int) C.int {
	src := getHandle(int(id))
	if src == nil {
		return -1
	}
	cloneRT := src.RT.Clone()
	return C.int(storeHandle(&GameHandle{Game: cloneRT.Game, RT: cloneRT}))
}

// C exports split across sibling files:
//   capi_init.go    — DSL path resolution + initGame
//   capi_snap.go    — snapshot / restore / snapshot_free / log suspend-resume
//   capi_actions.go — action loop, legal actions, setters, step
//   capi_state.go   — state / counters / obs size + bytes
//   capi_reward.go  — RewardEvents accumulator getter / reset
//   capi_labels.go  — labels / replay / utility / main()
