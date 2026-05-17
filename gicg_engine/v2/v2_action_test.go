package enginev2

import "testing"

// helper: ActionKind ptr (ActionHookSpec.Action 是 *ActionKind, nil = wildcard)
func actionKindPtr(k ActionKind) *ActionKind { return &k }

// A5 Action 层: PlayCard 入口 → 装备 OnPlay hook → fire SubActionDealDamage with TriggerEquipOnPlay。
//
// 验证:
//   - Action 入口 dispatch (PlayCard)
//   - Action-level hook (装备 OnPlay) 触发 SubAction
//   - SubAction 携带 TriggerSource=TriggerEquipOnPlay (A22 联动)
//   - 烟绯 charge hook (player_action only) 不触发 (因为这是 equip trigger)
//   - Action 完成后 LastTransitions 包含装备触发的 SubActionDealDamage entry
//   - actx.SubActionCount = 1 + actx.CommitCount = 1 (装备造成 1 dmg)
func TestA5ActionLayerEquipOnPlay(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("p1_hp", 100, 0, 100, Owner{Player: 1, Char: 0})
	hp.Tag = TagHP
	yanfeiCharge := g.DeclareScalar("yanfei_charge", 0, 0, 4, Owner{Player: 0, Char: 0})
	hand := g.DeclareCollection("p0_hand", 5, Owner{Player: 0, Char: -1}, "instance")
	equipCard := &CardRef{Ref: 100, Kind: CardKindEquipment, CostTotal: 2}
	hand.Append(equipCard)
	e := NewEngine(g)

	// 烟绯 charge hook: 仅 player_action 火元素普攻时 +2 (A22)
	e.RegisterHook(&HookSpec{
		Name: "yanfei/charge", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		Fn: func(ctx *Ctx) {
			if !ctx.IsPlayerAction() {
				return
			}
			if ctx.Element != ElementFire {
				return
			}
			ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: yanfeiCharge, Delta: 2})
		},
	})

	// Action-level hook: PlayCard equipment 时 fire SubActionDealDamage (装备 OnPlay 立即火伤)
	playKind := ActionPlayCard
	e.RegisterActionHook(&ActionHookSpec{
		Name: "equip/烈絮_OnPlay", Action: &playKind, Phase: PhaseCommit,
		Fn: func(actx *ActionCtx, e *Engine) {
			// 简化: 不真验证 card kind, 直接触发 1 火伤
			subCtx := &Ctx{
				Game: g, SubAction: SubActionDealDamage, Element: ElementFire,
				TriggerSource: TriggerEquipOnPlay,
				Actor:         Owner{Player: actx.Input.Player, Char: 0},
				Target:        actx.Input.Target,
				Value:         1,
			}
			subCtx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
			actx.FireSubActionFromAction(e, subCtx)
		},
	})

	// 玩家出装备牌 (PlayCard Action)
	actx := e.ProcessAction(ActionInput{
		Kind: ActionPlayCard, Player: 0, CardIdx: 0,
		Target: Owner{Player: 1, Char: 0},
	})

	// 验证 Action 完成
	if actx.Cancelled {
		t.Fatalf("Action 不应 cancelled")
	}
	if actx.SubActionCount != 1 {
		t.Errorf("expected 1 SubAction fired, got %d", actx.SubActionCount)
	}
	if actx.CommitCount != 1 {
		t.Errorf("expected 1 commit (装备 1 dmg), got %d", actx.CommitCount)
	}

	// 验证 hp 扣 (装备造成 1 dmg)
	if hp.Value != 99 {
		t.Errorf("expected hp=99 (100-1 装备), got %d", hp.Value)
	}

	// 关键验证 A22 联动: yanfei charge 不应增加 (因为 TriggerSource=TriggerEquipOnPlay 不是 PlayerAction)
	if yanfeiCharge.Value != 0 {
		t.Errorf("✗ A22 联动 FAIL: yanfei_charge 应=0 (equip trigger 不算 player action), got %d", yanfeiCharge.Value)
	}

	// 验证 LastTransitions 含装备触发的 entry
	if len(g.LastTransitions) != 1 {
		t.Fatalf("expected 1 transition (装备触发), got %d", len(g.LastTransitions))
	}
	te := g.LastTransitions[0]
	if te.SubAction != SubActionDealDamage {
		t.Errorf("transition SubAction wrong: %v", te.SubAction)
	}
	if te.TriggerSource != TriggerEquipOnPlay {
		t.Errorf("transition TriggerSource 应=TriggerEquipOnPlay, got %v", te.TriggerSource)
	}
	if te.Element != ElementFire {
		t.Errorf("transition Element 应=Fire, got %v", te.Element)
	}
}

// A5 Action 层: 玩家手动出火元素普攻 → 烟绯 charge +2 (TriggerPlayerAction)。
// 与上一 test 对照, 验证 TriggerSource 由 Action 层正确传给 SubAction。
func TestA5ActionLayerPlayerAttackTriggersCharge(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("p1_hp", 100, 0, 100, Owner{Player: 1, Char: 0})
	hp.Tag = TagHP
	yanfeiCharge := g.DeclareScalar("yanfei_charge", 0, 0, 4, Owner{Player: 0, Char: 0})
	e := NewEngine(g)

	e.RegisterHook(&HookSpec{
		Name: "yanfei/charge", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		Fn: func(ctx *Ctx) {
			if !ctx.IsPlayerAction() {
				return
			}
			if ctx.Element != ElementFire {
				return
			}
			ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: yanfeiCharge, Delta: 2})
		},
	})

	// Action-level hook: UseSkill 时 fire SubActionDealDamage with TriggerPlayerAction
	skillKind := ActionUseSkill
	e.RegisterActionHook(&ActionHookSpec{
		Name: "skill/normal_attack", Action: &skillKind, Phase: PhaseCommit,
		Fn: func(actx *ActionCtx, e *Engine) {
			subCtx := &Ctx{
				Game: g, SubAction: SubActionDealDamage, Element: ElementFire,
				TriggerSource: TriggerPlayerAction,
				Actor:         actx.Input.Actor,
				Target:        actx.Input.Target,
				Value:         1,
			}
			subCtx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
			actx.FireSubActionFromAction(e, subCtx)
		},
	})

	actx := e.ProcessAction(ActionInput{
		Kind: ActionUseSkill, Player: 0,
		Actor:  Owner{Player: 0, Char: 0},
		Target: Owner{Player: 1, Char: 0},
	})

	if actx.SubActionCount != 1 {
		t.Errorf("expected 1 SubAction, got %d", actx.SubActionCount)
	}
	if hp.Value != 99 {
		t.Errorf("expected hp=99 (100-1), got %d", hp.Value)
	}
	// A22: PlayerAction → charge +2 应触发
	if yanfeiCharge.Value != 2 {
		t.Errorf("expected yanfei_charge=2 (player+fire), got %d", yanfeiCharge.Value)
	}
	if g.LastTransitions[0].TriggerSource != TriggerPlayerAction {
		t.Errorf("transition TriggerSource 应=TriggerPlayerAction, got %v", g.LastTransitions[0].TriggerSource)
	}
}

// A5 Action 层 + A16: Action-level hook 的 owner 容器 destroyed → hook detach。
func TestA5ActionHookOwnerDetach(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("p1_hp", 100, 0, 100, Owner{Player: 1, Char: 0})
	supportZone := g.DeclareCollection("p0_support", 4, Owner{Player: 0, Char: -1}, "instance")
	supportZone.Append(&CardRef{Ref: 1, Kind: CardKindSupport})
	e := NewEngine(g)

	// 支援区 Action-level hook: 任意 PlayCard 时 fire SubActionDealDamage 1
	playKind := ActionPlayCard
	e.RegisterActionHook(&ActionHookSpec{
		Name: "support/jeht", Action: &playKind, Phase: PhaseCommit, OwnerCol: supportZone,
		Fn: func(actx *ActionCtx, e *Engine) {
			subCtx := &Ctx{
				Game: g, SubAction: SubActionDealDamage, Element: ElementNone,
				TriggerSource: TriggerCardSubAction,
				Actor:         Owner{Player: actx.Input.Player, Char: 0},
				Target:        Owner{Player: 1, Char: 0},
				Value:         1,
			}
			subCtx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
			actx.FireSubActionFromAction(e, subCtx)
		},
	})

	// 第一次 PlayCard: support fire
	actx1 := e.ProcessAction(ActionInput{Kind: ActionPlayCard, Player: 0, CardIdx: 0})
	if actx1.SubActionCount != 1 {
		t.Errorf("attack 1: expected 1 SubAction, got %d", actx1.SubActionCount)
	}
	if hp.Value != 99 {
		t.Errorf("attack 1: expected hp=99, got %d", hp.Value)
	}

	// 销毁 support zone
	ctxDestroy := &Ctx{Game: g, SubAction: SubActionGeneric, TriggerSource: TriggerEngineInternal,
		Actor: SystemOwner(), Target: SystemOwner()}
	ctxDestroy.Propose(Proposal{Kind: PropDestroy, Collection: supportZone})
	e.FireSubAction(ctxDestroy)

	// 第二次 PlayCard: support hook 应 detach
	actx2 := e.ProcessAction(ActionInput{Kind: ActionPlayCard, Player: 0, CardIdx: 0})
	if actx2.SubActionCount != 0 {
		t.Errorf("attack 2: expected 0 SubAction (hook detached), got %d", actx2.SubActionCount)
	}
	if hp.Value != 99 {
		t.Errorf("attack 2: expected hp=99 (no support trigger), got %d", hp.Value)
	}
}
