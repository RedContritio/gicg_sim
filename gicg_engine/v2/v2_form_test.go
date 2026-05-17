package enginev2

import "testing"

// A17 + A29: form-bound hook auto-skip。
func TestA17A29FormSwapBoundHook(t *testing.T) {
	g := NewGame()
	hp := g.DeclareScalar("enemy_hp", 10, 0, 10, Owner{Player: 1, Char: 0})
	form := g.DeclareScalar("kang_form", int(FormNormal), int(FormNormal), int(FormDisabled), Owner{Player: 0, Char: 0})
	e := NewEngine(g)

	// normal form 下的 boost (+2 雷伤)
	e.RegisterHook(&HookSpec{
		Name: "kang/normal_boost", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		ActiveInForm: FormNormal, FormOwnerScalar: form,
		Fn: func(ctx *Ctx) {
			if ctx.Element != ElementElectro {
				return
			}
			ctx.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -2})
		},
	})

	// 第一次攻击: form=normal → boost 触发
	ctx1 := &Ctx{Game: g, SubAction: SubActionDealDamage, Element: ElementElectro,
		TriggerSource: TriggerPlayerAction,
		Actor:         Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1}
	ctx1.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
	e.FireSubAction(ctx1)
	if hp.Value != 7 {
		t.Errorf("normal form: expected hp=7 (10-1-2), got %d", hp.Value)
	}

	form.Value = int(FormDisabled)

	// 第二次攻击: form=disabled → boost hook skip
	ctx2 := &Ctx{Game: g, SubAction: SubActionDealDamage, Element: ElementElectro,
		TriggerSource: TriggerPlayerAction,
		Actor:         Owner{Player: 0, Char: 0}, Target: Owner{Player: 1, Char: 0}, Value: 1}
	ctx2.Propose(Proposal{Kind: PropValueDelta, Scalar: hp, Delta: -1})
	e.FireSubAction(ctx2)
	if hp.Value != 6 {
		t.Errorf("disabled form: expected hp=6 (7-1, 无 boost), got %d", hp.Value)
	}
}

// A17 collection_replace skill-set
func TestA17SkillSetReplace(t *testing.T) {
	g := NewGame()
	form := g.DeclareScalar("luxing_form", int(FormNormal), int(FormNormal), int(FormActive), Owner{Player: 0, Char: 0})
	skillSet := g.DeclareCollection("luxing_skill_set", 5, Owner{Player: 0, Char: 0}, "shared")
	skillNormalAttack := &SkillRef{Ref: 1, Owner: Owner{Player: 0, Char: 0}, Element: ElementNone}
	skillNormalBurst := &SkillRef{Ref: 2, Owner: Owner{Player: 0, Char: 0}, Element: ElementDendro}
	skillWitheredBurst := &SkillRef{Ref: 3, Owner: Owner{Player: 0, Char: 0}, Element: ElementFire}
	skillSet.Append(skillNormalAttack)
	skillSet.Append(skillNormalBurst)

	e := NewEngine(g)

	// 火元素受击 → 转 withered + skill_set replace
	e.RegisterHook(&HookSpec{
		Name: "luxing/withered_transform", SubAction: subActionPtr(SubActionDealDamage), Phase: PhasePropose,
		ActiveInForm: FormNormal, FormOwnerScalar: form,
		Fn: func(ctx *Ctx) {
			if ctx.Element != ElementFire {
				return
			}
			ctx.Propose(Proposal{Kind: PropValueSet, Scalar: form, NewValue: int(FormWithered)})
			ctx.Propose(Proposal{Kind: PropCollectionRemoveAt, Collection: skillSet, Position: 1})
			ctx.Propose(Proposal{Kind: PropCollectionInsert, Collection: skillSet, Position: 1, Item: skillWitheredBurst})
		},
	})

	ctx := &Ctx{Game: g, SubAction: SubActionDealDamage, Element: ElementFire,
		TriggerSource: TriggerPlayerAction,
		Actor:         Owner{Player: 1, Char: 0}, Target: Owner{Player: 0, Char: 0}, Value: 1}
	count, _ := e.FireSubAction(ctx)
	if count == 0 {
		t.Fatalf("expected commit")
	}
	if FormStateKind(form.Value) != FormWithered {
		t.Errorf("expected form=withered, got %d", form.Value)
	}
	if s, ok := skillSet.Items[1].(*SkillRef); !ok || s.Ref != 3 {
		t.Errorf("expected skill_set[1].Ref=3 (withered_burst), got %v", skillSet.Items[1])
	}
}
