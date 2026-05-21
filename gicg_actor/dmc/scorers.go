// scorers.go — F1-F5 feature scorers for GreedyPlayer Go port。
//
// Phase 1.2b minimal:仅 F1。 Phase 1.2c follow-up:F2-F5(escalating kill / heal /
// shield / reaction / energy / AP penalty 等)。 详 Python ref:
// training/core/matchup/greedy_scorers.py。
//
// Scorer 签名(per Python ref):
//
//	(view_before, view_after, events_before, events_after, me) → float64 score
//
// 数值等价目标:winrate gate(不是 bit-exact)— Go-D2/D4 跑 n=128 swap matches winrate
// 落 Python baseline 95% CI 内(详 design.md D2)。 浮点 ops 顺序在 D1 单层不 critical
// (只 1 次 argmax,no compounding error),但 D2-D4 minimax tree 会累积。

package dmc

import (
	"gicg_mono/gicg_engine/record"
)

// ScorerFn — Python ref 的 ScorerFn typedef Go 版。
type ScorerFn func(viewBefore, viewAfter *record.StateView, eventsBefore, eventsAfter *EventsSnapshot, me int) float64

// totalHPAlive 返 (sum HP, alive count) for player “me“。 Mirror Python
// `_own_hp_alive(view, me)`。
func totalHPAlive(view *record.StateView, me int) (int, int) {
	if me < 0 || me >= 2 {
		return 0, 0
	}
	chars := view.Players[me].Chars
	totalHP := 0
	alive := 0
	for _, c := range chars {
		totalHP += c.HP
		if c.Alive {
			alive++
		}
	}
	return totalHP, alive
}

// ScoreF1 实现 Python `_score_f1`:dmg_dealt - 1.1 * dmg_received。 Ignores events。
//
// 跟 Python ref bit-exact 数值等价(简单 HP 差 + float64 乘法,IEEE 754 deterministic across
// platforms when ops 顺序相同)。
func ScoreF1(viewBefore, viewAfter *record.StateView, eventsBefore, eventsAfter *EventsSnapshot, me int) float64 {
	_ = eventsBefore
	_ = eventsAfter
	opp := 1 - me
	ownBefore, _ := totalHPAlive(viewBefore, me)
	ownAfter, _ := totalHPAlive(viewAfter, me)
	enemyBefore, _ := totalHPAlive(viewBefore, opp)
	enemyAfter, _ := totalHPAlive(viewAfter, opp)
	dmgDealt := enemyBefore - enemyAfter
	dmgTaken := ownBefore - ownAfter
	return float64(dmgDealt) - 1.1*float64(dmgTaken)
}

// apWastePiecewise — Python ref `_ap_waste_piecewise`:分段递增 penalty for unused AP at
// round end。 前 3 AP cheap (0.2),后 3 中等 (0.5),再 2 重 (0.8),> 8 极重 (1.0)。
// 模拟 marginal value 凸性。
func apWastePiecewise(n int) float64 {
	if n < 0 {
		n = 0
	}
	clamp := func(v, lo, hi int) int {
		if v < lo {
			return lo
		}
		if v > hi {
			return hi
		}
		return v
	}
	t1 := clamp(n, 0, 3)
	t2 := clamp(n-3, 0, 3)
	t3 := clamp(n-6, 0, 2)
	t4 := n - 8
	if t4 < 0 {
		t4 = 0
	}
	return 0.2*float64(t1) + 0.5*float64(t2) + 0.8*float64(t3) + 1.0*float64(t4)
}

// killSlopeEscalating — Python ref `_kill_slope_escalating`:每个 kill 附加 5*(total_before+i)
// 递增 bonus(F5 only)。 F2 已经给 10·k 平 base,本函数返 additional slope only,防 double count。
func killSlopeEscalating(k, totalBefore int) float64 {
	sum := 0.0
	for i := range k {
		sum += 5.0 * float64(totalBefore+i)
	}
	return sum
}

// ScoreF2 实现 Python `_score_f2`:F1 + 10·kill - 8·death(flat kill_base)。
func ScoreF2(viewBefore, viewAfter *record.StateView, eventsBefore, eventsAfter *EventsSnapshot, me int) float64 {
	opp := 1 - me
	_, ownAliveBefore := totalHPAlive(viewBefore, me)
	_, ownAliveAfter := totalHPAlive(viewAfter, me)
	_, enemyAliveBefore := totalHPAlive(viewBefore, opp)
	_, enemyAliveAfter := totalHPAlive(viewAfter, opp)
	killDelta := enemyAliveBefore - enemyAliveAfter
	if killDelta < 0 {
		killDelta = 0
	}
	deathDelta := ownAliveBefore - ownAliveAfter
	if deathDelta < 0 {
		deathDelta = 0
	}
	return ScoreF1(viewBefore, viewAfter, eventsBefore, eventsAfter, me) + 10.0*float64(killDelta) - 8.0*float64(deathDelta)
}

// ScoreF3 实现 Python `_score_f3`:F2 + (heal_done - 0.8·enemy_heal_done)。 用 events delta。
func ScoreF3(viewBefore, viewAfter *record.StateView, eventsBefore, eventsAfter *EventsSnapshot, me int) float64 {
	heal := float64(eventsAfter[EvHealDone]-eventsBefore[EvHealDone]) -
		0.8*float64(eventsAfter[EvEnemyHealDone]-eventsBefore[EvEnemyHealDone])
	return ScoreF2(viewBefore, viewAfter, eventsBefore, eventsAfter, me) + heal
}

// ScoreF4 实现 Python `_score_f4`:F3 + (shield_absorbed - 0.8·damage_blocked) +
// (reactions_triggered - 0.8·reactions_received)。 非对称权重让 me-side / enemy-side
// 净不为 0 当我 trigger 时。
func ScoreF4(viewBefore, viewAfter *record.StateView, eventsBefore, eventsAfter *EventsSnapshot, me int) float64 {
	shield := float64(eventsAfter[EvShieldAbsorbed]-eventsBefore[EvShieldAbsorbed]) -
		0.8*float64(eventsAfter[EvDamageBlocked]-eventsBefore[EvDamageBlocked])
	react := float64(eventsAfter[EvReactionsTriggered]-eventsBefore[EvReactionsTriggered]) -
		0.8*float64(eventsAfter[EvReactionsReceived]-eventsBefore[EvReactionsReceived])
	return ScoreF3(viewBefore, viewAfter, eventsBefore, eventsAfter, me) + shield + react
}

// ScoreF5 实现 Python `_score_f5`:F4 + energy/AP penalty + escalating kill slope on top
// of F2 flat。
func ScoreF5(viewBefore, viewAfter *record.StateView, eventsBefore, eventsAfter *EventsSnapshot, me int) float64 {
	energyPen := -0.4 * float64(eventsAfter[EvEnergyOverflow]-eventsBefore[EvEnergyOverflow])
	apPen := -apWastePiecewise(eventsAfter[EvAPWasted] - eventsBefore[EvAPWasted])
	killBonus := killSlopeEscalating(
		eventsAfter[EvKills]-eventsBefore[EvKills],
		eventsBefore[EvTotalKills],
	)
	return ScoreF4(viewBefore, viewAfter, eventsBefore, eventsAfter, me) + energyPen + apPen + killBonus
}

// Scorers — name → ScorerFn registry。 完整 F1-F5(同 Python ref)。
var Scorers = map[string]ScorerFn{
	"F1": ScoreF1,
	"F2": ScoreF2,
	"F3": ScoreF3,
	"F4": ScoreF4,
	"F5": ScoreF5,
}
