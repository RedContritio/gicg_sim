package enginev2

// A5 — 三层 pipeline (Action / SubAction / Mutation)。
// prototype 阶段实现 SubAction 单层 propose-resolve-commit;
// Action / Mutation 后续补 (验证 axiom 时 SubAction 已足够暴露 #10 PDR fundamental flaw)。
//
// 全 typed: SubAction / Phase / FormState 都是 enum (no string)。

import "sort"

// HookPhase — hook 注册和派发的阶段 (取代 string)。
type HookPhase int

const (
	PhasePropose HookPhase = iota
	PhaseResolve
	PhaseCommit
)

// FormStateKind — 角色 form 状态的 typed 枚举 (取代旧 ActiveInForm string)。
// 用于 A29 form-bound hook auto-skip。
type FormStateKind int

const (
	FormUnset    FormStateKind = iota // sentinel: 未设置 / 不限 form (always fire)
	FormNormal                        // 普通形态
	FormDisabled                      // 禁用 (例如未激活的天赋)
	FormWithered                      // 凋灵 (流浪者切形态)
	FormActive                        // 激活 (例如夜兰大招激活)
)

type HookFn func(ctx *Ctx)

// HookSpec — 注册 hook 时的 typed 元数据。
type HookSpec struct {
	Name string // 全局 unique (debug + dependency 引用 — 保留 string)

	// SubAction — nil = 匹配任意 SubActionKind (wildcard);非 nil = 仅匹配该 kind。
	SubAction *SubActionKind

	After  []string // 依赖于这些 hook name 之后 fire (typed dep 留待 lint 实现)
	Before []string

	OwnerScalar *Scalar     // A16 owner-bind: owner 容器 destroy → hook 自动 detach
	OwnerCol    *Collection // A16

	Phase HookPhase
	Fn    HookFn

	// A29 — Form-bound hook: 仅在指定 form 下 fire。
	// FormUnset = 不限 form (always fire);其他 = 仅在该 form 下 fire。
	ActiveInForm FormStateKind

	// A29 — 持有 active_form 容器 ref,engine 在 fire 前查 form scalar 当前值。
	// 简化: prototype 直接挂 owner-char 的 form scalar ref。Scalar.Value 必须是 FormStateKind 的 int 值。
	FormOwnerScalar *Scalar
}

// hookCacheKey — typed (SubActionKind, HookPhase) → uint。
type hookCacheKey struct {
	SubAction SubActionKind
	Phase     HookPhase
}

type Engine struct {
	Game           *Game
	hooks          []*HookSpec
	hookOrderCache map[hookCacheKey][]*HookSpec
	actionHooks    []*ActionHookSpec // A5 Action-level hook
}

func NewEngine(g *Game) *Engine {
	return &Engine{Game: g, hooks: []*HookSpec{}}
}

func (e *Engine) RegisterHook(h *HookSpec) {
	if h.Name == "" {
		panic("hook name 必须显式 (A4 全局 unique)")
	}
	for _, existing := range e.hooks {
		if existing.Name == h.Name {
			panic("hook name 重复: " + h.Name + " (A4)")
		}
	}
	e.hooks = append(e.hooks, h)
	e.hookOrderCache = nil // invalidate cache
}

// hooksFor — 收集 (subaction, phase) 的 hook,按 dependency topological sort (A4)。
// prototype 简化:不做真 topo sort,按 declared order + after-string 字面 hint
func (e *Engine) hooksFor(subAction SubActionKind, phase HookPhase) []*HookSpec {
	cacheKey := hookCacheKey{SubAction: subAction, Phase: phase}
	if e.hookOrderCache != nil {
		if cached, ok := e.hookOrderCache[cacheKey]; ok {
			return cached
		}
	}
	matched := []*HookSpec{}
	for _, h := range e.hooks {
		if h.Phase != phase {
			continue
		}
		if h.SubAction != nil && *h.SubAction != subAction {
			continue
		}
		matched = append(matched, h)
	}
	// 简化 topo sort: 按 (after-deps, name) 排序
	sort.SliceStable(matched, func(i, j int) bool {
		// 若 j 在 i.After 中,i 应该在后
		for _, a := range matched[i].After {
			if matched[j].Name == a || matchGlob(matched[j].Name, a) {
				return false
			}
		}
		// 若 i 在 j.After 中,i 应该在前
		for _, a := range matched[j].After {
			if matched[i].Name == a || matchGlob(matched[i].Name, a) {
				return true
			}
		}
		return matched[i].Name < matched[j].Name
	})
	if e.hookOrderCache == nil {
		e.hookOrderCache = map[hookCacheKey][]*HookSpec{}
	}
	e.hookOrderCache[cacheKey] = matched
	return matched
}

func matchGlob(name, pattern string) bool {
	if pattern == name {
		return true
	}
	// 简化 glob: pattern 末尾 "*" 匹配 prefix
	if len(pattern) > 0 && pattern[len(pattern)-1] == '*' {
		prefix := pattern[:len(pattern)-1]
		return len(name) >= len(prefix) && name[:len(prefix)] == prefix
	}
	return false
}

// FireSubAction — 完整跑一次 SubAction 的 propose → resolve → commit → drain PDR。
// 返回 (committed_proposal_count, pending_decisions_for_engine_to_handle)。
// 不支持 sync PDR hold;hold 路径走 FireSubActionWithHeldSupport (pdr.go)。
func (e *Engine) FireSubAction(ctx *Ctx) (int, []*PendingDecision) {
	// propose phase
	for _, h := range e.hooksFor(ctx.SubAction, PhasePropose) {
		if !hookOwnerAlive(h) {
			continue
		}
		appendProvenance(ctx, h.Name, "propose")
		h.Fn(ctx)
	}
	// resolve phase
	for _, h := range e.hooksFor(ctx.SubAction, PhaseResolve) {
		if !hookOwnerAlive(h) {
			continue
		}
		appendProvenance(ctx, h.Name, "resolve")
		h.Fn(ctx)
	}
	// commit phase
	count, ok := commit(ctx)
	if !ok {
		// 写 transition entry 标 cancelled
		ctx.Game.AppendTransition(TransitionEntry{
			SubAction:     ctx.SubAction,
			Actor:         ctx.Actor,
			Target:        ctx.Target,
			Element:       ctx.Element,
			TriggerSource: ctx.TriggerSource,
			Value:         ctx.Value,
			Cancelled:     true,
		})
		return 0, nil
	}
	// commit hooks (after-write 副作用,如 death check / log / reward accum)
	for _, h := range e.hooksFor(ctx.SubAction, PhaseCommit) {
		if !hookOwnerAlive(h) {
			continue
		}
		appendProvenance(ctx, h.Name, "commit")
		h.Fn(ctx)
	}
	// drain PDR — 返回给 engine,后续 step 处理
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
	// A6'/A7' drain nested SubActions (反应链 / 副伤害)。各 nested 独立 fire 完整 propose-commit。
	nested := ctx.NestedSubActions
	ctx.NestedSubActions = nil
	for _, nctx := range nested {
		nctx.Parent = ctx
		ncount, npending := e.FireSubAction(nctx)
		count += ncount
		pending = append(pending, npending...)
	}
	return count, pending
}

func hookOwnerAlive(h *HookSpec) bool {
	// A16 owner-bind GC: 引用的 owner 容器若已 Destroyed,hook 自动 detach。
	if h.OwnerScalar != nil && h.OwnerScalar.Destroyed {
		return false
	}
	if h.OwnerCol != nil && h.OwnerCol.Destroyed {
		return false
	}
	// A29 form-bound: 检查 hook 是否在当前 active form 下应该 fire
	if h.ActiveInForm != FormUnset && h.FormOwnerScalar != nil {
		// FormOwnerScalar.Value 编码 form (typed FormStateKind 的 int 值)
		if FormStateKind(h.FormOwnerScalar.Value) != h.ActiveInForm {
			return false
		}
	}
	return true
}

func appendProvenance(ctx *Ctx, hookName, kind string) {
	if len(ctx.Provenance) >= MaxProvenance {
		// drop oldest (A21 bound)
		ctx.Provenance = ctx.Provenance[1:]
	}
	ctx.Provenance = append(ctx.Provenance, ProvenanceEntry{HookName: hookName, Kind: kind})
}
