package engine

// EventContext 是 hook 回调的上下文。不同 HookType 使用不同字段子集。
type EventContext struct {
	AttachmentOnly bool   // pure element application; never a damage attempt
	WriteBuffID    uint64 // lifecycle of the counter instance being written
	// 事件分类
	ActionCtx ActionContext
	Source    Source

	// 写入钩子字段
	CounterID int
	Op        Op
	Before    int // 写入前的值（FireBeforeWrite/FireAfterWrite 均可读）
	After     int // 写入后的值（仅 FireAfterWrite 可读；before 时未定义）

	// 通用可修改值
	Value int // 伤害量 / 写入量

	// 伤害事件字段
	// 注: Element.IsPiercing() 替代旧 Penetrate flag (ADR-0019 §B.1)
	Element Element

	// 动作信息
	ActorPlayer int
	ActorChar   int
	SkillIndex  int
	CardRef     int
	ActionKind  ActionKind // HookActionCheck/Prepare 用：候选动作类型
	HandIndex   int        // HookActionCheck 用：手牌索引
	SwitchChar  int        // HookActionCheck 用：切换目标角色索引

	// Cost is the mutable effective dice cost of the candidate action
	// currently being enumerated (or restored for the chosen action at
	// execution time). Initialized by GetLegalActions to the declared
	// cost before HookActionPrepare fires. DSL hooks mutate via the
	// cost_mod builtin. Clamped and passed to EnumerateCostPayments
	// after all prepare hooks return.
	//
	// Per-candidate lifecycle: the value is reset at the start of each
	// candidate iteration, so mutations never leak between candidates.
	Cost DiceCost

	// AppliedMods is the set of prepare-phase hook IDs whose cost_mod
	// call actually executed for this candidate. Populated by the
	// cost_mod builtin using CurrentHookID. Baked into the chosen
	// Action's AppliedMods at enumeration, restored at execution so
	// consumer hooks can call was_applied(ctx, prepare_id) to decide
	// whether to consume their charge.
	AppliedMods map[int]bool

	// CurrentHookID is set by FireEventHooks / FirePerPlayerHooks to
	// the ID of the hook currently executing. Used by the cost_mod
	// builtin to auto-tag AppliedMods with the calling hook's identity.
	// Reset to -1 outside a hook body.
	CurrentHookID int
	BuffID        uint64

	EnergyCost   int
	BattleAction bool
	NeedTarget   bool // ActionPrepare 中设置，卡牌需要选择目标
	TargetMode   int  // 1=own_char, 2=enemy_char

	// 可用性
	Playable bool // HookActionCheck：默认 true，hook 置 false 阻止

	// 目标信息
	TargetPlayer int
	TargetChar   int
	TargetBuffID uint64 // internal selected instance, distinct from the executing BuffID

	// 控制
	Cancelled    bool // on_before_write 中调用 cancel() 置 true
	SkipReaction bool // on_before_damage 中置 true，跳过元素反应步骤
	Hit          bool // 伤害管道 ④ 实际扣减 HP 后置 true；on_after_damage 可读
	Paid         bool // invoke_skill: 费用已付，skill_use 跳过 AP/能量扣除

	// SkipSkillHooks: invoke_skill_silent 设置,FireEventHooks(HookSkillUse)
	// 不 dispatch DSL 注册的 on_skill_use(只跑 engine canonical hook —
	// 能量增减 / dice 等)。用于 prepare-skill 准备完成的自动触发,以及
	// 特技使用("不视为使用技能")。见 ADR-0012。
	SkipSkillHooks bool
	// IsSpecialty: 当前 frame 是特技调用。下游 hook(伤害管道 / 统计)
	// 可 ``if ctx.IsSpecialty then return end`` 跳过;特技伤害"不视为
	// 角色造成的伤害"由各 hook DSL 文件自行 filter。spike 阶段先加
	// 字段未必所有路径都用上,见 ADR-0012。
	IsSpecialty bool

	// ReactionKind: ADR-0019 §B.3 — DSL declare_reaction("X") 注册得到
	// ID 后,reaction.lua 在反应触发分支调 set_reaction_kind(R_X) 写入
	// 此字段;reset on 每 DealDamage 入口。obs encoder 编码到 typed slot。
	// 0 = no reaction(默认 Reaction.None);> 0 = registered reaction ID。
	// 支持新增反应:任何 DSL 文件 declare_reaction 即可,engine 0 hardcode
	// 反应名(register 是 runtime allocation,跟 declare_counter 同模式)。
	ReactionKind    int
	ReactionElement Element // secondary element selected by DSL reaction rules

	// Absorbed: ADR-0019 §B.5 — damage 管线 reduce 阶段后被护盾/减伤吸收的量
	// (preShieldValue - ctx.Value 之差,单 damage 累计)。on_after_damage hook
	// 可读 ctx.absorbed 实现以逸待劳类反击 idiom(strict 8 hook 流水线没有
	// 旧 priority bracket 写法,反击改读此字段)。
	Absorbed int
}
