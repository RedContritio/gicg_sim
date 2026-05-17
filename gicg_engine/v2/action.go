package enginev2

// A5 — Action 层 (三层 pipeline 顶层): 玩家一次操作的入口 dispatch。
// 内部触发多个 SubAction (各自独立 commit + 进 LastTransitions ring)。
// Action-level hook 在 Action 入口 fire (例: 装备 OnPlay 触发某 SubAction)。
//
// 与 SubAction 区别:
// - Action 是玩家选 (play_card / use_skill / switch / end_turn / elemental_tuning)
// - SubAction 是 Action 内子行为 (deal_damage / heal / draw / etc.)
// - Action 各 SubAction 独立 commit (反应链 / 副伤害都是新 SubAction)
//
// prototype 验证: PlayCard Action 入口 → Action-level hook (装备 OnPlay) →
// fire SubActionDealDamage with TriggerSource=TriggerEquipOnPlay。

type ActionKind int

const (
	ActionPlayCard        ActionKind = iota // 出卡
	ActionUseSkill                          // 使用角色技能
	ActionSwitchChar                        // 切换角色
	ActionEndTurn                           // 宣布结束回合
	ActionElementalTuning                   // 元素调和 (弃牌换骰子)
)

// ActionInput — 玩家一次 Action 的 typed 输入。字段按 Kind 互斥使用 (typed sum)。
type ActionInput struct {
	Kind   ActionKind
	Player int // 哪个玩家发起

	// ActionPlayCard / ActionElementalTuning
	CardIdx int // 手牌索引

	// ActionUseSkill
	SkillIdx int // 角色 skill_set 索引
	Actor    Owner

	// ActionPlayCard / ActionUseSkill 通用
	Target Owner // 目标角色 (无目标时 SystemOwner)

	// ActionSwitchChar
	SwitchToChar int
}

// ActionCtx — Action 层事务上下文。区别于 Ctx (SubAction 层)。
// 持 Action input + 已 fire 的 SubAction 列表 (trace) + 累计 commit count。
type ActionCtx struct {
	Game            *Game
	Input           ActionInput
	SubActionCount  int      // Action 内 fire 了几个 SubAction
	CommitCount     int      // 累计 commit 的 proposal 数 (跨 SubAction)
	Cancelled       bool     // Action 整体取消 (e.g. 不可玩)
	HeldSubAction   *HeldCtx // 若 SubAction 触发 sync PDR, 暂存以便 RL agent 处理
	PendingDecision []*PendingDecision
}

// ActionHookFn — Action-level hook 函数。可调 actx.FireSubAction 触发子 SubAction。
type ActionHookFn func(actx *ActionCtx, e *Engine)

// ActionHookSpec — Action-level hook 注册元数据 (类似 HookSpec 但 Action 层)。
type ActionHookSpec struct {
	Name        string
	Action      *ActionKind // nil = 任意 ActionKind (wildcard); 非 nil = 仅匹配该 kind
	Phase       HookPhase   // PhasePropose / PhaseResolve / PhaseCommit
	OwnerScalar *Scalar     // A16 owner-bind
	OwnerCol    *Collection
	Fn          ActionHookFn
}

// engine 注册 Action-level hook (与 RegisterHook 平行,但 Action 层独立)
func (e *Engine) RegisterActionHook(h *ActionHookSpec) {
	if h.Name == "" {
		panic("action hook name 必须显式")
	}
	for _, existing := range e.actionHooks {
		if existing.Name == h.Name {
			panic("action hook name 重复: " + h.Name)
		}
	}
	e.actionHooks = append(e.actionHooks, h)
}

// FireSubActionFromAction — Action-level hook 内调用, 触发一个 SubAction。
// 自动设置 TriggerSource (按 hook 注册时的 ActionKind 推断或显式传)。
// 返回 (committed_proposal_count, held_ctx)。
func (actx *ActionCtx) FireSubActionFromAction(e *Engine, ctx *Ctx) (int, *HeldCtx) {
	count, _, held := e.FireSubActionWithHeldSupport(ctx)
	actx.SubActionCount++
	actx.CommitCount += count
	if held != nil {
		actx.HeldSubAction = held
	}
	return count, held
}

// ProcessAction — Action 层主入口。
// 流程: propose → resolve → commit hooks (业务 fire SubAction 在 hook 内) → on_after。
// 不直接 commit Action 本身 (Action 不是 mutation,纯 dispatch + hook trigger)。
func (e *Engine) ProcessAction(input ActionInput) *ActionCtx {
	actx := &ActionCtx{Game: e.Game, Input: input}
	for _, h := range e.actionHooksFor(input.Kind, PhasePropose) {
		if !actionHookOwnerAlive(h) {
			continue
		}
		h.Fn(actx, e)
		if actx.Cancelled {
			return actx
		}
	}
	for _, h := range e.actionHooksFor(input.Kind, PhaseResolve) {
		if !actionHookOwnerAlive(h) {
			continue
		}
		h.Fn(actx, e)
		if actx.Cancelled {
			return actx
		}
	}
	for _, h := range e.actionHooksFor(input.Kind, PhaseCommit) {
		if !actionHookOwnerAlive(h) {
			continue
		}
		h.Fn(actx, e)
	}
	return actx
}

// actionHooksFor — 收集 (Action kind, phase) 的 hook,按注册序。
func (e *Engine) actionHooksFor(kind ActionKind, phase HookPhase) []*ActionHookSpec {
	matched := []*ActionHookSpec{}
	for _, h := range e.actionHooks {
		if h.Phase != phase {
			continue
		}
		if h.Action != nil && *h.Action != kind {
			continue
		}
		matched = append(matched, h)
	}
	return matched
}

func actionHookOwnerAlive(h *ActionHookSpec) bool {
	if h.OwnerScalar != nil && h.OwnerScalar.Destroyed {
		return false
	}
	if h.OwnerCol != nil && h.OwnerCol.Destroyed {
		return false
	}
	return true
}
