package engine

type EventFrame struct {
	BuffID           uint64
	BuffCounterID    int
	ActionCtx        ActionContext
	Source           Source
	Player           int
	Char             int
	SkillIndex       int // set when source is a skill
	CardRef          int // set when source is a card
	HasCardTarget    bool
	CardTargetPlayer int
	CardTargetChar   int
}

type deferredEntry struct {
	Frame     EventFrame
	Fn        func(g *Game) // 自动执行
	Action    *Action       // 需要玩家输入（Fn 为 nil 时使用）
	NeedInput bool
}

type eventLayer struct {
	Current  EventFrame
	Deferred []deferredEntry
}
