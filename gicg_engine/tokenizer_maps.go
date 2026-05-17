package engine

// Token keyword / enum / ctx-field / method lookup tables. Consumed by
// TokenizeLua in tokenizer.go.

var tokenMap map[string]int

func init() {
	tokenMap = map[string]int{
		// Keywords
		"if": TokIf, "then": TokThen, "end": TokEnd, "return": TokReturn,
		"elseif": TokElseif, "else": TokElse, "local": TokLocal,
		"function": TokFunction, "and": TokAnd, "or": TokOr, "not": TokNot,
		"true": TokTrue, "false": TokFalse, "nil": TokNil,

		// APIs
		"declare_counter": TokDeclareCounter, "get_counter": TokGetCounter,
		"get_counter_group": TokGetCounterGroup, "register_on_tag_write": TokRegisterOnTagWrite,
		"declare_char": TokDeclareChar, "get_char": TokGetChar,
		"declare_skill": TokDeclareSkill, "get_skill": TokGetSkill,
		"invoke_skill": TokInvokeSkill,
		"declare_card": TokDeclareCard, "get_card": TokGetCard, "add_card": TokAddCard,
		"deal_damage": TokDealDamage, "heal": TokHeal,
		"defer_fn": TokDeferFn, "get_active_char": TokGetActiveChar,
		"set_active_char": TokSetActiveChar, "get_next_char": TokGetNextChar,
		"context_player": TokContextPlayer, "force_switch": TokForceSwitch,
		"gain_energy": TokGainEnergy, "consume_energy": TokConsumeEnergy,
		"set_winner": TokSetWinner, "get_turn": TokGetTurn,
		"draw_card": TokDrawCard, "cancel": TokCancel,
		"min": TokMin, "max": TokMax, "pcall": TokPcall,

		// Hooks
		"on_reaction_damage": TokOnReactionDamage,
		"on_after_damage":    TokOnAfterDamage,
		"on_before_heal":     TokOnBeforeHeal, "on_after_heal": TokOnAfterHeal,
		"on_action_check": TokOnActionCheck, "on_action_prepare": TokOnActionPrepare,
		"on_skill_use": TokOnSkillUse, "on_card_play": TokOnCardPlay,
		"on_switch": TokOnSwitch, "on_before_turn_flip": TokOnBeforeTurnFlip,
		"on_round_start": TokOnRoundStart, "on_round_end": TokOnRoundEnd,
		"on_round_end_post_summon": TokOnRoundEndPostSummon,
		"on_round_end_decay":       TokOnRoundEndDecay, "on_round_end_final": TokOnRoundEndFinal,
		"on_before_write": TokOnBeforeWrite, "on_after_write": TokOnAfterWrite,
		"on_before_energy_gain":    TokOnBeforeEnergyGain,
		"on_after_energy_gain":     TokOnAfterEnergyGain,
		"on_before_energy_consume": TokOnBeforeEnergyConsume,
		"on_after_energy_consume":  TokOnAfterEnergyConsume,
		// ADR-0019 §B.5 — strict 4+3 hook 时机
		"on_damage_type":        TokOnDamageType,
		"on_damage_add":         TokOnDamageAdd,
		"on_damage_mul":         TokOnDamageMul,
		"on_damage_reduce_buff": TokOnDamageReduceBuff,
		"on_shield_absorb":      TokOnShieldAbsorb,
		"on_damage_immunity":    TokOnDamageImmunity,
		// ADR-0019 §A.4 — 调和 hook
		"on_tune": TokOnTune,
	}
}

var enumMap = map[string]int{
	"Element.None": TokElementNone, "Element.Fire": TokElementFire,
	"Element.Ice": TokElementIce, "Element.Water": TokElementWater,
	"Element.Electro": TokElementElectro, "Element.Geo": TokElementGeo,
	"Element.Physical": TokElementPhysical,
	"Element.Anemo":    TokElementAnemo, "Element.Dendro": TokElementDendro,
	"Element.Piercing": TokElementPiercing, // ADR-0019 §B.1

	"Target.EnemyActive": TokTargetEnemyActive, "Target.EnemyAll": TokTargetEnemyAll,
	"Target.OwnAll": TokTargetOwnAll, "Target.EnemyNonActive": TokTargetEnemyNonActive,
	"Target.OwnActive": TokTargetOwnActive, "Target.CardTarget": TokTargetCardTarget,

	"Scope.Self": TokScopeSelf, "Scope.ActiveStatus": TokScopeActiveStatus,
	"Scope.PerChar": TokScopePerChar, "Scope.PerPlayer": TokScopePerPlayer,
	"Scope.Global": TokScopeGlobal,

	"Op.Set": TokOpSet, "Op.Add": TokOpAdd, "Op.Sub": TokOpSub,

	"Source.Skill": TokSourceSkill, "Source.Card": TokSourceCard,
	"Source.Status": TokSourceStatus, "Source.Summon": TokSourceSummon,
	"Source.Support": TokSourceSupport, "Source.Reaction": TokSourceReaction,

	"Tag.Summon": TokTagSummon, "Tag.Element": TokTagElement,
	"Tag.Equip": TokTagEquip, "Tag.Food": TokTagFood,
	"Tag.Support": TokTagSupport, "Tag.Shield": TokTagShield,
	"Tag.Specialty": TokTagSpecialty,

	"Player.Own": TokPlayerOwn, "Player.Enemy": TokPlayerEnemy, "Player.All": TokPlayerAll,

	"Weapon.None": TokWeaponNone, "Weapon.Sword": TokWeaponSword,
	"Weapon.Polearm": TokWeaponPolearm, "Weapon.Bow": TokWeaponBow,
	"Weapon.Claymore": TokWeaponClaymore, "Weapon.Catalyst": TokWeaponCatalyst,

	"Slot.None": TokSlotNone, "Slot.Equip": TokSlotEquip,
	"Slot.Support": TokSlotSupport, "Slot.Specialty": TokSlotSpecialty,

	"ActionKind.Skill": TokActionKindSkill, "ActionKind.Card": TokActionKindCard,
	"ActionKind.Switch": TokActionKindSwitch, "ActionKind.EndTurn": TokActionKindEndTurn,

	"Zone.Hand": TokZoneHand, "Zone.Deck": TokZoneDeck,

	"Action.Switch": TokActionKindSwitch, // alias
}

var ctxFieldMap = map[string]int{
	"ctx.value": TokCtxValue, "ctx.element": TokCtxElement,
	"ctx.actor_player": TokCtxActorPlayer, "ctx.actor_char": TokCtxActorChar,
	"ctx.skill_index": TokCtxSkillIndex, "ctx.card_ref": TokCtxCardRef,
	"ctx.target_player": TokCtxTargetPlayer, "ctx.target_char": TokCtxTargetChar,
	"ctx.playable":      TokCtxPlayable,
	"ctx.battle_action": TokCtxBattleAction, "ctx.hit": TokCtxHit,
	"ctx.source": TokCtxSource, "ctx.action_kind": TokCtxActionKind,
	"ctx.penetrate": TokCtxPenetrate, "ctx.action_context": TokCtxActionContext,
	"ctx.paid": TokCtxPaid, "ctx.need_target": TokCtxNeedTarget,
}

var methodMap = map[string]int{
	"get": TokMGet, "set": TokMSet, "add": TokMAdd, "sub": TokMSub,
	"cmin": TokMCmin, "cmax": TokMCmax,
	"get_at": TokMGetAt, "set_at": TokMSetAt, "add_at": TokMAddAt, "sub_at": TokMSubAt,
	"decay_all": TokMDecayAll, "fill_all": TokMFillAll,
	"hp": TokMHp, "energy": TokMEnergy, "alive": TokMAlive,
	"owner_player": TokMOwnerPlayer, "owner_char": TokMOwnerChar,
	"name": TokMName, "element": TokMElement, "weapon": TokMWeapon,
}
