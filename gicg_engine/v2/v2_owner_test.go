package enginev2

import "testing"

// A16 — Owner-detach hook lifecycle (tombstone GC)。
//
// 场景: 装备 "破葬之雷" attached_to_char (Owner=p0/c0), durability scalar 初始 2,
// 每次受击 -1, 0 → propose destroy (tombstone),之后该装备 hook 自动 detach。
//
// 验证:
//  1. 第一次受击: durability 2→1, hook fire (装备增伤 +1)
//  2. 第二次受击: durability 1→0 + propose destroy → hook fire 但本次仍生效
//     (本次 destroy 只影响后续 SubAction)
//  3. 第三次受击: hookOwnerAlive() 检测 durability.Destroyed=true → hook detach
//     此次只跑主 dmg, 无 +1 boost
func TestA16OwnerDetachHook(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("p1_hp", 100, 0, 100, Owner{Player: 1, Char: 0})
	durability := g.DeclareScalar("p0_equip_durability", 2, 0, 2, Owner{Player: 0, Char: 0})
	e := NewEngine(g)

	// 装备 hook: 受击时 +1 dmg + 自身 -1 durability;reach 0 → propose destroy。
	// OwnerScalar = durability (A16 owner-bind: durability destroyed → hook detach)。
	e.RegisterHook(&HookSpec{
		Name:        "equip/破葬之雷",
		SubAction:   subActionPtr(SubActionDealDamage),
		Phase:       PhasePropose,
		OwnerScalar: durability,
		Fn: func(ctx *Ctx) {
			ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
			ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: durability, Delta: -1})
			if durability.Value+(-1) <= 0 {
				// durability 即将归零 → 同 transaction 内 propose destroy
				ctx.Propose(Proposal{Kind: PropDestroy, Scalar: durability})
			}
		},
	})

	// 第一次攻击: 主 dmg + 装备 boost
	ctx1 := &Ctx{Game: g, SubAction: SubActionDealDamage, TriggerSource: TriggerPlayerAction,
		Actor: Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1}
	ctx1.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
	e.FireSubAction(ctx1)
	if hp.Value != 98 {
		t.Errorf("attack 1: expected hp=98 (100-1-1), got %d", hp.Value)
	}
	if durability.Value != 1 {
		t.Errorf("attack 1: expected durability=1, got %d", durability.Value)
	}
	if durability.Destroyed {
		t.Errorf("attack 1: durability not yet destroyed")
	}

	// 第二次攻击: 装备最后一次生效 + propose destroy
	ctx2 := &Ctx{Game: g, SubAction: SubActionDealDamage, TriggerSource: TriggerPlayerAction,
		Actor: Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1}
	ctx2.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
	e.FireSubAction(ctx2)
	if hp.Value != 96 {
		t.Errorf("attack 2: expected hp=96 (98-1-1), got %d", hp.Value)
	}
	if durability.Value != 0 {
		t.Errorf("attack 2: expected durability=0, got %d", durability.Value)
	}
	if !durability.Destroyed {
		t.Errorf("attack 2: expected durability.Destroyed=true (propose 已 commit)")
	}

	// 第三次攻击: hook 应自动 detach (durability tombstoned), 只主 dmg
	ctx3 := &Ctx{Game: g, SubAction: SubActionDealDamage, TriggerSource: TriggerPlayerAction,
		Actor: Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1}
	ctx3.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
	e.FireSubAction(ctx3)
	if hp.Value != 95 {
		t.Errorf("attack 3: expected hp=95 (96-1, no boost — hook detached), got %d", hp.Value)
	}
	if durability.Value != 0 {
		t.Errorf("attack 3: durability 应保 0 (hook detach 后不再操作), got %d", durability.Value)
	}
}

// A16 + Collection owner: hook owner 是 collection,collection destroyed → hook detach
func TestA16CollectionOwnerDetach(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("p1_hp", 100, 0, 100, Owner{Player: 1, Char: 0})
	supportZone := g.DeclareCollection("p0_support", 4, Owner{Player: 0, Char: -1}, "instance")
	supportZone.Append(&CardRef{Ref: 1, Kind: CardKindSupport})
	e := NewEngine(g)

	// 支援区 hook: 每次攻击 +1 dmg
	e.RegisterHook(&HookSpec{
		Name:      "support/凯瑟琳",
		SubAction: subActionPtr(SubActionDealDamage),
		Phase:     PhasePropose,
		OwnerCol:  supportZone,
		Fn: func(ctx *Ctx) {
			ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
		},
	})

	// 第一次攻击: support hook fire
	ctx1 := &Ctx{Game: g, SubAction: SubActionDealDamage, TriggerSource: TriggerPlayerAction,
		Actor: Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1}
	ctx1.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
	e.FireSubAction(ctx1)
	if hp.Value != 98 {
		t.Errorf("attack 1: expected hp=98, got %d", hp.Value)
	}

	// 销毁 support zone (例: 玩家被夺取支援区,或被 dispel)
	ctxDestroy := &Ctx{Game: g, SubAction: SubActionGeneric, TriggerSource: TriggerEngineInternal,
		Actor: SystemOwner(), Target: SystemOwner()}
	ctxDestroy.Propose(Proposal{Kind: PropDestroy, Collection: supportZone})
	e.FireSubAction(ctxDestroy)
	if !supportZone.Destroyed {
		t.Fatalf("support zone 应 destroyed")
	}

	// 第二次攻击: support hook 应 detach
	ctx2 := &Ctx{Game: g, SubAction: SubActionDealDamage, TriggerSource: TriggerPlayerAction,
		Actor: Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1}
	ctx2.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
	e.FireSubAction(ctx2)
	if hp.Value != 97 {
		t.Errorf("attack 2: expected hp=97 (98-1, no support boost), got %d", hp.Value)
	}
}

// A16 — propose destroy 后 rollback (整 transaction cancelled),Destroyed 应回滚
func TestA16DestroyRollback(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("p1_hp", 100, 0, 100, Owner{Player: 1, Char: 0})
	durability := g.DeclareScalar("durability", 1, 0, 1, Owner{Player: 0, Char: 0})

	// 模拟一个会失败的 transaction: insert 满 collection
	full := g.DeclareCollection("full", 1, Owner{Player: 0, Char: -1}, "instance")
	full.Append(&CardRef{Ref: 99})

	ctx := &Ctx{Game: g, SubAction: SubActionDealDamage, TriggerSource: TriggerPlayerAction,
		Actor: Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1}
	ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
	ctx.Propose(Proposal{Kind: PropDestroy, Scalar: durability})
	// 故意触发失败: insert 满 collection → commit 整体 rollback
	ctx.Propose(Proposal{Kind: PropCollectionInsert, Collection: full, Position: 0,
		Item: &CardRef{Ref: 100}})

	count, _ := NewEngine(g).FireSubAction(ctx)
	if count != 0 {
		t.Errorf("expected commit rollback (collection 满), got count=%d", count)
	}
	if durability.Destroyed {
		t.Errorf("rollback 后 durability.Destroyed 应回滚 = false, got true")
	}
	if hp.Value != 100 {
		t.Errorf("rollback 后 hp 应回滚 = 100, got %d", hp.Value)
	}
}
