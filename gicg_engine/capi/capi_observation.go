package main

/*
#include <stdlib.h>
#include <string.h>
*/
import "C"

import (
	engine "gicg_mono/gicg_engine"
	"unsafe"
)

//export GameGetStaticObsSize
func GameGetStaticObsSize() C.int {
	return C.int(engine.StaticObsSize())
}

//export GameGetDefinitionLinkCapacity
func GameGetDefinitionLinkCapacity() C.int {
	return C.int(engine.ObsMaxDefinitionLinks)
}

//export GameGetDefinitionLinkSchemaVersion
func GameGetDefinitionLinkSchemaVersion() C.int {
	return C.int(engine.ObsDefinitionLinkSchemaVersion)
}

//export GameGetDynamicObsSize
func GameGetDynamicObsSize() C.int {
	return C.int(engine.DynamicObsSize())
}

// GameGetReactionCount — Round-6 S-1: Python verify ReactionCount ≤
// REACTION_VOCAB-3 at game init (push reaction-count check 从 forward
// raise 到 game init,DSL declare 越界即时报错)。
//
//export GameGetReactionCount
func GameGetReactionCount(id C.int) C.int {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return -1
	}
	return C.int(h.Game.ReactionCount())
}

// GameGetTypedObsConstants exports the 8 Go-side obs layout constants
// Python uses to compute typed-segment offsets, so Python can verify
// its hard-coded mirrors match at startup (review B2 + Round-2 M2 —
// hand block constants also affect typed segment slicing offset; if
// those drift Go↔Python the typed segments read from wrong positions
// without _verify catching it).
//
// Output array layout (8 * sizeof(int)):
//
//	[0] OBS_RECENT_DAMAGE_EVENTS
//	[1] OBS_RECENT_DAMAGE_FIELD_COUNT
//	[2] OBS_PREPARE_SKILL_SLOTS
//	[3] OBS_MODIFIER_LOG_K_MOD
//	[4] OBS_MODIFIER_LOG_FIELD_COUNT
//	[5] OBS_MAX_CARD_TYPES        — hand bucket width (Round-2 M2)
//	[6] OBS_HAND_BUCKETS          — number of hand buckets (Round-2 M2)
//	[7] OBS_ENEMY_SIZES_HARDCODED — hand-block trailing scalar count (Round-2 M2)
//
//export GameGetTypedObsConstants
func GameGetTypedObsConstants(out *C.int) {
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), 8)
	arr[0] = C.int(engine.ObsRecentDamageEvents)
	arr[1] = C.int(engine.ObsRecentDamageFieldCount)
	arr[2] = C.int(engine.ObsPrepareSkillSlots)
	arr[3] = C.int(engine.ObsModifierLogKMod)
	arr[4] = C.int(engine.ObsModifierLogFieldCount)
	arr[5] = C.int(engine.ObsMaxCardTypes)
	arr[6] = 4 // OBS_HAND_BUCKETS — hardcoded in observation_dynamic.go (own hand/deck/discard + enemy discard)
	arr[7] = 2 // OBS_ENEMY_SIZES — enemy hand/deck size scalars
}

// GameGetIRLayoutConstants exports the IR-2.b.2 hook obs layout
// constants (replaces the legacy ObsMaxTokensPerHook × 2 token-pair
// segment). Python uses these to slice the hook section of static obs
// into (n_hooks, max_ops, fields) for the IR encoder.
//
// Output array layout (4 * sizeof(int)):
//
//	[0] OBS_MAX_HOOKS               — hook slot count
//	[1] OBS_MAX_OPS_PER_HOOK        — max IR ops per hook
//	[2] OBS_FIELDS_PER_OP           — int32 fields per op (= 5)
//	[3] OBS_INTS_PER_HOOK           — slot size = OPS × FIELDS
//
//export GameGetIRLayoutConstants
func GameGetIRLayoutConstants(out *C.int) {
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), 4)
	arr[0] = C.int(engine.ObsMaxHooks)
	arr[1] = C.int(engine.ObsMaxOpsPerHook)
	arr[2] = C.int(engine.ObsFieldsPerOp)
	arr[3] = C.int(engine.ObsIntsPerHook)
}

//export GameGetStaticObs
func GameGetStaticObs(id C.int, out *C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	obs := h.Game.BuildStaticObs()
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), len(obs))
	for i, v := range obs {
		arr[i] = C.int(v)
	}
}
