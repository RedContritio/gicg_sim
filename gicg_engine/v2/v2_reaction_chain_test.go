package enginev2

import "testing"

// A6'/A7' 反应链 + nested SubAction queue。
//
// 场景: 玩家火元素普攻 p1c0 (主 1 dmg), p1c0 已附水 (water_aura=1)。
// 蒸发反应触发: 主 dmg +2 (变 3) + 清水附着 + propose nested SubAction (扩散给 p1c1 1 anemo dmg)。
// 主 SubAction commit 完, engine drain nested → p1c1 hp 受 1 dmg。
//
// 验证:
// - 主 SubAction commit count = 3 (主 dmg + vaporize +2 + clear water)
// - nested SubAction commit count = 1 (扩散 1 dmg)
// - p1c0 hp 10 → 7, p1c1 hp 10 → 9
// - LastTransitions 含 2 entry: 主 (Fire/PlayerAction) + nested (Anemo/ReactionSubdamage)
// - 烟绯 charge hook 仅在主 SubAction (PlayerAction) 触发, 不在 nested (ReactionSubdamage)
func TestA6ReactionChainNestedSubAction(t *testing.T) {
	g := NewGame()
	hpC0 := g.DeclareScalar("p1c0_hp", 10, 0, 10, Owner{Player: 1, Char: 0})
	hpC0.Tag = TagHP
	hpC1 := g.DeclareScalar("p1c1_hp", 10, 0, 10, Owner{Player: 1, Char: 1})
	hpC1.Tag = TagHP
	waterAura := g.DeclareScalar("p1c0_water", 1, 0, 1, Owner{Player: 1, Char: 0})
	yanfeiCharge := g.DeclareScalar("yanfei_charge", 0, 0, 4, Owner{Player: 0, Char: 0})

	e := NewEngine(g)

	// 烟绯 charge: 仅 PlayerAction + Fire 时 +2
	e.RegisterHook(&HookSpec{
		Name: "yanfei/charge", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		Fn: func(ctx *Ctx) {
			if !ctx.IsPlayerAction() || ctx.Element != ElementFire {
				return
			}
			ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: yanfeiCharge, Delta: 2})
		},
	})

	// 蒸发反应: Fire + water_aura > 0 → +2 dmg + 清水 + 触发扩散 nested
	e.RegisterHook(&HookSpec{
		Name: "reaction/vaporize", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		Fn: func(ctx *Ctx) {
			if ctx.Element != ElementFire || waterAura.Value <= 0 {
				return
			}
			// vaporize +2 给主 target
			if ctx.Target.Char == 0 {
				ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hpC0, Delta: -2})
			}
			ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: waterAura, Delta: -1})

			// 扩散 nested SubAction: 副伤 1 给后台 c1 (Anemo / ReactionSubdamage)
			nctx := &Ctx{
				Game: g, SubAction: SubActionDealDamage, Element: ElementAnemo,
				TriggerSource: TriggerReactionSubdamage,
				Actor:         ctx.Actor,
				Target:        Owner{Player: 1, Char: 1}, // 后台 c1
				Value:         1,
			}
			nctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hpC1, Delta: -1})
			ctx.RequestNestedSubAction(nctx)
		},
	})

	// 主 SubAction: 玩家火元素普攻 p1c0 (1 dmg)
	mainCtx := &Ctx{
		Game: g, SubAction: SubActionDealDamage, Element: ElementFire,
		TriggerSource: TriggerPlayerAction,
		Actor:         Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1,
	}
	mainCtx.Propose(Proposal{Kind: PropValueDelta, Scalar: hpC0, Delta: -1})

	count, _ := e.FireSubAction(mainCtx)

	// 主 commit: hp -1 + yanfei charge +2 + vaporize -2 + water_aura -1 = 4
	// nested commit: hp -1 = 1
	// 总 5
	if count != 5 {
		t.Errorf("expected 5 total commits (主 4 含 yanfei charge + nested 1), got %d", count)
	}
	if hpC0.Value != 7 {
		t.Errorf("p1c0 hp 应 7 (10-1-2 vaporize), got %d", hpC0.Value)
	}
	if hpC1.Value != 9 {
		t.Errorf("p1c1 hp 应 9 (10-1 扩散副伤), got %d", hpC1.Value)
	}
	if waterAura.Value != 0 {
		t.Errorf("water_aura 应 0 (反应消耗), got %d", waterAura.Value)
	}

	// A22 联动: charge 仅主 SubAction (PlayerAction) 触发 = +2;nested (ReactionSubdamage) 不触发
	if yanfeiCharge.Value != 2 {
		t.Errorf("yanfei_charge 应=2 (仅主 SubAction PlayerAction 触发), got %d", yanfeiCharge.Value)
	}

	// LastTransitions 含 2 entry: 主 + nested
	if len(g.LastTransitions) != 2 {
		t.Fatalf("expected 2 transitions (主 + nested), got %d", len(g.LastTransitions))
	}
	main := g.LastTransitions[0]
	if main.SubAction != SubActionDealDamage || main.Element != ElementFire ||
		main.TriggerSource != TriggerPlayerAction {
		t.Errorf("main transition typed fields 错: %+v", main)
	}
	nested := g.LastTransitions[1]
	if nested.SubAction != SubActionDealDamage || nested.Element != ElementAnemo ||
		nested.TriggerSource != TriggerReactionSubdamage {
		t.Errorf("nested transition typed fields 错: %+v", nested)
	}
	if nested.Target.Char != 1 {
		t.Errorf("nested target 应 c1 (扩散), got %v", nested.Target)
	}
}

// 多层嵌套: 主 → nested1 → nested2 (chain depth 2)
// 验证 NestedSubAction 内部也可再 propose nested (递归 chain)
func TestA6ReactionChainTwoLayerNesting(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("hp", 100, 0, 100, Owner{Player: 1, Char: 0})

	e := NewEngine(g)

	// 单一 hook: 任何 deal_damage 内 propose 1 nested deal_damage (with TriggerEngineInternal)
	// 但只递归 1 次 (nested 是 EngineInternal, 不再触发自己)
	e.RegisterHook(&HookSpec{
		Name: "test/nested_chain", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		Fn: func(ctx *Ctx) {
			if ctx.TriggerSource != TriggerPlayerAction {
				return
			}
			// nested layer 1 propose 一个 EngineInternal 子 SubAction
			nctx1 := &Ctx{
				Game: g, SubAction: SubActionDealDamage, Element: ElementNone,
				TriggerSource: TriggerEngineInternal,
				Actor:         ctx.Actor, Target: ctx.Target, Value: 1,
			}
			nctx1.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
			ctx.RequestNestedSubAction(nctx1)
		},
	})

	// 第二个 hook: EngineInternal 时 propose 一个 ReactionSubdamage 子 SubAction (二层嵌套)
	e.RegisterHook(&HookSpec{
		Name: "test/nested_chain2", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		After: []string{"test/nested_chain"},
		Fn: func(ctx *Ctx) {
			if ctx.TriggerSource != TriggerEngineInternal {
				return
			}
			nctx2 := &Ctx{
				Game: g, SubAction: SubActionDealDamage, Element: ElementNone,
				TriggerSource: TriggerReactionSubdamage,
				Actor:         ctx.Actor, Target: ctx.Target, Value: 1,
			}
			nctx2.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
			ctx.RequestNestedSubAction(nctx2)
		},
	})

	mainCtx := &Ctx{
		Game: g, SubAction: SubActionDealDamage, Element: ElementNone,
		TriggerSource: TriggerPlayerAction,
		Actor:         Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1,
	}
	mainCtx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
	e.FireSubAction(mainCtx)

	// 主 -1 + nested1 -1 + nested2 -1 = -3 hp
	if hp.Value != 97 {
		t.Errorf("expected hp=97 (100-1-1-1 三层 chain), got %d", hp.Value)
	}
	if len(g.LastTransitions) != 3 {
		t.Errorf("expected 3 transitions (chain depth 2 = 3 层), got %d", len(g.LastTransitions))
	}
	// 顺序: 主 (PlayerAction) → nested1 (EngineInternal) → nested2 (ReactionSubdamage)
	if g.LastTransitions[0].TriggerSource != TriggerPlayerAction {
		t.Errorf("transition[0] 应 PlayerAction")
	}
	if g.LastTransitions[1].TriggerSource != TriggerEngineInternal {
		t.Errorf("transition[1] 应 EngineInternal")
	}
	if g.LastTransitions[2].TriggerSource != TriggerReactionSubdamage {
		t.Errorf("transition[2] 应 ReactionSubdamage")
	}
}

// nested SubAction parent ref 正确设置
func TestA6NestedSubActionParentRef(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("hp", 100, 0, 100, Owner{Player: 1, Char: 0})

	e := NewEngine(g)

	var capturedParent *Ctx
	e.RegisterHook(&HookSpec{
		Name: "main/trigger_nested", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		Fn: func(ctx *Ctx) {
			if ctx.TriggerSource != TriggerPlayerAction {
				return
			}
			nctx := &Ctx{
				Game: g, SubAction: SubActionDealDamage, Element: ElementNone,
				TriggerSource: TriggerReactionSubdamage,
				Actor:         ctx.Actor, Target: ctx.Target, Value: 1,
			}
			nctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
			ctx.RequestNestedSubAction(nctx)
		},
	})
	e.RegisterHook(&HookSpec{
		Name: "nested/inspect_parent", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		Fn: func(ctx *Ctx) {
			if ctx.TriggerSource == TriggerReactionSubdamage {
				capturedParent = ctx.Parent
			}
		},
	})

	mainCtx := &Ctx{
		Game: g, SubAction: SubActionDealDamage,
		TriggerSource: TriggerPlayerAction,
		Actor:         Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 0,
	}
	e.FireSubAction(mainCtx)

	if capturedParent == nil {
		t.Fatalf("nested ctx.Parent 应 = main ctx, got nil")
	}
	if capturedParent != mainCtx {
		t.Errorf("nested ctx.Parent 应指向 main ctx (recursive trace)")
	}
}
