package engine

type Op int

const (
	OpSet Op = iota
	OpAdd
	OpSub
)

type Element int

const (
	ElemNone Element = iota
	ElemFire
	ElemIce
	ElemWater
	ElemElectro
	ElemGeo
	ElemAnemo
	ElemDendro
	ElemPhysical
	// ElemPiercing — ADR-0019 §B.1: 穿透伤害是基础类型(无视护盾和减伤的物理伤害),
	// 不是 modifier flag。replace 旧 EventContext.Penetrate / DamageOpts.Penetrate。
	// 不附着不反应,damage 管线跳过 reaction + reduce 阶段直接扣 HP。
	ElemPiercing
)

// IsPiercing — 穿透伤害判定。damage 管线在 reaction / reduce 阶段判跳过。
func (e Element) IsPiercing() bool { return e == ElemPiercing }

// IsPhysical — 物理(不附着不反应)。
func (e Element) IsPhysical() bool { return e == ElemPhysical }

// IsElemental — 7 元素(火/冰/水/雷/岩/风/草),可附着 / 触发反应。
func (e Element) IsElemental() bool { return e >= ElemFire && e <= ElemDendro }

// DiceColor indexes the dice counter table. The 7 real elements
// (Fire..Dendro) plus Omni make 8 dice types. DiceColor values map
// 1:1 to the position in Ruleset.DiceCounterIDs[player].
const (
	DiceColorFire    = 0
	DiceColorIce     = 1
	DiceColorWater   = 2
	DiceColorElectro = 3
	DiceColorGeo     = 4
	DiceColorAnemo   = 5
	DiceColorDendro  = 6
	DiceColorOmni    = 7
	DiceColorCount   = 8
)

// ElementToDiceColor returns the DiceColor index for a given game
// element, or -1 if the element has no corresponding dice color
// (ElemNone, ElemPhysical).
func ElementToDiceColor(e Element) int {
	switch e {
	case ElemFire:
		return DiceColorFire
	case ElemIce:
		return DiceColorIce
	case ElemWater:
		return DiceColorWater
	case ElemElectro:
		return DiceColorElectro
	case ElemGeo:
		return DiceColorGeo
	case ElemAnemo:
		return DiceColorAnemo
	case ElemDendro:
		return DiceColorDendro
	}
	return -1
}

type ActionContext int

const (
	ActNone ActionContext = iota
	ActUseSkill
	ActPlayCard
	ActSwitch
	ActEndTurn
	ActForcedDeath
	ActForcedReaction
)

type Source int

const (
	SrcNone Source = iota
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

	// 伤害管道 — ADR-0019 §B.5 strict 8 时机:
	//   HookDamageType → HookDamageAdd → HookDamageMul → HookReactionDamage →
	//   HookDamageReduceBuff → HookShieldAbsorb → HookDamageImmunity → 扣血 →
	//   HookAfterDamage
	HookDamageType       // ①a 元素修改(物理→火附魔等)
	HookDamageAdd        // ①b 加法增伤(班尼特 +2)
	HookDamageMul        // ①c 乘法增伤(future-proof)
	HookReactionDamage   // ② 元素反应
	HookDamageReduceBuff // ③a 减伤 buff(物理半伤等)
	HookShieldAbsorb     // ③b 护盾消耗
	HookDamageImmunity   // ③c 免疫(kill all)
	HookAfterDamage      // ④ 始终触发

	// 治疗管道
	HookBeforeHeal // 治疗前，可修改 value
	HookAfterHeal  // 治疗后

	// 能量管道
	HookBeforeEnergyGain
	HookAfterEnergyGain
	HookBeforeEnergyConsume
	HookAfterEnergyConsume

	// 动作系统
	HookActionCheck    // 动作可用性检查（ctx.Playable 默认 true）
	HookActionPrepare  // 动作预处理（可通过 cost_mod 修改 Cost；设置 EnergyCost/BattleAction/TargetMode）
	HookSkillUse       // 技能效果
	HookCardPlay       // 卡牌效果
	HookSwitch         // 切换角色事件
	HookBeforeTurnFlip // 行动权翻转前（可修改 BattleAction）
	HookOnTune         // 调和(Tune)— ADR-0019 §A.4 / dsl_gaps D3,卡作元素调和使用时

	// 回合阶段
	HookRoundStart
	HookRoundEnd
	HookRoundEndPostSummon
	HookRoundEndDecay
	HookRoundEndFinal

	// 生命周期（由 alive counter 0↔1 跃迁驱动）
	HookDeath  // alive: 1 → 0
	HookRevive // alive: 0 → 1（包括初始登场）

	// 支援区生命周期
	HookSupportRemove // 支援卡从 PlayerState.Supports 移除时；ctx.ActorPlayer + ctx.CardRef

	// 通用
	HookAction // 任意动作兜底
)

// 同类型 hook 按注册顺序执行，无 priority 机制。
// 加载顺序（system/ → characters/ → cards/）保证系统 hook 先于用户 hook。

type Phase int

const (
	PhaseNotStarted   Phase = iota
	PhaseSelectActive       // 首回合选择出战角色
	PhaseRoundStart
	PhaseAction
	PhaseRoundEnd
	PhaseGameOver
)

type ActionKind int

const (
	ActionSkill ActionKind = iota
	ActionCard
	ActionSwitch
	ActionEndTurn
	ActionTune // 消耗 1 手牌 + 转换 1 非本色非 omni 骰子 → 本色
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
