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
		"context_player": TokContextPlayer, "force_switch_next": TokForceSwitch,
		"force_switch_previous": TokForceSwitchPrevious,
		"apply_element":         TokApplyElement,
		"is_char_alive":         TokIsCharAlive,
		"gain_energy":           TokGainEnergy, "consume_energy": TokConsumeEnergy,
		"set_winner": TokSetWinner, "get_turn": TokGetTurn,
		"draw_card": TokDrawCard, "cancel": TokCancel,
		"min": TokMin, "max": TokMax, "pcall": TokPcall,

		// Hooks
		"on_reaction_damage": TokOnReactionDamage,
		"on_after_damage":    TokOnAfterDamage,
		"on_after_reaction":  TokOnAfterReaction,
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

		// RC2 — DSL builtins absent from the IR compiler's tokenMap
		// caused finalizeHookIRs to reject 40%+ of hook bodies. These
		// dispatch through OpCall on the Op1 token (same path as
		// deal_damage etc.); IR-3 runtime looks the name back up via
		// engine.LookupBuiltin → handler table at execution time.
		"roll_dice":                       TokRollDice,
		"clear_dice_pool":                 TokClearDicePool,
		"set_reaction_kind":               TokSetReactionKind,
		"cost_total":                      TokCostTotal,
		"cost_mod":                        TokCostMod,
		"register_buff":                   TokRegisterBuff,
		"spawn_buff":                      TokSpawnBuff,
		"spawn_support_buff":              TokSpawnSupportBuff,
		"buff_progress":                   TokBuffProgress,
		"set_buff_progress":               TokSetBuffProgress,
		"get_dice_total":                  TokGetDiceTotal,
		"selected_buff":                   TokSelectedBuff,
		"background_energy":               TokBackgroundEnergy,
		"transfer_energy_from_background": TokTransferBackgroundEnergy,
		"choose_reroll":                   TokChooseReroll,
		"buff_duration":                   TokBuffDuration,
		"set_buff_duration":               TokSetBuffDuration,
		"cost_reduce":                     TokCostReduce,
		"was_applied":                     TokWasApplied,
		"add_dice":                        TokAddDice,
		"set_preparing":                   TokSetPreparing,
		"has_card_in_own_hand":            TokHasCardInOwnHand,
		"remove_support":                  TokRemoveSupport,
		"request_switch":                  TokRequestSwitch,

		// Element → DiceColor bridge (paired with add_dice; the two enum
		// spaces are offset by one because Element.None occupies 0).
		"element_to_dice_color": TokElementToDiceColor,
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

	// RC2: CostSlot (cost_mod second arg) + DiceColor (add_dice
	// second arg) reach into hook bodies in v_legacy + v_phase2 cards.
	"CostSlot.Fire": TokCostSlotFire, "CostSlot.Ice": TokCostSlotIce,
	"CostSlot.Water": TokCostSlotWater, "CostSlot.Electro": TokCostSlotElectro,
	"CostSlot.Geo": TokCostSlotGeo, "CostSlot.Anemo": TokCostSlotAnemo,
	"CostSlot.Dendro": TokCostSlotDendro, "CostSlot.Match": TokCostSlotMatch,
	"CostSlot.Any": TokCostSlotAny, "CostSlot.All": TokCostSlotAll,

	"DiceColor.Fire": TokDiceColorFire, "DiceColor.Ice": TokDiceColorIce,
	"DiceColor.Water": TokDiceColorWater, "DiceColor.Electro": TokDiceColorElectro,
	"DiceColor.Geo": TokDiceColorGeo, "DiceColor.Anemo": TokDiceColorAnemo,
	"DiceColor.Dendro": TokDiceColorDendro, "DiceColor.Omni": TokDiceColorOmni,
}

var ctxFieldMap = map[string]int{
	"ctx.value": TokCtxValue, "ctx.element": TokCtxElement,
	"ctx.attachment_only":  TokCtxAttachmentOnly,
	"ctx.reaction_element": TokCtxReactionElement,
	"ctx.reaction_kind":    TokCtxReactionKind,
	"ctx.actor_player":     TokCtxActorPlayer, "ctx.actor_char": TokCtxActorChar,
	"ctx.skill_index": TokCtxSkillIndex, "ctx.card_ref": TokCtxCardRef,
	"ctx.target_player": TokCtxTargetPlayer, "ctx.target_char": TokCtxTargetChar,
	"ctx.playable":      TokCtxPlayable,
	"ctx.battle_action": TokCtxBattleAction, "ctx.hit": TokCtxHit,
	"ctx.source": TokCtxSource, "ctx.action_kind": TokCtxActionKind,
	"ctx.penetrate": TokCtxPenetrate, "ctx.action_context": TokCtxActionContext,
	"ctx.paid": TokCtxPaid, "ctx.need_target": TokCtxNeedTarget,
	"ctx.absorbed": TokCtxAbsorbed,
}

var methodMap = map[string]int{
	"get": TokMGet, "set": TokMSet, "add": TokMAdd, "sub": TokMSub,
	"cmin": TokMCmin, "cmax": TokMCmax,
	"get_at": TokMGetAt, "set_at": TokMSetAt, "add_at": TokMAddAt, "sub_at": TokMSubAt,
	"decay_all": TokMDecayAll, "fill_all": TokMFillAll,
	"hp": TokMHp, "energy": TokMEnergy, "alive": TokMAlive,
	"owner_player": TokMOwnerPlayer, "owner_char": TokMOwnerChar,
	"name": TokMName, "element": TokMElement, "weapon": TokMWeapon,
	"normal_attack": TokMNormalAttack, // RC2 — `c.normal_attack` char-attr read
}

// kwArgMap — TableCtor field keys used as kwargs to builtin calls in
// hook bodies. Compiler maps these strings to TokKw* tokens for
// OpKwArg ops. Audit shows deal_damage is the only hook-body caller
// using TableCtor; the listed keys cover its observed kwargs.
var kwArgMap = map[string]int{
	"source":           TokKwSource,
	"target_counter":   TokKwTargetCounter,
	"other_characters": TokKwOtherCharacters,
	"actor":            TokKwActor,
	"element":          TokKwElement,
	"target":           TokKwTarget,
	"penetrate":        TokKwPenetrate,
	"react":            TokKwReact,
}

// bridgeMap — engine-managed Lua global table names that compiler
// pattern-matches into OpCall with one of these token IDs.
var bridgeMap = map[string]int{
	"_chars":        TokBridgeChars,
	"_char_by_slot": TokBridgeCharBySlot,
}
