package engine

// SkillIdentityResolver — ADR-0019 §B.3c obs encoder 反查接口。
// interp.Runtime 实现此接口;Game.Extra (any) 类型断言为此接口,
// 避免 engine package 循环 import interp。
type SkillIdentityResolver interface {
	SkillIdentityOf(playerIdx, skillID int) (charIdx, slot int, ok bool)
}

// ADR-0019 §B.3 — Recent damage event ring buffer。
//
// 每次 DealDamage 完成 (HookAfterDamage 之后) emit 一个 typed
// RecentDamageEvent 到 ring (bounded K=8,超出 drop oldest)。obs encoder
// 编码 ring 给 RL,使其唯一推理"刚发生的伤害事件"因果(P0-3 修复:
// reaction kind / shield absorbed / element transition / modifier source
// 全 typed 进 obs)。
//
// K=8 起步 (一轮评审 P1-1 上调,覆盖超导/感电/扩散一对多 multi-target);
// dynamic refine 待 §B.3 obs encoder 落地后跑 replay log 实证 (§B.0 工具
// 静态实证 P99=14/MAX=17 是整卡 effect 累加, 不等同单 damage 频次)。

const MaxRecentDamageEvents = 8

// RecentDamageEvent — 单 DealDamage call 的 typed snapshot。
type RecentDamageEvent struct {
	// 玩家/角色信息(actor / target)
	ActorPlayer  int
	ActorChar    int
	TargetPlayer int
	TargetChar   int

	// 伤害类型 + 数值
	Element    Element
	RawValue   int // pre-shield, pre-reaction (ctx.Value 进入 reduce stage 前)
	FinalValue int // 实际扣 HP 量
	Absorbed   int // RawValue - FinalValue (护盾吸收 + 减伤合计)
	IsPiercing bool
	IsHit      bool // ctx.Hit (实际命中 vs cancelled / immunity)

	// ADR-0019 §B.3 typed signals
	ReactionKind int // 0 = ReactionNone; > 0 = registered reaction ID

	// Modifier list snapshot (deep copy from per-call DamageModifierLog)
	Modifiers []Modifier
}

// PushRecentDamageEvent — DealDamage 出口调,append event 到 ring;
// 超 MaxRecentDamageEvents 时 drop oldest。
func (g *Game) PushRecentDamageEvent(e RecentDamageEvent) {
	g.RecentDamageEvents = append(g.RecentDamageEvents, e)
	if len(g.RecentDamageEvents) > MaxRecentDamageEvents {
		g.RecentDamageEvents = g.RecentDamageEvents[1:]
	}
}

// ResetRecentDamageEvents — 每 game step 边界 / Reset 时调,清空 ring。
// (per-step 滑动窗口 vs 跨 step 累积是 design choice;当前选每 step 滑动
// 而非清空,跨 step ring 仍保留;若需要 step-clear,obs encoder 自己 clear。)
func (g *Game) ResetRecentDamageEvents() {
	g.RecentDamageEvents = nil
}
