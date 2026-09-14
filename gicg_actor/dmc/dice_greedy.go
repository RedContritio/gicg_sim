// dice_greedy.go — Go port of training/core/matchup/greedy_dice.py。
//
// 背景:GICG 引擎把"同一逻辑动作的不同 dice payment 组合" fan-out 成多个独立
// Action(e.g. cost [1 pyro, 2 any] → C(pool, 2) 个 payment)。 len(GetLegalActions())
// 从 ~10-30(逻辑动作数)膨胀到 ~100-500。 GreedyPlayer minimax 是 O(N^depth),N 膨胀
// 让 D4 灾难性。
//
// filterLogicalActions 把 fan-out 折叠成"每逻辑动作 1 个 top-payment":按 engine-native
// action identity (kind, subject_ref, aux, target_player, target_char) 分组,组内选
// payment_cost 最小的 — N → N_logical。 折叠**只影响 minimax 迭代哪些 action**;返回的
// index 仍是 index into GetLegalActions(),g.Step(idx) 不变。
//
// 数值/分层逻辑严格照 Python ref(greedy_dice.py docstring 的 heuristic):
//   - Tier 1000:color 匹配出战角色 element(scarce + critical)
//   - Tier  500:omni(color 7)— wildcard,即使 1 个也珍贵
//   - Tier  100:color 匹配任意 alive 后台角色 element
//   - Tier 10×count:其他颜色(杂色)— pool 里越多越有价值("杂色数量多>数量少")
//
// payment_cost = Σ_c (payment[c] × value[c])。 组内 min payment_cost 的 payment 入选。
// Tune(ActionKind=4)tiebreak:同 cost 时偏好 discard 低价值卡(用 hand index 代理,
// 低 index = 老牌 = 更"稳定" = 优先 discard,跟 Python _tune_card_value 一致)。

package dmc

import (
	engine "gicg_mono/gicg_engine"
)

// dice value tiers — mirror greedy_dice.py module constants。
const (
	valueActive       = 1000 // 出战角色同色
	valueOmni         = 500  // omni 万能骰
	valueBackline     = 100  // 后台 alive 角色同色
	valueJunkPerCount = 10   // 杂色 base = 10 × pool_count
)

// buildColorValues 计算每 dice color 的价值数组(长度 8),HIGHER = 更想保留。
//
// me:acting player index。 dicePool[8]:live per-color counts(杂色 base 用)。
// 严格照 Python build_color_values:先用 pool count seed 杂色 base,再用 role-based
// tier override(取 max 不覆盖更高的)。
func buildColorValues(g *engine.Game, me int, dicePool [engine.DiceColorCount]int) [engine.DiceColorCount]int {
	var values [engine.DiceColorCount]int

	chars := g.Players[me].Chars
	activeIdx := g.Players[me].ActiveChar

	// 出战角色 element → color。
	activeColor := -1
	if activeIdx >= 0 && activeIdx < len(chars) {
		activeColor = engine.ElementToDiceColor(chars[activeIdx].Element)
	}

	// 后台(alive 非出战)角色 element → color set。
	backlineColors := map[int]bool{}
	for i, ch := range chars {
		if i == activeIdx {
			continue
		}
		if !ch.Alive {
			continue
		}
		c := engine.ElementToDiceColor(ch.Element)
		if c >= 0 {
			backlineColors[c] = true
		}
	}

	// 杂色 base = 10 × pool_count(abundant > rare)。
	for c := 0; c < engine.DiceColorCount; c++ {
		values[c] = valueJunkPerCount * dicePool[c]
	}

	// role-based tier override(仅当当前值更低才抬,跟 Python `if values[c] < tier` 一致)。
	for c := range backlineColors {
		if values[c] < valueBackline {
			values[c] = valueBackline
		}
	}
	if activeColor >= 0 && values[activeColor] < valueActive {
		values[activeColor] = valueActive
	}
	// omni 永远拿固定 omni tier,不看 pool count(即使 1 个 omni 也珍贵)。
	if values[engine.DiceColorOmni] < valueOmni {
		values[engine.DiceColorOmni] = valueOmni
	}
	return values
}

// paymentCost 返 Σ_c (payment[c] × value[c])。 mirror Python payment_cost。
func paymentCost(payment [engine.DiceColorCount]int8, colorValues [engine.DiceColorCount]int) int {
	cost := 0
	for c := 0; c < engine.DiceColorCount; c++ {
		cost += int(payment[c]) * colorValues[c]
	}
	return cost
}

// actionIdentity 计算 engine-native action identity tuple
// (kind, subject_ref, aux, target_player, target_char) — 跟
// capi_actions_query.go::GameGetActionIdentities 逐字段等价。
// 这是 determinization-stable、permutation-independent 的逻辑动作 key。
func actionIdentity(g *engine.Game, a engine.Action) [5]int {
	kind := int(a.Kind)
	subject := -1
	aux := -1
	tgtP := -1
	tgtC := -1
	switch a.Kind {
	case engine.ActionReroll:
		subject, aux = a.Index, a.RerollColor
	case engine.ActionSkill:
		subject = a.Index // globally-unique skill ID
	case engine.ActionCard:
		pi := a.PlayerIdx
		if a.Index >= 0 && a.Index < len(g.Players[pi].Hand) {
			subject = g.Players[pi].Hand[a.Index].Ref
		}
		if a.HasTarget {
			tgtP = a.TargetPlayer
			tgtC = a.TargetChar
		}
		if a.HasBuffTarget {
			aux, tgtP, tgtC = a.TargetBuff, a.TargetPlayer, -1
		}
		if a.HasSupportTarget {
			aux, tgtP, tgtC = engine.ObsBuffRows+a.TargetSupport, a.PlayerIdx, -1
		}
	case engine.ActionSwitch:
		subject = a.Index // target char slot
	case engine.ActionTune:
		pi := a.PlayerIdx
		if a.Index >= 0 && a.Index < len(g.Players[pi].Hand) {
			subject = g.Players[pi].Hand[a.Index].Ref
		}
		aux = a.TuneSourceColor
	}
	return [5]int{kind, subject, aux, tgtP, tgtC}
}

// filterLogicalActions 把 g.GetLegalActions() 折叠成"每逻辑动作 1 个 top-payment"。
// 返回 sorted index into GetLegalActions() — caller(minimax)迭代这些 index 而非
// range(n_legal)。 g.Step(idx) 接的就是这个 index。
//
// 分组 key = action identity tuple。 组内选 payment_cost 最小的 payment;Tune 组同 cost
// 时 tiebreak 偏好低价值卡(hand index 代理)。 单 payment 的 action(便宜技能 / switch /
// end_turn)原样通过。
//
// 严格照 Python filter_logical_actions:dict 保插入序分组 → 最后 sort 输出。
func filterLogicalActions(g *engine.Game) []int {
	actions := g.GetLegalActions()
	n := len(actions)
	if n == 0 {
		return nil
	}

	me := g.ActingPlayer()

	// 读 acting player 的 dice pool(8 slots)。 g.Extra 是 DicePoolProvider
	// (interp.Runtime),跟 action.go::GetLegalActions 内部一致。
	provider := g.Extra.(engine.DicePoolProvider)
	var dicePool [engine.DiceColorCount]int
	for c := 0; c < engine.DiceColorCount; c++ {
		dicePool[c] = g.Counters[provider.DiceCounterID(me, c)].Value
	}

	colorValues := buildColorValues(g, me, dicePool)

	// 按 identity 分组。 用 slice + map 保插入序(Python dict 保序)。
	type group struct {
		key  [5]int
		idxs []int
	}
	var groups []group
	keyToGroup := map[[5]int]int{}
	for i := 0; i < n; i++ {
		key := actionIdentity(g, actions[i])
		gi, ok := keyToGroup[key]
		if !ok {
			gi = len(groups)
			groups = append(groups, group{key: key})
			keyToGroup[key] = gi
		}
		groups[gi].idxs = append(groups[gi].idxs, i)
	}

	chosen := make([]int, 0, len(groups))
	for _, grp := range groups {
		if len(grp.idxs) == 1 {
			chosen = append(chosen, grp.idxs[0])
			continue
		}
		kind := grp.key[0]
		best := grp.idxs[0]
		bestCost := paymentCost(actions[best].DicePayment, colorValues)
		if kind == int(engine.ActionTune) {
			// Tune:min payment_cost,tiebreak 偏好 discard 低价值卡。
			// _tune_card_value 代理 = hand index(低 = 老 = 更稳 = 优先 discard,
			// 低 value 先 discard)。 identity[1] 是 subject_ref(discarded card),
			// 但 Python 实际用 hand_idx — 这里直接用 actions[i].Index(hand index)。
			bestTune := actions[best].Index
			for _, i := range grp.idxs[1:] {
				cost := paymentCost(actions[i].DicePayment, colorValues)
				tune := actions[i].Index
				if cost < bestCost || (cost == bestCost && tune < bestTune) {
					best = i
					bestCost = cost
					bestTune = tune
				}
			}
		} else {
			// Skill / Card / Switch / EndTurn:min payment_cost。
			for _, i := range grp.idxs[1:] {
				cost := paymentCost(actions[i].DicePayment, colorValues)
				if cost < bestCost {
					best = i
					bestCost = cost
				}
			}
		}
		chosen = append(chosen, best)
	}

	// Python 末尾 chosen.sort() — index 升序。 这里分组按插入序已经基本有序,
	// 但组内选的 best 可能跳序,显式 sort 保证跟 Python 一致。
	sortInts(chosen)
	return chosen
}

// sortInts — 简单插入排序(chosen 长度 ~10-30,不值得 import sort)。
func sortInts(a []int) {
	for i := 1; i < len(a); i++ {
		v := a[i]
		j := i - 1
		for j >= 0 && a[j] > v {
			a[j+1] = a[j]
			j--
		}
		a[j+1] = v
	}
}
