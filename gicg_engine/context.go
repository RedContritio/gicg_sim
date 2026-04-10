package engine

// EventContext 是 hook 回调的上下文。不同 HookType 使用不同字段子集。
type EventContext struct {
	// 事件分类
	ActionCtx ActionContext
	Source    Source

	// 写入钩子字段
	CounterID int
	Op        Op

	// 通用可修改值
	Value int // 伤害量 / 写入量

	// 伤害事件字段
	Element   Element
	Penetrate bool

	// 动作信息
	ActorPlayer int
	ActorChar   int
	SkillIndex  int
	CardRef     int
	ActionKind  ActionKind // HookActionCheck/Prepare 用：候选动作类型
	HandIndex   int        // HookActionCheck 用：手牌索引
	SwitchChar  int        // HookActionCheck 用：切换目标角色索引

	APCost       int
	EnergyCost   int
	BattleAction bool
	NeedTarget   bool // ActionPrepare 中设置，卡牌需要选择目标
	TargetMode   int  // 1=own_char, 2=enemy_char

	// 可用性
	Playable bool // HookActionCheck：默认 true，hook 置 false 阻止

	// 目标信息
	TargetPlayer int
	TargetChar   int

	// 控制
	Cancelled    bool // on_before_write 中调用 cancel() 置 true
	SkipReaction bool // on_before_damage 中置 true，跳过元素反应步骤
	Hit          bool // 伤害管道 ④ 实际扣减 HP 后置 true；on_after_damage 可读
	Paid         bool // invoke_skill: 费用已付，skill_use 跳过 AP/能量扣除
}
