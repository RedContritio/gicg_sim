package engine

// Token type constants — the ~200 ID vocabulary the DSL tokenizer
// emits: keywords, operators, API calls, enums, ctx fields, methods, literals.

const (
	TokPad = 0

	// Keywords (1-19)
	TokIf       = 1
	TokThen     = 2
	TokEnd      = 3
	TokReturn   = 4
	TokElseif   = 5
	TokElse     = 6
	TokLocal    = 7
	TokFunction = 8
	TokAnd      = 9
	TokOr       = 10
	TokNot      = 11
	TokTrue     = 12
	TokFalse    = 13
	TokNil      = 14

	// Operators (20-39)
	TokEq     = 20 // ==
	TokNeq    = 21 // ~=
	TokLt     = 22 // <
	TokGt     = 23 // >
	TokLe     = 24 // <=
	TokGe     = 25 // >=
	TokAdd    = 26 // +
	TokSub    = 27 // -
	TokMul    = 28 // *
	TokDiv    = 29 // /
	TokAssign = 30 // =
	TokDot    = 31 // .
	TokColon  = 32 // :
	TokComma  = 33 // ,
	TokLParen = 34 // (
	TokRParen = 35 // )
	TokLBrace = 36 // {
	TokRBrace = 37 // }

	// API calls (40-79)
	TokDeclareCounter     = 40
	TokGetCounter         = 41
	TokGetCounterGroup    = 42
	TokRegisterOnTagWrite = 43
	TokDeclareChar        = 44
	TokGetChar            = 45
	TokDeclareSkill       = 46
	TokGetSkill           = 47
	TokInvokeSkill        = 48
	TokDeclareCard        = 49
	TokGetCard            = 50
	TokAddCard            = 51
	TokDealDamage         = 52
	TokHeal               = 53
	TokDeferFn            = 54
	TokGetActiveChar      = 55
	TokSetActiveChar      = 56
	TokGetNextChar        = 57
	TokContextPlayer      = 58
	TokForceSwitch        = 59
	TokGainEnergy         = 60
	TokConsumeEnergy      = 61
	TokSetWinner          = 62
	TokGetTurn            = 63
	TokDrawCard           = 64
	TokCancel             = 65
	TokMin                = 66
	TokMax                = 67
	TokPcall              = 68

	// Hook types (80-109; 80/82 reserved — 旧 HookDamageBoost/Reduce 已 ADR-0019 §B.5 删除)
	TokOnReactionDamage      = 81
	TokOnAfterDamage         = 83
	TokOnBeforeHeal          = 84
	TokOnAfterHeal           = 85
	TokOnActionCheck         = 86
	TokOnActionPrepare       = 87
	TokOnSkillUse            = 88
	TokOnCardPlay            = 89
	TokOnSwitch              = 90
	TokOnBeforeTurnFlip      = 91
	TokOnRoundStart          = 92
	TokOnRoundEnd            = 93
	TokOnRoundEndPostSummon  = 94
	TokOnRoundEndDecay       = 95
	TokOnRoundEndFinal       = 96
	TokOnBeforeWrite         = 97
	TokOnAfterWrite          = 98
	TokOnBeforeEnergyGain    = 99
	TokOnAfterEnergyGain     = 100
	TokOnBeforeEnergyConsume = 101
	TokOnAfterEnergyConsume  = 102
	// ADR-0019 §B.5 — strict 4+3 hook 时机
	TokOnDamageType       = 103
	TokOnDamageAdd        = 104
	TokOnDamageMul        = 105
	TokOnDamageReduceBuff = 106
	TokOnShieldAbsorb     = 107
	TokOnDamageImmunity   = 108
	// ADR-0019 §A.4 / dsl_gaps D3 — 调和 hook
	TokOnTune = 109

	// Enum prefixes (110-179)
	TokElementNone     = 110
	TokElementFire     = 111
	TokElementIce      = 112
	TokElementWater    = 113
	TokElementElectro  = 114
	TokElementGeo      = 115
	TokElementPhysical = 116
	TokElementAnemo    = 117
	TokElementDendro   = 118
	TokElementPiercing = 119 // ADR-0019 §B.1: 穿透 = 元素类型,不是 modifier flag

	TokTargetEnemyActive    = 120
	TokTargetEnemyAll       = 121
	TokTargetOwnAll         = 122
	TokTargetEnemyNonActive = 123
	TokTargetOwnActive      = 124
	TokTargetCardTarget     = 125

	TokScopeSelf         = 130
	TokScopeActiveStatus = 131
	TokScopePerChar      = 132
	TokScopePerPlayer    = 133
	TokScopeGlobal       = 134

	TokOpSet = 140
	TokOpAdd = 141
	TokOpSub = 142

	TokSourceSkill    = 150
	TokSourceCard     = 151
	TokSourceStatus   = 152
	TokSourceSummon   = 153
	TokSourceSupport  = 154
	TokSourceReaction = 155

	TokTagSummon    = 160
	TokTagElement   = 161
	TokTagEquip     = 162
	TokTagFood      = 163
	TokTagSupport   = 164
	TokTagShield    = 165
	TokTagSpecialty = 166

	TokPlayerOwn   = 170
	TokPlayerEnemy = 171
	TokPlayerAll   = 172

	TokWeaponNone     = 180
	TokWeaponSword    = 181
	TokWeaponPolearm  = 182
	TokWeaponBow      = 183
	TokWeaponClaymore = 184
	TokWeaponCatalyst = 185

	TokSlotNone      = 200
	TokSlotEquip     = 201
	TokSlotSupport   = 202
	TokSlotSpecialty = 203

	TokActionKindSkill   = 190
	TokActionKindCard    = 191
	TokActionKindSwitch  = 192
	TokActionKindEndTurn = 193

	TokZoneHand = 196
	TokZoneDeck = 197

	// ctx fields (200-219)
	TokCtxValue        = 200
	TokCtxElement      = 201
	TokCtxActorPlayer  = 202
	TokCtxActorChar    = 203
	TokCtxSkillIndex   = 204
	TokCtxCardRef      = 205
	TokCtxTargetPlayer = 206
	TokCtxTargetChar   = 207
	TokCtxPlayable     = 208
	// 209 retired: was TokCtxApCost (AP system removed Phase IV.c+d)
	TokCtxBattleAction  = 210
	TokCtxHit           = 211
	TokCtxSource        = 212
	TokCtxActionKind    = 213
	TokCtxPenetrate     = 214
	TokCtxActionContext = 215
	TokCtxPaid          = 216
	TokCtxNeedTarget    = 217
	TokCtxAbsorbed      = 218 // ADR-0019 §B.5 ctx.absorbed(以逸待劳类反击 idiom)

	// Methods (220-239)
	TokMGet         = 220
	TokMSet         = 221
	TokMAdd         = 222
	TokMSub         = 223
	TokMCmin        = 224
	TokMCmax        = 225
	TokMGetAt       = 226
	TokMSetAt       = 227
	TokMAddAt       = 228
	TokMSubAt       = 229
	TokMDecayAll    = 230
	TokMFillAll     = 231
	TokMHp          = 232
	TokMEnergy      = 233
	TokMAlive       = 234
	TokMOwnerPlayer = 235
	TokMOwnerChar   = 236
	TokMName        = 237
	TokMElement     = 238
	TokMWeapon      = 239

	// Literals (240-249)
	TokLitNumber = 240 // next value = the number
	TokLitString = 241 // next value = string hash

	// References (250-252)
	TokVarRef = 250 // local variable reference (next = var index in scope)

	// IR-1.6 kwarg keys (260-279) — TableCtor field keys used as
	// kwargs to builtin calls in hook bodies (deal_damage etc.).
	// Compiler emits OpKwArg(key=TokKw*, value=reg) immediately before
	// the OpCall that consumes them.
	TokKwSource        = 260
	TokKwElement       = 261
	TokKwTarget        = 262
	TokKwPenetrate     = 263
	TokKwReact         = 264
	TokKwTargetCounter = 265

	// IR-1.6 bridge global accessors (290-299) — Lua tables populated at
	// engine init (_chars[i], _char_by_slot[p][c]); compiler pattern-matches
	// IndexAccess on these names into OpCall with one of these token IDs.
	TokBridgeChars      = 290
	TokBridgeCharBySlot = 291

	// RC2 builtins (300-319): opaque OpCall tokens dispatched through Op1.
	TokRollDice         = 300
	TokClearDicePool    = 301
	TokSetReactionKind  = 302
	TokCostTotal        = 303
	TokCostMod          = 304
	TokWasApplied       = 305
	TokAddDice          = 306
	TokSetPreparing     = 307
	TokHasCardInOwnHand = 308
	TokRemoveSupport    = 309
	// element_to_dice_color — Element enum → DiceColor index bridge
	// (the two spaces are offset by one: Element.None occupies 0).
	TokElementToDiceColor = 310
	TokRegisterBuff       = 313
	TokKwActor            = 314
	TokIsCharAlive        = 315
	TokCostReduce         = 312 // restricted-first total dice discount
	TokRequestSwitch      = 311 // deferred player input; distinct from automatic force_switch

	// Normal attack attribute shares method-token AddrCharAttr lookup.
	TokMNormalAttack = 319

	// CostSlot / DiceColor enums: opaque NN embeddings, resolved via enumMap.
	TokCostSlotFire    = 320
	TokCostSlotIce     = 321
	TokCostSlotWater   = 322
	TokCostSlotElectro = 323
	TokCostSlotGeo     = 324
	TokCostSlotAnemo   = 325
	TokCostSlotDendro  = 326
	TokCostSlotMatch   = 327
	TokCostSlotAny     = 328
	TokCostSlotAll     = 329

	TokDiceColorFire    = 330
	TokDiceColorIce     = 331
	TokDiceColorWater   = 332
	TokDiceColorElectro = 333
	TokDiceColorGeo     = 334
	TokDiceColorAnemo   = 335
	TokDiceColorDendro  = 336
	TokDiceColorOmni    = 337

	TokVocabSize = 512
)
