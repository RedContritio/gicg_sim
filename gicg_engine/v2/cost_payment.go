package enginev2

// A24 — Cost payment auto-resolve。
//
// engine 默认按"字典序最小合法 dice 子集"自动 pay,
// 只在 cost 有 meaningful choice (玩家可能 strategically 选不同) 时显式 enter
// cost_payment substate。**90% 普通卡跳过 RL cost step**,避免 expand_union_k 重蹈覆辙。
//
// 关键设计: meaningful 检测必须 **O(N) 非 NP** (review 质疑算法本身可能 NP)。
// 本 prototype 实现 greedy 检测 + 自动选 algorithm。

// DiceColor 简化枚举 (实际 v1 已有,这里 prototype 独立)
type DiceColor int

const (
	DiceFire DiceColor = iota
	DiceIce
	DiceWater
	DiceElectro
	DiceGeo
	DiceAnemo
	DiceDendro
	DiceOmni
	DiceColorCount
)

// CostSpec — declare_card / declare_skill 声明的 cost。
// Specific[color] = N (火 1 / 水 2 / etc.); Same = N (任意同色 N); Any = N (任意 N)。
type CostSpec struct {
	Specific [DiceColorCount]int // 具体元素 cost (Omni 槽位通常 0)
	Same     int                 // 同色 N (玩家可选哪种 specific kind)
	Any      int                 // 任意 N (Omni 优先,specific 也可)
}

// DicePool — 玩家当前 dice 数 (按 color)。
type DicePool [DiceColorCount]int

func (d DicePool) Total() int {
	t := 0
	for _, n := range d {
		t += n
	}
	return t
}

// IsCostMeaningful — 检测 cost 是否对玩家有 strategic choice。
// O(N) algorithm,不枚举所有合法 subset。
//
// 触发 meaningful (engine 显式 enter substate):
//
//	(a) cost.Same > 0 AND 玩家持有 ≥2 种 specific element (不算 Omni) 且每种 ≥ Same 量
//	    → 玩家可选用哪种 specific 付,留另一种给后续高 cost 卡
//	(b) cost.Any > 0 AND 玩家持有 specific element 总和 > Any 且 Omni > 0
//	    → 玩家可选 Omni 付 vs specific 付 (留 Omni 给后续 same cost 用)
//	(c) cost.Specific[color] > 0 AND 玩家持有 Omni > 0 且 specific[color] < required
//	    → 玩家可选用 Omni 替代 (多数自动:specific 不够时必须用 Omni; 少数 strategic)
//
// 否则 auto-resolve (greedy 字典序最小)。
func IsCostMeaningful(cost CostSpec, pool DicePool) bool {
	// case (a): same cost + 多种 specific dice 满足
	if cost.Same > 0 {
		matchingKinds := 0
		for color := DiceFire; color < DiceOmni; color++ {
			if pool[color] >= cost.Same {
				matchingKinds++
			}
		}
		// Omni 也算 (Omni 可作 same)
		if pool[DiceOmni] >= cost.Same {
			matchingKinds++
		}
		if matchingKinds >= 2 {
			return true
		}
	}

	// case (b): any cost + Omni 可选 vs specific 可选
	if cost.Any > 0 && pool[DiceOmni] > 0 {
		specificTotal := 0
		for color := DiceFire; color < DiceOmni; color++ {
			specificTotal += pool[color]
		}
		if specificTotal >= cost.Any {
			// 玩家可选: 用 Omni 还是用 specific 付 Any
			return true
		}
	}

	// case (c): specific cost + Omni 可替代 (这里只在 specific 充足且 Omni 也充足时才 strategic)
	for color := DiceFire; color < DiceOmni; color++ {
		need := cost.Specific[color]
		if need > 0 && pool[color] >= need && pool[DiceOmni] > 0 {
			// specific 够付 + Omni 也可付 → 玩家可选保留 specific
			return true
		}
	}

	return false
}

// AutoResolveCost — engine 自动选合法 dice 子集 (字典序最小)。
// 返回扣除的 dice (DicePool 形式)。
// 算法 O(N):
//  1. 优先用 specific element (按 color 字典序: Fire > Ice > Water > ... > Dendro)
//  2. specific 不够用 Omni 补
//  3. Same: 用 dice 数最多的 specific element 付; 不够用 Omni 补
//  4. Any: 用 Omni 优先,specific 按字典序补
func AutoResolveCost(cost CostSpec, pool DicePool) (DicePool, bool) {
	consumed := DicePool{}
	remaining := pool

	// step 1: specific cost
	for color := DiceFire; color < DiceOmni; color++ {
		need := cost.Specific[color]
		if need == 0 {
			continue
		}
		take := min(remaining[color], need)
		consumed[color] += take
		remaining[color] -= take
		need -= take
		// specific 不够,用 Omni 补
		if need > 0 {
			take2 := min(remaining[DiceOmni], need)
			consumed[DiceOmni] += take2
			remaining[DiceOmni] -= take2
			need -= take2
		}
		if need > 0 {
			return DicePool{}, false // 付不起
		}
	}

	// step 2: same cost — 选 dice 数最多的 specific element (auto)
	if cost.Same > 0 {
		bestColor := DiceColor(-1)
		bestCount := 0
		for color := DiceFire; color < DiceOmni; color++ {
			if remaining[color] > bestCount {
				bestCount = remaining[color]
				bestColor = color
			}
		}
		need := cost.Same
		if bestColor >= 0 {
			take := min(remaining[bestColor], need)
			consumed[bestColor] += take
			remaining[bestColor] -= take
			need -= take
		}
		if need > 0 {
			take2 := min(remaining[DiceOmni], need)
			consumed[DiceOmni] += take2
			remaining[DiceOmni] -= take2
			need -= take2
		}
		if need > 0 {
			return DicePool{}, false
		}
	}

	// step 3: any cost — Omni 优先,specific 按字典序补
	if cost.Any > 0 {
		need := cost.Any
		take := min(remaining[DiceOmni], need)
		consumed[DiceOmni] += take
		remaining[DiceOmni] -= take
		need -= take
		for color := DiceFire; color < DiceOmni && need > 0; color++ {
			t := min(remaining[color], need)
			consumed[color] += t
			remaining[color] -= t
			need -= t
		}
		if need > 0 {
			return DicePool{}, false
		}
	}

	return consumed, true
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// CostPaymentDecision — A24 入口。
// 返回 (auto_consumed, needs_substate)。
// auto_consumed != nil: engine 自动扣除,RL 视角跳过 cost step。
// needs_substate=true: engine enter cost_payment substate,RL 选哪种支付。
func CostPaymentDecision(cost CostSpec, pool DicePool) (consumed DicePool, needsSubstate bool, ok bool) {
	if IsCostMeaningful(cost, pool) {
		return DicePool{}, true, true
	}
	c, ok := AutoResolveCost(cost, pool)
	return c, false, ok
}
