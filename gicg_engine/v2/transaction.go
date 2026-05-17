package enginev2

// A2 — Mutation = propose-resolve-commit 事务。
// hook 在 propose phase 提交 proposal 到 ctx.Proposals;
// resolve phase 可 reject/cap 既有 proposal;
// commit phase engine atomic apply 全部未 reject 的 proposal,失败 → 全 rollback。
//
// 全 typed: Proposal 字段 Scalar/Collection/Marker/Decision 互斥使用 (按 Kind),
// 不再 any-typed Container + map[string]any Payload。
// applyProposal 误用字段 → panic (内部不变量),业务失败 → 返回 false 走 rollback。

type ProposalKind int

const (
	PropValueDelta         ProposalKind = iota // Scalar += Delta
	PropValueSet                               // Scalar = NewValue
	PropCollectionInsert                       // Collection.Insert(Position, Item)
	PropCollectionRemoveAt                     // Collection.RemoveAt(Position) → 存 Item 用于 rollback
	PropMarker                                 // 仅记录 (typed MarkerRef),commit noop
	PropRequestDecision                        // A25/A30 PDR (typed Decision)
	PropDestroy                                // A16 owner-detach: set Container.Destroyed = true
)

// Proposal — 一次提议的写入或副作用。
// 字段按 Kind 互斥使用,不允许混用 (typed sum)。
type Proposal struct {
	Kind ProposalKind

	// PropValueDelta / PropValueSet
	Scalar   *Scalar
	Delta    int
	NewValue int

	// PropCollectionInsert / PropCollectionRemoveAt
	Collection *Collection
	Item       Item // typed Item interface
	Position   int

	// PropMarker
	Marker *MarkerRef

	// PropRequestDecision
	Decision *DecisionSpec

	// 公共
	Owner    Owner  // A13: per-proposal owner (RL 不消费,仅 analytics)
	HookName string // 自动填,trace 用
	Rejected bool   // resolve phase 设
}

// Ctx — 一次 SubAction 的事务上下文。全 typed,无 map[string]any。
type Ctx struct {
	Game *Game

	// SubAction 元数据 (typed)
	SubAction     SubActionKind
	Element       ElementType   // 伤害/反应类 SubAction 用;无关时 ElementNone
	TriggerSource TriggerSource // A22 — engine 在调 SubAction 入口时塞
	Actor         Owner         // 谁触发(player, char)
	Target        Owner         // 受影响方(player, char);无明确 target 时 SystemOwner
	Value         int           // 主 effect value (deal_damage 的伤害量;heal 的治疗量)

	// 事务状态
	Proposals        []*Proposal
	PendingDecisions []*PendingDecision // A25 async PDR 队列 (hook chain 完后处理)

	// commit 控制
	Cancelled bool // = true 时 commit 全 rollback,不写 container,不 fire on_after

	// trace + 嵌套
	Provenance []ProvenanceEntry
	Parent     *Ctx // 嵌套 SubAction 的父 ctx

	// A30 PDR-sync-with-hold (typed): hook 调 RequestDecisionSync 时 set
	HoldFor *DecisionSpec

	// DecisionResult — RL agent 选完后由 engine 写入,resolve/commit hook 可读 (typed)
	DecisionResult *DecisionResult

	// A6'/A7' 反应链: hook 内 propose 嵌套 SubAction (例 vaporize 触发扩散副伤)。
	// engine 在主 SubAction commit hook chain 完后 drain — 各 nested 独立 propose-resolve-commit
	// + 各自进 LastTransitions ring。typed Ctx ptr (跟主 ctx 同 schema)。
	NestedSubActions []*Ctx
}

// RequestNestedSubAction — hook 内调,push 一个 nested SubAction ctx 到队列。
// engine 在主 SubAction commit hook chain 完后 drain (各 nested 独立 fire)。
// 典型用例: 反应触发副伤 (vaporize → 扩散给后台角色)。
func (ctx *Ctx) RequestNestedSubAction(nctx *Ctx) {
	ctx.NestedSubActions = append(ctx.NestedSubActions, nctx)
}

// IsPlayerAction — 便利字段, == (TriggerSource == TriggerPlayerAction)。
// hook 内典型用法: `if !ctx.IsPlayerAction() { return }` (烟绯天赋 / 战玉璋等)。
func (ctx *Ctx) IsPlayerAction() bool {
	return ctx.TriggerSource == TriggerPlayerAction
}

type ProvenanceEntry struct {
	HookName string
	Kind     string
}

const MaxProvenance = 32

func (ctx *Ctx) Propose(p Proposal) {
	p.HookName = ctx.currentHookName()
	ctx.Proposals = append(ctx.Proposals, &p)
}

// 当前正在 fire 的 hook name — 简化版从 provenance tail 取
func (ctx *Ctx) currentHookName() string {
	if len(ctx.Provenance) == 0 {
		return ""
	}
	return ctx.Provenance[len(ctx.Provenance)-1].HookName
}

// HasProposalKind — 后续 hook 查 ctx 已 propose 什么 kind (A21 cross-hook query)。
// 简化版: 仅按 kind 查;具体 marker/decision 比对用 HasMarker / HasDecisionKind。
func (ctx *Ctx) HasProposalKind(kind ProposalKind) bool {
	for _, p := range ctx.Proposals {
		if p.Kind == kind && !p.Rejected {
			return true
		}
	}
	return false
}

// HasMarker — 查指定 typed MarkerRef 是否被某 hook propose 过。
// 用于反应链 cross-hook signal (例: vaporize hook 标 marker, swirl hook 查 marker)。
func (ctx *Ctx) HasMarker(m *MarkerRef) bool {
	for _, p := range ctx.Proposals {
		if p.Kind != PropMarker || p.Rejected {
			continue
		}
		if p.Marker == m {
			return true
		}
	}
	return false
}

// commit — engine atomic apply 全部未 reject 的 proposal。
// 失败时 rollback 已 apply 的部分。返回 (committed_count, ok)。
//
// A2 prototype rev (source_hook_id 整组 reject):
// commit 前 engine 扫所有 proposal 的 HookName,若同一 HookName 的任一 proposal 被
// reject (业务 hook 标 Rejected=true),则该 HookName 的所有 proposal 都跟着 reject。
// 这避免 v3 review #5 "boost 被全抵不返还" — boost hook 同时 propose dmg + buff_consume,
// reduce hook reject dmg 后,buff_consume 也跟着 reject,buff 不消耗。
func commit(ctx *Ctx) (int, bool) {
	if ctx.Cancelled {
		return 0, false
	}
	// A2 rev: same-source group reject
	rejectedHooks := map[string]bool{}
	for _, p := range ctx.Proposals {
		if p.Rejected && p.HookName != "" {
			rejectedHooks[p.HookName] = true
		}
	}
	if len(rejectedHooks) > 0 {
		for _, p := range ctx.Proposals {
			if !p.Rejected && rejectedHooks[p.HookName] {
				p.Rejected = true
			}
		}
	}
	applied := []*Proposal{}
	for _, p := range ctx.Proposals {
		if p.Rejected {
			continue
		}
		ok := applyProposal(ctx.Game, p)
		if !ok {
			// rollback 已 applied
			for i := len(applied) - 1; i >= 0; i-- {
				rollbackProposal(ctx.Game, applied[i])
			}
			return 0, false
		}
		applied = append(applied, p)
	}
	return len(applied), true
}

func applyProposal(g *Game, p *Proposal) bool {
	switch p.Kind {
	case PropValueDelta:
		if p.Scalar == nil {
			panic("PropValueDelta proposal missing Scalar field")
		}
		p.Scalar.Value += p.Delta
		p.Scalar.clamp()
		return true
	case PropValueSet:
		if p.Scalar == nil {
			panic("PropValueSet proposal missing Scalar field")
		}
		p.Scalar.Value = p.NewValue
		p.Scalar.clamp()
		return true
	case PropCollectionInsert:
		if p.Collection == nil {
			panic("PropCollectionInsert proposal missing Collection field")
		}
		if p.Collection.MaxSize > 0 && len(p.Collection.Items) >= p.Collection.MaxSize {
			return false // 业务失败 (collection 满) — rollback
		}
		p.Collection.Insert(p.Position, p.Item)
		return true
	case PropCollectionRemoveAt:
		if p.Collection == nil {
			panic("PropCollectionRemoveAt proposal missing Collection field")
		}
		if p.Position < 0 || p.Position >= len(p.Collection.Items) {
			return false // 业务失败 (越界) — rollback
		}
		// 记录被移除 item, 用于 rollback
		p.Item = p.Collection.RemoveAt(p.Position)
		return true
	case PropMarker, PropRequestDecision:
		// markers / decision spec 不写容器,只记录 ctx,commit 时 noop
		return true
	case PropDestroy:
		// A16: tombstone 标记容器已销毁,引用它的 hook 在下次 fire 时自动 detach
		if p.Scalar != nil {
			p.Scalar.Destroyed = true
			return true
		}
		if p.Collection != nil {
			p.Collection.Destroyed = true
			return true
		}
		panic("PropDestroy proposal missing Scalar or Collection field")
	}
	panic("unknown ProposalKind")
}

func rollbackProposal(g *Game, p *Proposal) {
	switch p.Kind {
	case PropValueDelta:
		p.Scalar.Value -= p.Delta
		p.Scalar.clamp()
	case PropValueSet:
		// PropValueSet rollback 需要 before 值 — prototype 简化省略 (实际 commit 前应记 before)
	case PropCollectionInsert:
		p.Collection.RemoveAt(p.Position)
	case PropCollectionRemoveAt:
		p.Collection.Insert(p.Position, p.Item)
	case PropMarker, PropRequestDecision:
		// noop
	case PropDestroy:
		// rollback destroy: 取消 tombstone
		if p.Scalar != nil {
			p.Scalar.Destroyed = false
		}
		if p.Collection != nil {
			p.Collection.Destroyed = false
		}
	}
}
