package interp

// ADR-0019 §A.2 — find_char_by_kind builtin (enum-based)。
//
// dsl_gaps.md §H Target 扩展 ★★ — 万众瞩目 / 追踪爆弹 / 部分召唤物 等
// 卡牌需要"按某条件挑角色"。closure spike(2026-05-04)证伪 lua DSL 不
// 支持 first-class function return value,改 enum-based 路线:用 CharKind
// 枚举预定义谓词集 + builtin 内部实现。
//
// 签名: find_char_by_kind(player, kind) -> int(char_idx;-1 表无)
// player: 0/1 玩家 idx 或 Player.Own/Enemy(走 ResolvePlayer)
// kind: CharKind 枚举值(0-4),见 builtins_enums.go 注册
//
// Tie-breaking: 同分情况按 char_idx 升序取第一个(deterministic)。

const (
	CharKindLowestHp        = 0
	CharKindHighestHp       = 1
	CharKindLeastDamaged    = 2 // (Init - Value) 最小,即受伤最少
	CharKindRandomNonActive = 3 // 随机非出战活角色,用 g.Rng
	CharKindPreviousActive  = 4 // ADR-0019 §A.2 future: v1 没存 prev active char,fallback 到 active
)

func (rt *Runtime) builtinFindCharByKind(args []Value) (Value, error) {
	pVal, _ := ToInt(args[0])
	kind, _ := ToInt(args[1])
	g := rt.Game

	rp := rt.ResolvePlayer(pVal)
	if rp < 0 || rp > 1 {
		return -1, nil
	}

	// Collect alive char idxs with HP counter ID.
	type aliveChar struct {
		charIdx int
		hpID    int
	}
	var alive []aliveChar
	for c, entry := range rt.Chars.BySlot[rp] {
		if entry == nil {
			continue
		}
		if c >= len(g.Players[rp].Chars) || !g.Players[rp].Chars[c].Alive {
			continue
		}
		if entry.HPCounterID < 0 {
			continue
		}
		alive = append(alive, aliveChar{c, entry.HPCounterID})
	}
	if len(alive) == 0 {
		return -1, nil
	}

	switch kind {
	case CharKindLowestHp:
		bestIdx := alive[0].charIdx
		bestVal := g.Counters[alive[0].hpID].Value
		for _, a := range alive[1:] {
			v := g.Counters[a.hpID].Value
			if v < bestVal {
				bestVal = v
				bestIdx = a.charIdx
			}
		}
		return bestIdx, nil

	case CharKindHighestHp:
		bestIdx := alive[0].charIdx
		bestVal := g.Counters[alive[0].hpID].Value
		for _, a := range alive[1:] {
			v := g.Counters[a.hpID].Value
			if v > bestVal {
				bestVal = v
				bestIdx = a.charIdx
			}
		}
		return bestIdx, nil

	case CharKindLeastDamaged:
		// damaged = Init - Value; 求 min damaged
		bestIdx := alive[0].charIdx
		c0 := g.Counters[alive[0].hpID]
		bestDmg := c0.Init - c0.Value
		for _, a := range alive[1:] {
			c := g.Counters[a.hpID]
			d := c.Init - c.Value
			if d < bestDmg {
				bestDmg = d
				bestIdx = a.charIdx
			}
		}
		return bestIdx, nil

	case CharKindRandomNonActive:
		active := g.Players[rp].ActiveChar
		var nonActive []int
		for _, a := range alive {
			if a.charIdx != active {
				nonActive = append(nonActive, a.charIdx)
			}
		}
		if len(nonActive) == 0 {
			return -1, nil
		}
		if g.Rng != nil {
			return nonActive[g.Rng.Intn(len(nonActive))], nil
		}
		return nonActive[0], nil

	case CharKindPreviousActive:
		// Future Considerations: v1 没存 prev active char,fallback 到当前 active
		// (DSL 作者懂这是 not-implemented placeholder,触发条件极少:追踪爆弹类)。
		return g.Players[rp].ActiveChar, nil
	}
	return -1, nil
}
