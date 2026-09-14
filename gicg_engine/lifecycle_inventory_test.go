package engine

import (
	"reflect"
	"strings"
	"testing"
)

// Every new state field must get an explicit lifecycle decision. Behavioral
// tests supplement this inventory: listing a field does not prove it is copied.
func TestLifecycleFieldInventory(t *testing.T) {
	assertInventory := func(value any, groups ...string) {
		t.Helper()
		typ := reflect.TypeOf(value)
		fields := map[string]bool{}
		for _, group := range groups {
			for _, field := range strings.Fields(group) {
				if fields[field] {
					t.Fatalf("duplicate policy: %s.%s", typ.Name(), field)
				}
				fields[field] = true
			}
		}
		for i := 0; i < typ.NumField(); i++ {
			field := typ.Field(i).Name
			if !fields[field] {
				t.Errorf("unclassified state: %s.%s", typ.Name(), field)
			}
			delete(fields, field)
		}
		for field := range fields {
			t.Errorf("stale policy: %s.%s", typ.Name(), field)
		}
	}
	assertInventory(Game{},
		// Dynamic: full + pooled copy; reset explicit.
		`BuffSerial Buffs Counters Players Phase Round Turn FirstEnd Winner PendingAction PendingCardTarget PendingDice
        DicePaid DiceTunedOut DiceTunedIn Preparing Rng BaseSeed DeckRngs DeckSeeds
        RewardAccum PendingReactionKind RecentDamageEvents resume`,
		// Immutable definition / layout: shared by clones, preserved on restore/reset.
		`BuffDefinitions Hooks CounterPerm HookPerm CardPerm SkillSlotPerm StructuralSids counterCharMap
        SkillNames CardNames CharNames CounterNames CanonicalSkillHooks CanonicalCardHooks
        Obs MaxRounds FixDice ReactionRegistry ReactionNames RulesDigest`,
		// Execution scratch: must be empty at snapshot boundary; cleared by reset.
		`eventStack depth damageLogStack executing`,
		// Attachments: excluded from restore, clone clears; Runtime.Clone rebinds Extra.
		`Log Extra Failure`,
	)
	assertInventory(PlayerState{}, `Chars ActiveChar Hand Deck Discard Supports InitDeck DeclaredEnd`)
	assertInventory(SupportInst{}, `ID Ref ActivatedAt BuffID`) // value-copied with the Supports slice
	assertInventory(CharInfo{}, `Alive SpecialtyCardRef`, `PlayerIdx CharIdx Skills Element`)
	assertInventory(Action{}, `Kind PlayerIdx Index Forced DicePayment AppliedMods HasTarget TargetPlayer TargetChar HasBuffTarget TargetBuff HasSupportTarget TargetSupport TuneSourceColor RerollColor`)
	assertInventory(DiceSelection{}, `Player Remaining Color Pool Selected`)
	assertInventory(PendingCard{}, `PC PlayerIdx CardRef BattleAction TargetMode AppliedMods`)
	assertInventory(continuation{}, `root op choices log public`)
	assertInventory(publicCause{}, `Kind Player Char Hook TargetPlayer TargetChar Stage`)
}

func TestLifecycle_RejectsWrongRulesAndBusySnapshots(t *testing.T) {
	a := &Game{Hooks: NewHookRegistry(), Rng: NewRandom(7)}
	b := &Game{Hooks: NewHookRegistry(), Rng: NewRandom(7)}
	if a.CanRestoreFrom(b) {
		t.Fatal("different rulesets accepted")
	}
	a.PushEvent(EventFrame{})
	if a.IsQuiescent() {
		t.Fatal("active event frame accepted")
	}
	defer func() {
		if recover() == nil {
			t.Fatal("busy snapshot did not fail")
		}
	}()
	a.SnapshotPooled()
}

func TestLifecycle_CloneDoesNotShareEmptyStackCapacity(t *testing.T) {
	g := &Game{Hooks: NewHookRegistry()}
	g.PushEvent(EventFrame{Player: 0})
	g.PopEvent()
	if cap(g.eventStack) == 0 {
		t.Fatal("fixture did not retain capacity")
	}
	a, b := g.DeepCopy(), g.DeepCopy()
	a.PushEvent(EventFrame{Player: 0})
	b.PushEvent(EventFrame{Player: 1})
	if a.CurrentEvent().Player != 0 {
		t.Fatal("clone event storage was overwritten by sibling")
	}
	if len(g.eventStack) != 0 {
		t.Fatal("clone changed original stack")
	}
}
