package audit

import (
	engine "gicg_mono/gicg_engine"
	"reflect"
	"sort"
	"strings"
)

type StatePolicy struct{ Field, Channel, Reason string }

// Every top-level gameplay field receives a reviewed observation policy. Unknown
// additions fail the audit rather than silently being treated as hidden state.
func PublicState() ([]StatePolicy, []string) {
	var rows []StatePolicy
	classified := map[string]bool{}
	add := func(fields, channel, reason string) {
		for _, field := range strings.Fields(fields) {
			classified[field] = true
			rows = append(rows, StatePolicy{field, channel, reason})
		}
	}
	add("Phase Round Turn FirstEnd MaxRounds FixDice", "meta", "public transition settings and ending order")
	add("Counters Buffs", "counter-values/buff-rows", "public quantities, typed references and ordered lifecycle state; enemy dice may be intentionally masked")
	add("Players", "player projection", "chars, counters, support slots/age and specialty rule refs; own hand/deck multiset, public discard, enemy sizes; ended flags in meta")
	add("Preparing RecentDamageEvents", "typed segments", "queued skills and recent damage/modifier summaries")
	add("PendingAction PendingCardTarget", "meta/legal-actions/execution-entities", "target frame rule and locals; nested replay bridge explicitly incomplete")
	add("PendingDice", "execution-entities", "own reroll frame exposes remaining rolls, color, pool and selected counts; opponent sees only pending owner")
	add("resume", "public cause / remaining limitation", "declared skill/card and round stage are encoded; private locals and remaining program are not fully encoded")
	add("BuffSerial", "internal identity", "lifecycle equality only; exclude absolute serial to avoid spurious learning")
	add("Rng BaseSeed DeckRngs DeckSeeds", "hidden randomness", "never reveal future draws or random streams")
	add("DicePaid DiceTunedOut DiceTunedIn", "public history summary outside NN", "used by determinization; recurrent/history-aware belief modeling remains separate")
	add("RewardAccum Winner", "training target", "reward/terminal supervision, not an input feature")
	add("ReactionNames ReactionRegistry BuffDefinitions Hooks RulesDigest CounterPerm HookPerm CardPerm SkillSlotPerm StructuralSids counterCharMap SkillNames CardNames CharNames CounterNames CanonicalSkillHooks CanonicalCardHooks Obs", "static rules/layout", "static IR, slot mappings, counter metadata and character skill references")
	add("PendingReactionKind eventStack depth damageLogStack executing", "execution scratch", "not a stable decision-boundary feature")
	add("Log Extra Failure", "attachment", "logging, runtime and diagnostic state")
	var issues []string
	typ := reflect.TypeOf(engine.Game{})
	for i := 0; i < typ.NumField(); i++ {
		field := typ.Field(i).Name
		if !classified[field] {
			issues = append(issues, "unclassified observation field: "+field)
		}
		delete(classified, field)
	}
	for field := range classified {
		issues = append(issues, "stale observation policy: "+field)
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].Field < rows[j].Field })
	sort.Strings(issues)
	return rows, issues
}
