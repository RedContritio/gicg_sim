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

// Scorers — name → ScorerFn registry。 Phase 1.2c add F2-F5。
var Scorers = map[string]ScorerFn{
	"F1": ScoreF1,
}
