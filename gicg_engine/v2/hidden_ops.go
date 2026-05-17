package enginev2

// A14 + A19 — Hidden 容器 server-side resolve + closure plain-data view。
//
// 致命 review #5: closure 接受任意 user fn 作为 sort key → closure 内 capture
// 外部 mutable ref → community card 注入 sniff closure 直接 dump 对手手牌。
//
// 解 (本 prototype): closure 限 **plain_key_fn 内置枚举** (engine 提供的固定 sort key 集合),
// user 不能写任意 closure。如果需要 composite,提供 composite_key_fn builder。
//
// 同时 A14 ownership-bound hidden_from: owner 变 → mask 自动翻 (例 swap_hands 后,
// 原 owner 看不见,新 owner 看得见)。

// PlainKeyFn — 内置 sort key 枚举 (A19)。
// item 是 typed Item interface,extractKey 按 ItemKind() typed dispatch 取 field。
// user 不能 capture 外部 ref (typed dispatch + concrete struct field 而非 closure)。
type PlainKeyFn int

const (
	KeyCostTotal PlainKeyFn = iota // CardRef.CostTotal
	KeyCardID                      // CardRef.Ref
	KeyHpAsc                       // SummonRef.Hp
	KeyHpDesc                      // -SummonRef.Hp
)

// extractKey — 从 typed Item 按 PlainKeyFn 取 int 值,server-side 内部用。
// 不匹配的 (Item, PlainKeyFn) 组合 panic (内部不变量: caller 必须用对 kfn)。
func extractKey(item Item, kfn PlainKeyFn) int {
	switch kfn {
	case KeyCostTotal:
		c, ok := item.(*CardRef)
		if !ok {
			panic("KeyCostTotal requires *CardRef")
		}
		return c.CostTotal
	case KeyCardID:
		c, ok := item.(*CardRef)
		if !ok {
			panic("KeyCardID requires *CardRef")
		}
		return c.Ref
	case KeyHpAsc:
		s, ok := item.(*SummonRef)
		if !ok {
			panic("KeyHpAsc requires *SummonRef")
		}
		return s.Hp
	case KeyHpDesc:
		s, ok := item.(*SummonRef)
		if !ok {
			panic("KeyHpDesc requires *SummonRef")
		}
		return -s.Hp
	}
	panic("unknown PlainKeyFn")
}

// SelectMax — server-side 在 hidden 容器上 select max by plain_key_fn。
// 返回 item index (DSL 拿到 ref/index 但**不能 inspect 内容**)。
// 跨 IS-MCTS determinize 一致 (deterministic by RNG seed if tie-break needed)。
func (c *Collection) SelectMax(kfn PlainKeyFn) int {
	if len(c.Items) == 0 {
		return -1
	}
	bestIdx := 0
	bestKey := extractKey(c.Items[0], kfn)
	for i := 1; i < len(c.Items); i++ {
		k := extractKey(c.Items[i], kfn)
		if k > bestKey {
			bestKey = k
			bestIdx = i
		}
	}
	return bestIdx
}

// SelectMin — 对偶
func (c *Collection) SelectMin(kfn PlainKeyFn) int {
	if len(c.Items) == 0 {
		return -1
	}
	bestIdx := 0
	bestKey := extractKey(c.Items[0], kfn)
	for i := 1; i < len(c.Items); i++ {
		k := extractKey(c.Items[i], kfn)
		if k < bestKey {
			bestKey = k
			bestIdx = i
		}
	}
	return bestIdx
}

// IsVisibleTo — 容器内容对 player p 是否可见 (A14)。
// 真实场景: obs encoder 给 RL agent 编 obs 时调此判定 mask。
func (c *Collection) IsVisibleTo(player int) bool {
	for _, hp := range c.HiddenFrom {
		if hp == player {
			return false
		}
	}
	return true
}

func (s *Scalar) IsVisibleTo(player int) bool {
	for _, hp := range s.HiddenFrom {
		if hp == player {
			return false
		}
	}
	return true
}

// SwapCollections — 跨方 swap 两个 collection 内容 + ownership-bound mask 自动翻。
// A14 关键设计: hidden_from 由容器持有,但 swap 操作让"对方原 owner"也跟着翻 mask。
//
// 模型: 两个容器各自有 owner。swap 后:
//   - hand_p0 (owner=p0, hidden_from=[p1]) 内容 ↔ hand_p1 (owner=p1, hidden_from=[p0])
//   - 因为 hidden_from 与 owner 自动反转 (owner=p0 时 hidden_from=p1, 反之),
//     swap 后两容器的 owner 不变 → hidden_from 不变 → mask 仍自动正确
//   - 即:容器 owner 永远固定,内容流转,mask 跟容器 owner 走 (不跟内容走)
//
// 这正是 ownership-bound 含义:**容器是 owner 的 view,不是 item 的 view**。
// 沙中遗事"敌方手牌"指的是 hand_enemy 容器,不是某些 card item。
// swap 后 card "原属 p0" 的事实在 game design 上不重要,RL agent 只看自己 hand 容器内容。
func SwapCollections(a, b *Collection) {
	a.Items, b.Items = b.Items, a.Items
}
