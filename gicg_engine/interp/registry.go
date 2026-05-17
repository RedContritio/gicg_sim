package interp

import (
	engine "gicg_mono/gicg_engine"
)

// Registry types for counters / chars / skills / cards. The per-game
// dynamic Runtime + helpers live in runtime.go.

const MaxChars = 6

// RefKind tells a counter proxy how to interpret its raw int value
// when DSL reads or writes it. A RefKind-tagged counter stores an
// integer ID internally (same storage as any other counter), but
// automatically wraps the ID into the corresponding typed Value on
// read and unwraps it on write.
//
// The sentinel value -1 stored in the counter means "no ref".
const (
	RefKindNone  = 0 // raw int counter (default)
	RefKindSkill = 1 // stores *SkillRef (by ID)
	RefKindCard  = 2 // stores *CardRef (by Ref)
)

// Scope constants matching DSL Scope enum
const (
	ScopeSelf         = 0
	ScopeActiveStatus = 1
	ScopePerChar      = 2
	ScopePerPlayer    = 3
	ScopeGlobal       = 4
)

// Player constants matching DSL Player enum
const (
	PlayerOwn   = -10
	PlayerEnemy = -11
	PlayerAll   = -12
)

// --- Counter Registry ---

type CounterEntry struct {
	Ref         Value // the proxy object returned to DSL (CounterProxy, PerPlayerProxy, PerCharProxy)
	CounterIDs  []int // raw counter IDs in Game.Counters
	Scope       int
	Min, Max    int
	InitValue   int
	Tag         int    // 0 = no tag
	Display     string // human-readable name for record/replay; empty = fallback to internal name
	OwnerPlayer int
	OwnerChar   int
	// RefKind tags this counter as storing a typed ref (skill, card)
	// instead of a raw int. DSL get/set on the backing proxy auto-
	// wraps the stored int into the corresponding Value type when
	// reading, and unwraps back to int when writing. Sentinel -1 in
	// the raw counter means "no ref". RefKindNone = raw int behavior.
	RefKind int
	// SlotIDs is populated only for Scope.Self / Scope.ActiveStatus
	// entries. It records per-slot counter allocations across all
	// (player, char) slots, populated progressively by per-binding
	// char-file declares or all-at-once by shared-load talent-card
	// declares. Used by shared-load cross-reference get_counter to
	// construct a SelfSlotProxy (dynamic slot resolution via ctx).
	// nil for PerPlayer / PerChar / Global entries. Entries are
	// indexed by (player*MaxChars + char), -1 if no counter allocated
	// at that slot.
	SlotIDs []int
}

type CounterRegistry struct {
	Entries   map[string]*CounterEntry
	TagGroups map[int][]*CounterEntry
}

func NewCounterRegistry() *CounterRegistry {
	return &CounterRegistry{
		Entries:   make(map[string]*CounterEntry),
		TagGroups: make(map[int][]*CounterEntry),
	}
}

// --- Char Registry ---

type CharEntry struct {
	Name            string
	HPCounterID     int
	EnergyCounterID int
	AliveCounterID  int
	ActiveCounterID int
	Element         int
	Weapon          int
	PlayerIdx       int // -1 = unbound
	CharIdx         int
	Skills          map[string]int // name → skill ID
	SkillIDs        []int
	// NormalAttackID is the skill ID of this char's "normal attack",
	// identified at declare time as the first skill whose DiceCost has
	// Any > 0 (GI TCG normal attacks are 1 element + 2 any; skills and
	// bursts are pure specific). -1 if not yet identified. Used by DSL
	// cards (速速茶点, 铁剑) to check "is the current skill a normal
	// attack" without hard-coding per-char skill names.
	NormalAttackID int

	// SpecialtyCardRef holds the card_ref currently equipped to this
	// char's specialty slot (-1 = empty; 0 is a valid card ref). Set
	// when a Slot.Specialty card is played targeting this char; checked
	// by on_action_check on other Slot.Specialty cards to reject
	// (1-card cap per char). See ADR-0012 § 2.
	//
	// Default is initialized to -1 in BindChar (NewCharEntry can't —
	// declare time CharEntry doesn't run through a constructor).
	SpecialtyCardRef int
}

type CharRegistry struct {
	ByName map[string]*CharEntry
	BySlot [2][MaxChars]*CharEntry
}

func NewCharRegistry() *CharRegistry {
	return &CharRegistry{
		ByName: make(map[string]*CharEntry),
	}
}

// --- Skill Registry ---

// SkillRef is the DSL-facing handle for a skill. Zero value is nil.
// DSL compares skills via pointer identity.
type SkillRef struct {
	ID       int
	Name     string
	CharName string
	Cost     engine.Cost // dice cost + energy
}

type SkillRegistry struct {
	ByID   map[int]*SkillRef
	NextID int
}

func NewSkillRegistry() *SkillRegistry {
	return &SkillRegistry{
		ByID: make(map[int]*SkillRef),
	}
}

// --- Card Registry ---

// CardSlot tags a card with a structural attach destination. Most
// cards leave this 0 (SlotNone) — they enter the hand, fire effects,
// and discard. Equipment / support / specialty cards instead attach
// to a player-visible slot:
//
//   - SlotEquip:     weapon / artifact / talent (per-char,1 each)
//   - SlotSupport:   support zone (per-player,4 max)
//   - SlotSpecialty: specialty (per-char,1) — see ADR-0012
//
// Slot semantics are enforced engine-side at on_action_check
// (reject when slot is full) and on_card_play (record occupancy).
type CardSlot int

const (
	SlotNone CardSlot = iota
	SlotEquip
	SlotSupport
	SlotSpecialty
)

// CardRef is the DSL-facing handle for a card. Zero value is nil.
type CardRef struct {
	Ref            int
	Name           string
	Cost           engine.Cost // dice cost + energy (usually 0 for cards)
	BattleAction   bool
	TargetMode     int // 0=none, 1=own_char, 2=enemy_char
	RequiresWeapon int // 0 = no requirement
	RequiresChar   string
	Slot           CardSlot // SlotNone = ordinary action card
}

type CardRegistry struct {
	ByName  map[string]*CardRef
	ByRef   map[int]*CardRef
	NextRef int
}

func NewCardRegistry() *CardRegistry {
	return &CardRegistry{
		ByName: make(map[string]*CardRef),
		ByRef:  make(map[int]*CardRef),
	}
}
