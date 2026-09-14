package engine

// player.go — PlayerState 与其直接依赖的 small struct(CardInst /
// PendingCard / SupportInst + MaxSupportSlots)。从 game.go 拆出
// 让 game.go 控制在 300 行 hook limit 内。

// CardInst 引擎只知道卡牌的身份标识 + 该卡进入手牌时的回合号。
// DrawnAtRound 用于 reward shaping 的"持有时间衰减"——每张卡进入 hand
// 时刷新为当前 g.Round；BuildDeck/add_card 等创建路径在调用点设。
type CardInst struct {
	Ref          int
	DrawnAtRound int
}

// SupportInst tracks one card occupying a player's support zone
// (PlayerState.Supports). Pushed on card_play by the priority 2000 hook
// in interp/builtins_card.go (Slot.Support 分支). Removed via DSL
// builtin remove_support(p, ref) which also appends the card_ref into
// Discard and fires HookSupportRemove.
type SupportInst struct {
	ID          uint64 // internal lifecycle identity, stable through payment and clone
	Ref         int    // card_ref
	ActivatedAt int    // game.Round when entered
	BuffID      uint64 // associated independent effect; internal lifecycle identity
}

// MaxSupportSlots — GICG canonical 4-slot support zone cap. Enforced at
// on_action_check (interp/builtins_card.go); 5th support card →
// ctx.Playable = false.
const MaxSupportSlots = 4

type PlayerState struct {
	Chars       []CharInfo
	ActiveChar  int
	Hand        []CardInst
	Deck        []CardInst
	Discard     []CardInst
	Supports    []SupportInst // 支援区(len ≤ MaxSupportSlots)
	InitDeck    []CardInst    // Reset() 时恢复
	DeclaredEnd bool
}
