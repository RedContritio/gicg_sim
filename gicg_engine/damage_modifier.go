package engine

// ADR-0019 §B.2 — typed Modifier list with element dimension。
//
// damage 管线每 fire hook 阶段引擎自动 record (ValueBefore, ElementBefore)
// → fire → 比较 → append Modifier 到 per-DealDamage call 的 DamageModifierLog。
// 嵌套 damage call (反击 / 反应子伤害 / 扩散一对多) 各自独立 log,
// 不合并,通过 g.damageLogStack push/pop 管理嵌套语义。
//
// 不进 EventContext (二轮评审 P1-6: 避免 union 污染);DSL 通过 future
// `ctx.modifiers` proxy(§B.3 / §B.5)读 game-level g.CurrentDamageLog()
// 反查;本 §B.2 仅落地数据结构 + 自动 record,obs encoder + DSL read 在
// 后续步骤补。

// ModifierKind — damage 流水线 stage-level 标签。
//
// 当前 §B.2 仅 record stage-level (一个 ModBoost 合并 Type/Add/Mul 三个 hook,
// 一个 ModReduce 合并 ReduceBuff/Shield/Immunity 三个 hook);per-hook 细分
// 留后续 obs 改造时实施。strict §B.5 已删旧 HookDamageBoost/Reduce 但 stage
// 分组语义保留,故 ModBoost/ModReduce 名称仍指 stage 整体。
type ModifierKind int

const (
	ModBoost       ModifierKind = iota // ① 增伤 stage(Type+Add+Mul 合并 record)
	ModReaction                        // ② 反应 stage(反应附加 +N / element None 转换)
	ModReduce                          // ③ 减伤 stage(ReduceBuff+Shield+Immunity 合并 record)
	ModAfterDamage                     // ⑤ AfterDamage stage(占位,通常不改 ctx)
)

// Modifier — 单 stage 的修饰记录。
//
// ValueBefore / ValueAfter: ctx.Value 进入 / 退出 stage 的差。
// ElementBefore / ElementAfter: ctx.Element 进入 / 退出 stage 的变化(蝶火附魔 /
// 反应消耗后 element 转 None 等)。
type Modifier struct {
	Kind          ModifierKind
	ValueBefore   int
	ValueAfter    int
	ElementBefore Element
	ElementAfter  Element
}

// DamageModifierLog — per-DealDamage call 的 modifier 序列。
//
// 嵌套 damage call (反击 / 反应子伤害 / 扩散一对多) 各自独立 DamageModifierLog,
// 通过 g.damageLogStack 栈管理。
type DamageModifierLog struct {
	Modifiers []Modifier
}

// pushDamageLog — DealDamage 入口调,push 新 log 到栈顶。
func (g *Game) pushDamageLog() *DamageModifierLog {
	log := &DamageModifierLog{}
	g.damageLogStack = append(g.damageLogStack, log)
	return log
}

// popDamageLog — DealDamage defer 调,pop 栈顶 log。
func (g *Game) popDamageLog() {
	n := len(g.damageLogStack)
	if n == 0 {
		return
	}
	g.damageLogStack = g.damageLogStack[:n-1]
}

// CurrentDamageLog — exposed for obs encoder + DSL proxy。栈空(非 damage
// 上下文)时返 nil。
func (g *Game) CurrentDamageLog() *DamageModifierLog {
	n := len(g.damageLogStack)
	if n == 0 {
		return nil
	}
	return g.damageLogStack[n-1]
}

// recordStageModifier — damage.go 4 fire 点调,在 fire 前后比较 ctx 字段
// 自动 append modifier 到当前 log。kind 由 caller 传(对应 stage)。
//
// ValueBefore == ValueAfter && ElementBefore == ElementAfter 时仍 record
// (RL 看到 "stage X 触发了但无 effect" 也是有效信号 — 跟 "stage X 完全
// 没 fire" 不同语义)。
func (g *Game) recordStageModifier(kind ModifierKind, valueBefore int, elemBefore Element, ctx *EventContext) {
	log := g.CurrentDamageLog()
	if log == nil {
		return // 非 damage 上下文,silent skip
	}
	log.Modifiers = append(log.Modifiers, Modifier{
		Kind:          kind,
		ValueBefore:   valueBefore,
		ValueAfter:    ctx.Value,
		ElementBefore: elemBefore,
		ElementAfter:  ctx.Element,
	})
}
