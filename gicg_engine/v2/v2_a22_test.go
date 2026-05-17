package enginev2

import "testing"

// A22 — TriggerSource ctx 字段 filter (取代旧 silent_kind 白名单方案)。
// 烟绯天赋: 仅 player_action 火元素普攻时 charge +2;
// equip_trigger / reaction_subdamage / 非火元素 全跳过。
// engine 不维护 silent.lua 白名单 — engine 只塞 typed ctx 字段, 业务 hook 自 filter。
func TestA22TriggerSourceFilter(t *testing.T) {
	g := NewGame()
	charge := g.DeclareScalar("yanfei_charge", 0, 0, 4, Owner{Player: 0, Char: 0})
	hp := g.DeclareScalar("enemy_hp", 10, 0, 10, Owner{Player: 1, Char: 0})
	e := NewEngine(g)

	e.RegisterHook(&HookSpec{
		Name: "yanfei/passive_charge", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		Fn: func(ctx *Ctx) {
			if !ctx.IsPlayerAction() {
				return
			}
			if ctx.Element != ElementFire {
				return
			}
			ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: charge, Delta: 2})
		},
	})

	// 1. player_action + 火 → charge +2
	ctx1 := &Ctx{Game: g, SubAction: SubActionDealDamage, Element: ElementFire,
		TriggerSource: TriggerPlayerAction,
		Actor:         Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1}
	ctx1.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
	e.FireSubAction(ctx1)
	if charge.Value != 2 {
		t.Errorf("player_action+fire: expected charge=2, got %d", charge.Value)
	}

	// 2. equip_trigger + 火 → charge 不变
	ctx2 := &Ctx{Game: g, SubAction: SubActionDealDamage, Element: ElementFire,
		TriggerSource: TriggerEquipOnPlay,
		Actor:         Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1}
	ctx2.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
	e.FireSubAction(ctx2)
	if charge.Value != 2 {
		t.Errorf("equip_trigger: expected charge=2 (unchanged), got %d", charge.Value)
	}

	// 3. reaction_subdamage + 火 → charge 不变
	ctx3 := &Ctx{Game: g, SubAction: SubActionDealDamage, Element: ElementFire,
		TriggerSource: TriggerReactionSubdamage,
		Actor:         Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1}
	ctx3.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
	e.FireSubAction(ctx3)
	if charge.Value != 2 {
		t.Errorf("reaction_subdamage: expected charge=2 (unchanged), got %d", charge.Value)
	}

	// 4. player_action + 雷 (非火) → charge 不变
	ctx4 := &Ctx{Game: g, SubAction: SubActionDealDamage, Element: ElementElectro,
		TriggerSource: TriggerPlayerAction,
		Actor:         Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1}
	ctx4.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
	e.FireSubAction(ctx4)
	if charge.Value != 2 {
		t.Errorf("electro player_action: expected charge=2 (non-fire), got %d", charge.Value)
	}
}
