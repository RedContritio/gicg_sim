// events.go — RewardEvents snapshot helper for scorers + minimax bracketing。
//
// Python ref:greedy_scorers.py 用 ``np.ndarray[14]`` from `env.reward_events(me)`(capi
// GameGetRewardEvents 把 engine.RewardEvents struct 写到 int 数组 in stable field order)。
// Go side 用同顺序 [14]int snapshot,直接 from gicg_engine.RewardEvents struct copy 出。
//
// Stable field order(must match capi_reward.go GameGetRewardEvents):
//
//	0: DamageDealt
//	1: DamageReceived
//	2: HealDone
//	3: EnemyHealDone
//	4: ShieldAbsorbed
//	5: DamageBlocked
//	6: Kills
//	7: TotalKills
//	8: Deaths
//	9: TotalDeaths
//	10: ReactionsTriggered
//	11: ReactionsReceived
//	12: APWasted
//	13: EnergyOverflow
//
// 跟 Python REWARD_EVENTS_FIELDS 同顺序(gicg_env/_constants.py 内 stable 列出)。

package dmc

import (
	engine "gicg_mono/gicg_engine"
)

// EventsSnapshot 是 RewardEvents 14 字段的 [14]int snapshot,for view delta computation。
type EventsSnapshot [14]int

// SnapshotEvents 从 engine.Game 当前 RewardAccum[me] 读出 [14]int 快照(为 minimax
// bracket before/after delta 用)。
func SnapshotEvents(g *engine.Game, me int) *EventsSnapshot {
	if me < 0 || me >= 2 {
		return &EventsSnapshot{}
	}
	r := &g.RewardAccum[me]
	return &EventsSnapshot{
		r.DamageDealt,
		r.DamageReceived,
		r.HealDone,
		r.EnemyHealDone,
		r.ShieldAbsorbed,
		r.DamageBlocked,
		r.Kills,
		r.TotalKills,
		r.Deaths,
		r.TotalDeaths,
		r.ReactionsTriggered,
		r.ReactionsReceived,
		r.APWasted,
		r.EnergyOverflow,
	}
}

// Event index 常量(Python ref EV_*)。
const (
	EvDamageDealt        = 0
	EvDamageReceived     = 1
	EvHealDone           = 2
	EvEnemyHealDone      = 3
	EvShieldAbsorbed     = 4
	EvDamageBlocked      = 5
	EvKills              = 6
	EvTotalKills         = 7
	EvDeaths             = 8
	EvTotalDeaths        = 9
	EvReactionsTriggered = 10
	EvReactionsReceived  = 11
	EvAPWasted           = 12
	EvEnergyOverflow     = 13
)
