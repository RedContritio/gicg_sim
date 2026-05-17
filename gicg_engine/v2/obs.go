package enginev2

// A28 — Hierarchical obs encoding (typed schema, Go side)。
//
// EncodeObs(g, player) 返回 typed ObsSnapshot — 给 player 视角 (按 hidden_from masked)。
// Python 侧 (后续 migration) 接 typed snapshot tensorize。
//
// 设计原则:
// - typed (no map[string]any): 跟 v2 prototype 一致, RL 可 fixed-slot encode
// - masked: 按 owner / HiddenFrom 决定 player 视角下 visible
// - L3 obs: 全 LastTransitions 都 public (typed transition log, RL 可推理因果)
// - PDR exposed: 若 sync hold, DecisionSpec 直接进 obs 让 RL 选
//
// "RL 可观测全部规则"含义:
// - state (Scalars/Collections, masked): RL 直接看
// - rule semantics (hook 行为): rule declared in DSL, 由 (state input, hook) → state output
//   confirms causally; RL 通过 LastTransitions 看到每步的 (Element/TriggerSource/Actor/Value)
//   因果, 加 next-state 推理 hook 行为
// - PDR decisions: DecisionSpec typed → RL 看到合法 options
// 整体: state + transitions + decision space 三者 typed 完整 → RL 可学到所有规则。

// ===== Typed Obs snapshot =====

// ObsSnapshot — RL agent 在某 game step 看到的 typed 完整 obs (player p 视角)。
type ObsSnapshot struct {
	// 全局 game-level meta
	Round        int
	Turn         int
	Phase        GamePhase
	Winner       int
	StepID       int
	ViewerPlayer int // 此 obs 是给哪个 player 的

	// 按 owner 分组的 scalars (含 mask)
	ScalarsSelf   []ScalarObs
	ScalarsEnemy  []ScalarObs
	ScalarsShared []ScalarObs // SystemOwner 容器

	// 按 owner 分组的 collections (含 mask)
	CollectionsSelf   []CollectionObs
	CollectionsEnemy  []CollectionObs
	CollectionsShared []CollectionObs

	// L3 obs: typed transition log (全 public, bounded MaxLastTransitions)
	LastTransitions []TransitionEntry

	// PDR sync hold (若当前 game step 在 PDR 中, RL agent 必读)
	PendingDecision *DecisionSpec
}

// ScalarObs — Scalar 在 obs 里的 typed view。
type ScalarObs struct {
	Name      string
	Value     int // 若 Visible=false, 此值为 0 (sentinel)
	Min, Max  int
	Tag       int
	Owner     Owner
	Visible   bool // 若 false, RL 只知容器存在,不知 Value
	Destroyed bool // A16 tombstone
}

// CollectionObs — Collection 在 obs 里的 typed view。
type CollectionObs struct {
	Name      string
	Owner     Owner
	Size      int       // 始终公开 (即便内容 hidden, 数量是公开信息)
	Visible   bool      // 若 false, Items 为 nil (只知 size)
	Items     []ItemObs // 仅 Visible=true 时填
	Destroyed bool
}

// ItemObs — Collection item 在 obs 里的 typed view (sum over Card/Summon/SkillRef)。
type ItemObs struct {
	Kind ItemKind

	// typed sum (互斥按 Kind)
	Card   *CardObs
	Summon *SummonObs
	Skill  *SkillObs
}

type CardObs struct {
	Ref       int
	CostTotal int
	Kind      CardKind
}

type SummonObs struct {
	Ref     int
	Owner   Owner
	Hp      int
	Usage   int
	Element ElementType
}

type SkillObs struct {
	Ref     int
	Owner   Owner
	Element ElementType
	// CostSpec 暴露(玩家可看 skill 的 cost)
	Cost *CostSpec
}

// ===== Encoder =====

// EncodeObs — 从 Game state + 当前 PDR hold (若有) 生成 player p 视角的 typed obs snapshot。
//
// Held: 调用方传入当前 HeldCtx (若 game 在 PDR sync hold), nil 表正常 step。
func EncodeObs(g *Game, viewerPlayer int, held *HeldCtx) *ObsSnapshot {
	obs := &ObsSnapshot{
		Round:        g.Round,
		Turn:         g.Turn,
		Phase:        g.Phase,
		Winner:       g.Winner,
		StepID:       g.NextStepID,
		ViewerPlayer: viewerPlayer,
	}

	// Scalars
	for _, s := range g.Scalars {
		so := encodeScalar(s, viewerPlayer)
		switch {
		case s.Owner.Player == viewerPlayer:
			obs.ScalarsSelf = append(obs.ScalarsSelf, so)
		case s.Owner.Player == -1:
			obs.ScalarsShared = append(obs.ScalarsShared, so)
		default:
			obs.ScalarsEnemy = append(obs.ScalarsEnemy, so)
		}
	}

	// Collections
	for _, c := range g.Collections {
		co := encodeCollection(c, viewerPlayer)
		switch {
		case c.Owner.Player == viewerPlayer:
			obs.CollectionsSelf = append(obs.CollectionsSelf, co)
		case c.Owner.Player == -1:
			obs.CollectionsShared = append(obs.CollectionsShared, co)
		default:
			obs.CollectionsEnemy = append(obs.CollectionsEnemy, co)
		}
	}

	// L3 transitions (全 public, deep copy 避免后续 mutation 污染 obs)
	if len(g.LastTransitions) > 0 {
		obs.LastTransitions = make([]TransitionEntry, len(g.LastTransitions))
		copy(obs.LastTransitions, g.LastTransitions)
	}

	// PDR sync hold 暴露
	if held != nil {
		obs.PendingDecision = held.DecisionSpec
	}

	return obs
}

func encodeScalar(s *Scalar, viewerPlayer int) ScalarObs {
	visible := s.IsVisibleTo(viewerPlayer)
	value := 0
	if visible {
		value = s.Value
	}
	return ScalarObs{
		Name:      s.Name,
		Value:     value,
		Min:       s.Min,
		Max:       s.Max,
		Tag:       s.Tag,
		Owner:     s.Owner,
		Visible:   visible,
		Destroyed: s.Destroyed,
	}
}

func encodeCollection(c *Collection, viewerPlayer int) CollectionObs {
	visible := c.IsVisibleTo(viewerPlayer)
	co := CollectionObs{
		Name:      c.Name,
		Owner:     c.Owner,
		Size:      len(c.Items),
		Visible:   visible,
		Destroyed: c.Destroyed,
	}
	if visible {
		co.Items = make([]ItemObs, len(c.Items))
		for i, it := range c.Items {
			co.Items[i] = encodeItem(it)
		}
	}
	return co
}

func encodeItem(it Item) ItemObs {
	switch v := it.(type) {
	case *CardRef:
		return ItemObs{Kind: ItemKindCard, Card: &CardObs{
			Ref: v.Ref, CostTotal: v.CostTotal, Kind: v.Kind,
		}}
	case *SummonRef:
		return ItemObs{Kind: ItemKindSummon, Summon: &SummonObs{
			Ref: v.Ref, Owner: v.Owner, Hp: v.Hp, Usage: v.Usage, Element: v.Element,
		}}
	case *SkillRef:
		return ItemObs{Kind: ItemKindSkillRef, Skill: &SkillObs{
			Ref: v.Ref, Owner: v.Owner, Element: v.Element, Cost: v.Cost,
		}}
	}
	panic("encodeItem: unknown Item type")
}
