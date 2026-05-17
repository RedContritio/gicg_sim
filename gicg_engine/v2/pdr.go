package enginev2

// A25 — Player Decision Request 协议。
//
// 关键 design 决策:**v4 ADR 的 PDR 是 "hook chain 完 + commit 后处理 substate"**,
// 但 v3/v4 review #10 (勘探钻机) 暴露 fundamental flaw: 受伤 propose 内 PDR 完成后
// 想 modify dmg proposal — 但 transaction 已 commit,无法回头改。
//
// 本 prototype 验证两个 PDR 变体:
//
// 变体 A (PDR-async, v4 ADR 原版): hook 调 RequestDecision mark,主 transaction commit,
// substate 是后续 step。完成后 callback 不能 modify 已 commit 的 ctx。
//
// 变体 B (PDR-sync-with-hold, prototype 探索 — A30): hook 调 RequestDecisionSync,
// engine **暂停 hook chain 当前位置**,enter substate 同步等结果,resume 后续 hook。
// transaction 跨多 RL step 但 atomic;HeldCtx + DecisionSpec 是 plain typed data,可 fork 兼容 A11。
//
// 全 typed: DecisionSpec / DecisionResult 是 sum type (DecisionKind enum + 互斥字段)。

// ===== Typed DecisionSpec / DecisionResult sum type =====

type DecisionKind int

const (
	DecisionSelectFromCollection DecisionKind = iota // 千织 3-of-4 召唤物挑选
	DecisionBinaryChoice                             // 勘探钻机 hp/手牌二选一
	DecisionTargetChar                               // 普攻指定目标角色
	DecisionCostPayment                              // A24 dice 支付方案
	DecisionEnterSubstate                            // 进 sub-game (烈絮特技 sub-skill)
)

// BinaryOption — typed binary choice 的选项 (取代旧 OptionA/B string label)。
// 业务 hook 通过 ResultMarker 区分玩家选了哪边 (resolve hook 读 ctx.DecisionResult.ChosenBinary)。
type BinaryOption struct {
	ResultMarker *MarkerRef // 选中此项后由 resolve hook 标的 marker (declared)
	LabelHint    string     // 仅 RL obs encoder 编码用 hint, 不进业务逻辑
}

// DecisionSpec — RL agent 在 PDR step 看到的决策内容。
// 字段按 Kind 互斥使用 (typed sum)。
type DecisionSpec struct {
	Kind DecisionKind

	// DecisionSelectFromCollection
	SourceCollection *Collection // 从哪个 collection 挑
	SelectCount      int         // 挑几个

	// DecisionBinaryChoice
	Options [2]*BinaryOption

	// DecisionTargetChar
	AllowedTargets []Owner // 可选 target 列表

	// DecisionCostPayment
	CostSpec *CostSpec

	// DecisionEnterSubstate
	Substate *SubstateTemplate
	InitData *SubstateInitData
}

// DecisionResult — RL agent 选完后写回。typed sum, Kind 必须与 Spec 一致。
type DecisionResult struct {
	Kind DecisionKind

	// DecisionSelectFromCollection
	SelectedIndices []int

	// DecisionBinaryChoice
	ChosenBinary int // 0 or 1

	// DecisionTargetChar
	ChosenTarget Owner

	// DecisionCostPayment
	PaidDice []DiceColor // 实际支付的骰子序列

	// DecisionEnterSubstate
	SubstateExit *SubstateExitData
}

// PendingDecision — A25 async PDR 的队列项 (engine 在主 transaction commit 后 FIFO 处理)。
type PendingDecision struct {
	Spec      *DecisionSpec
	ParentCtx *Ctx
}

// HeldCtx — A30 PDR-sync-with-hold: transaction 被 PDR 暂停的状态。
// engine 把 HeldCtx 暴露给 RL,agent step 选完后写 Result,engine.ResumeHeldCtx 继续。
type HeldCtx struct {
	Ctx          *Ctx
	DecisionSpec *DecisionSpec
	// engine 在 RL agent 选完后填,resume 时拷贝到 ctx.DecisionResult
	DecisionResult *DecisionResult
	ResumePhase    HookPhase // hook chain 暂停在哪 (typed)
	ResumeIdx      int       // 暂停在该 phase 的第几 hook
}

// RequestDecisionAsync — A25 async PDR (主 transaction commit 后处理,不能 modify in-flight)。
func (ctx *Ctx) RequestDecisionAsync(spec *DecisionSpec) {
	pd := &PendingDecision{Spec: spec, ParentCtx: ctx}
	ctx.PendingDecisions = append(ctx.PendingDecisions, pd)
}

// RequestDecisionSync — A30 sync PDR (engine 暂停 hook chain, 等 RL 选完 resume)。
// 当前 hook fire 完后,engine 检查 ctx.HoldFor,若非 nil 则 abort hook chain + 暴露 HeldCtx。
func (ctx *Ctx) RequestDecisionSync(spec *DecisionSpec) {
	ctx.HoldFor = spec
}

// FireSubActionWithHeldSupport — 增强版 FireSubAction,支持同步 PDR hold (A30)。
//
// 返回 (committed_count, pending_async_decisions, held_ctx)。
//   - held_ctx == nil: transaction 正常 commit
//   - held_ctx != nil: transaction held,engine 应:
//     1. 暴露 held_ctx.DecisionSpec 给 RL agent (新 game step)
//     2. agent 选 → 写 held_ctx.DecisionResult
//     3. 调 e.ResumeHeldCtx(held_ctx) 继续
func (e *Engine) FireSubActionWithHeldSupport(ctx *Ctx) (int, []*PendingDecision, *HeldCtx) {
	// propose phase
	for i, h := range e.hooksFor(ctx.SubAction, PhasePropose) {
		if !hookOwnerAlive(h) {
			continue
		}
		appendProvenance(ctx, h.Name, "propose")
		h.Fn(ctx)
		if ctx.HoldFor != nil {
			return 0, nil, &HeldCtx{
				Ctx:          ctx,
				DecisionSpec: ctx.HoldFor,
				ResumePhase:  PhasePropose,
				ResumeIdx:    i + 1,
			}
		}
	}
	return e.continueFromResolve(ctx, 0)
}

func (e *Engine) continueFromResolve(ctx *Ctx, startIdx int) (int, []*PendingDecision, *HeldCtx) {
	resolveHooks := e.hooksFor(ctx.SubAction, PhaseResolve)
	for i := startIdx; i < len(resolveHooks); i++ {
		h := resolveHooks[i]
		if !hookOwnerAlive(h) {
			continue
		}
		appendProvenance(ctx, h.Name, "resolve")
		h.Fn(ctx)
		if ctx.HoldFor != nil {
			return 0, nil, &HeldCtx{
				Ctx:          ctx,
				DecisionSpec: ctx.HoldFor,
				ResumePhase:  PhaseResolve,
				ResumeIdx:    i + 1,
			}
		}
	}
	count, ok := commit(ctx)
	if !ok {
		return 0, nil, nil
	}
	for _, h := range e.hooksFor(ctx.SubAction, PhaseCommit) {
		if !hookOwnerAlive(h) {
			continue
		}
		appendProvenance(ctx, h.Name, "commit")
		h.Fn(ctx)
	}
	pending := ctx.PendingDecisions
	ctx.PendingDecisions = nil
	// L3 obs: append typed transition entry
	ctx.Game.AppendTransition(TransitionEntry{
		SubAction:     ctx.SubAction,
		Actor:         ctx.Actor,
		Target:        ctx.Target,
		Element:       ctx.Element,
		TriggerSource: ctx.TriggerSource,
		Value:         ctx.Value,
		Cancelled:     false,
	})
	return count, pending, nil
}

// ResumeHeldCtx — RL agent 把 result 写进 HeldCtx 后调 resume。
func (e *Engine) ResumeHeldCtx(held *HeldCtx) (int, []*PendingDecision, *HeldCtx) {
	ctx := held.Ctx
	ctx.HoldFor = nil
	ctx.DecisionResult = held.DecisionResult
	if held.ResumePhase == PhasePropose {
		// 继续 propose 剩余 hook
		proposeHooks := e.hooksFor(ctx.SubAction, PhasePropose)
		for i := held.ResumeIdx; i < len(proposeHooks); i++ {
			h := proposeHooks[i]
			if !hookOwnerAlive(h) {
				continue
			}
			appendProvenance(ctx, h.Name, "propose")
			h.Fn(ctx)
			if ctx.HoldFor != nil {
				return 0, nil, &HeldCtx{
					Ctx:          ctx,
					DecisionSpec: ctx.HoldFor,
					ResumePhase:  PhasePropose,
					ResumeIdx:    i + 1,
				}
			}
		}
		return e.continueFromResolve(ctx, 0)
	}
	if held.ResumePhase == PhaseResolve {
		return e.continueFromResolve(ctx, held.ResumeIdx)
	}
	return 0, nil, nil
}
