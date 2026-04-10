package engine

type Op int

const (
	OpSet Op = iota
	OpAdd
	OpSub
)

type Element int

const (
	ElemNone     Element = iota
	ElemFire
	ElemIce
	ElemWater
	ElemElectro
	ElemGeo
	ElemPhysical
)

type ActionContext int

const (
	ActNone            ActionContext = iota
	ActUseSkill
	ActPlayCard
	ActSwitch
	ActEndTurn
	ActForcedDeath
	ActForcedReaction
)

type Source int

const (
	SrcNone     Source = iota
	SrcSkill
	SrcCard
	SrcStatus
	SrcSummon
	SrcSupport
	SrcReaction
)

type HookType int

const (
	// 写入管道
	HookBeforeWrite HookType = iota
	HookAfterWrite

	// 伤害管道
	HookDamageBoost    // ①：增伤阶段（附魔、加伤），可修改 value/element
	HookReactionDamage // ②：元素反应
	HookDamageReduce   // ③：减伤阶段（护盾吸收），可修改 value
	HookAfterDamage    // ④：始终触发

	// 治疗管道
	HookBeforeHeal // 治疗前，可修改 value
	HookAfterHeal  // 治疗后

	// 能量管道
	HookBeforeEnergyGain
	HookAfterEnergyGain
	HookBeforeEnergyConsume
	HookAfterEnergyConsume

	// 动作系统
	HookActionCheck   // 动作可用性检查（ctx.Playable 默认 true）
	HookActionPrepare // 动作预处理（可修改 APCost/EnergyCost/BattleAction）
	HookSkillUse      // 技能效果
	HookCardPlay      // 卡牌效果
	HookSwitch        // 切换角色事件
	HookBeforeTurnFlip // 行动权翻转前（可修改 BattleAction）

	// 回合阶段
	HookRoundStart
	HookRoundEnd
	HookRoundEndPostSummon
	HookRoundEndDecay
	HookRoundEndFinal

	// 通用
	HookAction // 任意动作兜底
)

// 同类型 hook 按注册顺序执行，无 priority 机制。
// 加载顺序（system/ → characters/ → cards/）保证系统 hook 先于用户 hook。

type Phase int

const (
	PhaseNotStarted    Phase = iota
	PhaseSelectActive        // 首回合选择出战角色
	PhaseRoundStart
	PhaseAction
	PhaseRoundEnd
	PhaseGameOver
)

type ActionKind int

const (
	ActionSkill   ActionKind = iota
	ActionCard
	ActionSwitch
	ActionEndTurn
)

type StepResult int

const (
	StepNeedTarget StepResult = iota
	StepContinue
	StepGameOver
)

// Counter 是纯值容器，所有生命周期逻辑由 DSL hook 管理。
type Counter struct {
	Value int
	Init  int // Game.Reset() 时恢复
	Min   int
	Max   int
}

func (c *Counter) Clamp() {
	if c.Value < c.Min {
		c.Value = c.Min
	}
	if c.Value > c.Max {
		c.Value = c.Max
	}
}
