package enginev2

import "testing"

// helper: SubActionKind ptr (HookSpec.SubAction 是 *SubActionKind, nil = wildcard)
func subActionPtr(k SubActionKind) *SubActionKind { return &k }

// 测试 1 — 基本 propose-resolve-commit (A2)。
// 简单场景: deal_damage(target_hp, value=5) → 一个 boost hook +1 → commit hp -= 6
func TestBasicProposeCommit(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("hp_p1", 10, 0, 10, Owner{Player: 1, Char: 0})
	e := NewEngine(g)

	e.RegisterHook(&HookSpec{
		Name: "test/boost", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		Fn: func(ctx *Ctx) {
			ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
		},
	})

	ctx := &Ctx{
		Game: g, SubAction: SubActionDealDamage, TriggerSource: TriggerPlayerAction,
		Actor: Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 5,
	}
	ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -5})

	count, _ := e.FireSubAction(ctx)
	if count != 2 {
		t.Fatalf("expected 2 committed proposals, got %d", count)
	}
	if hp.Value != 4 {
		t.Fatalf("expected hp=4 (10-5-1), got %d", hp.Value)
	}
}

// 测试 2 — A2-rev: boost 被全 reject 后 buff 跟着 group reject 不消耗。
// 旧 KNOWN ISSUE → A2-rev source-hook group reject 修复后断言保留 buff。
func TestBoostNotConsumedWhenFullyAbsorbed(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("hp_p1", 10, 0, 10, Owner{Player: 1, Char: 0})
	boostBuff := g.DeclareScalar("boost_buff", 1, 0, 1, Owner{Player: 0, Char: 0})
	e := NewEngine(g)

	e.RegisterHook(&HookSpec{
		Name: "test/boost_with_consume", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		Fn: func(ctx *Ctx) {
			if boostBuff.Value <= 0 {
				return
			}
			ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
			ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: boostBuff, Delta: -1})
		},
	})

	e.RegisterHook(&HookSpec{
		Name: "test/shield_reject", SubAction: subActionPtr(SubActionDealDamage), Phase: PhaseResolve,
		After: []string{"test/boost_with_consume"},
		Fn: func(ctx *Ctx) {
			for _, p := range ctx.Proposals {
				if p.Kind == PropValueDelta && p.Scalar == hp {
					p.Rejected = true
				}
			}
		},
	})

	ctx := &Ctx{
		Game: g, SubAction: SubActionDealDamage, TriggerSource: TriggerPlayerAction,
		Actor: Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 5,
	}
	ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -5})

	e.FireSubAction(ctx)
	if hp.Value != 10 {
		t.Errorf("expected hp=10 (全抵), got %d", hp.Value)
	}
	if boostBuff.Value != 1 {
		t.Errorf("✗ A2-rev FAIL: expected boost_buff=1 (group reject), got %d", boostBuff.Value)
	}
}

// 测试 3 — A2-rev 显式: 同 source hook group reject。
func TestSourceHookGroupReject(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("hp_p1", 10, 0, 10, Owner{Player: 1, Char: 0})
	boostBuff := g.DeclareScalar("boost_buff_v2", 1, 0, 1, Owner{Player: 0, Char: 0})
	e := NewEngine(g)

	e.RegisterHook(&HookSpec{
		Name: "boost/v2", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		Fn: func(ctx *Ctx) {
			if boostBuff.Value <= 0 {
				return
			}
			ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
			ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: boostBuff, Delta: -1})
		},
	})

	e.RegisterHook(&HookSpec{
		Name: "immunity/v2", SubAction: subActionPtr(SubActionDealDamage), Phase: PhaseResolve,
		After: []string{"boost/v2"},
		Fn: func(ctx *Ctx) {
			for _, p := range ctx.Proposals {
				if p.Kind == PropValueDelta && p.Scalar == hp && p.Delta < 0 {
					p.Rejected = true
				}
			}
		},
	})

	ctx := &Ctx{Game: g, SubAction: SubActionDealDamage, TriggerSource: TriggerPlayerAction,
		Actor: Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 5}
	ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -5})

	e.FireSubAction(ctx)
	if hp.Value != 10 {
		t.Errorf("expected hp=10 (immune), got %d", hp.Value)
	}
	if boostBuff.Value != 1 {
		t.Errorf("expected boost_buff=1, got %d", boostBuff.Value)
	}
}
