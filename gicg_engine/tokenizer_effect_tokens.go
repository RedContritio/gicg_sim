package engine

// Appended effect API tokens. Keep existing numbers stable; IDs remain below
// TokVocabSize, including when an effect builtin also has an execution handler.
const (
	TokSpawnBuff                = 350
	TokBuffDuration             = 351
	TokSetBuffDuration          = 352
	TokForceSwitchPrevious      = 353
	TokKwOtherCharacters        = 354
	TokApplyElement             = 355
	TokCtxAttachmentOnly        = 356
	TokOnAfterReaction          = 357
	TokCtxReactionElement       = 358
	TokSpawnSupportBuff         = 359
	TokBuffProgress             = 360
	TokSetBuffProgress          = 361
	TokGetDiceTotal             = 362
	TokCtxReactionKind          = 363
	TokSelectedBuff             = 364
	TokBackgroundEnergy         = 365
	TokTransferBackgroundEnergy = 366
	TokChooseReroll             = 367
)
