package main

/*
#include <stdlib.h>
*/
import "C"

import (
	engine "gicg_mono/gicg_engine"
	"unsafe"
)

// GameGetRewardEvents writes the per-player RewardEvents accumulator
// into an out buffer of 14 ints in the canonical field order. The
// engine records raw occurrences only — any scalar reward formula is
// the caller's concern (Python GreedyPlayer / RL training / diagnostic
// tools map the 14 signals to their own scoring functions).
//
// Slot layout (indexed from 0 — must stay in sync with
// engine.RewardEvents field order):
//
//	 0: DamageDealt
//	 1: DamageReceived
//	 2: HealDone
//	 3: EnemyHealDone
//	 4: ShieldAbsorbed
//	 5: DamageBlocked
//	 6: Kills
//	 7: TotalKills
//	 8: Deaths
//	 9: TotalDeaths
//	10: ReactionsTriggered
//	11: ReactionsReceived
//	12: APWasted
//	13: EnergyOverflow
//
// Caller must pre-allocate `out` to RewardEventsFieldCount ints.
//
//export GameGetRewardEvents
func GameGetRewardEvents(id C.int, player C.int, out *C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	p := int(player)
	if p < 0 || p > 1 {
		return
	}
	r := &h.Game.RewardAccum[p]
	arr := unsafe.Slice((*C.int)(unsafe.Pointer(out)), engine.RewardEventsFieldCount)
	arr[0] = C.int(r.DamageDealt)
	arr[1] = C.int(r.DamageReceived)
	arr[2] = C.int(r.HealDone)
	arr[3] = C.int(r.EnemyHealDone)
	arr[4] = C.int(r.ShieldAbsorbed)
	arr[5] = C.int(r.DamageBlocked)
	arr[6] = C.int(r.Kills)
	arr[7] = C.int(r.TotalKills)
	arr[8] = C.int(r.Deaths)
	arr[9] = C.int(r.TotalDeaths)
	arr[10] = C.int(r.ReactionsTriggered)
	arr[11] = C.int(r.ReactionsReceived)
	arr[12] = C.int(r.APWasted)
	arr[13] = C.int(r.EnergyOverflow)
}

// GameResetReward zeroes the per-episode RewardEvents accumulator for
// both players. Intended for env.reset() — a clean slate for the new
// episode's signals. NOT for per-step resets: within an episode,
// TotalKills / TotalDeaths are monotone counters that F5's escalating
// kill slope reads as "how many kills so far?".
//
//export GameResetReward
func GameResetReward(id C.int) {
	defer recoverRuleError(id)
	h := getHandle(int(id))
	if h == nil {
		return
	}
	h.Game.RewardAccum = [2]engine.RewardEvents{}
}
