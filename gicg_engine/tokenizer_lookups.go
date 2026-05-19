package engine

// Exported read-only accessors over the unexported lookup maps in
// tokenizer_maps.go. Added for the AST→IR compiler in
// gicg_engine/interp/ir/, which needs the same string→token-ID lookups
// that TokenizeLua uses but without copying the maps. Token IDs are
// canonical and shared with the encoder (Python) embedding tables.
//
// Return int16 (not int) to match the IR Op-field type and remove
// per-call-site casts at every consumer.

// LookupCtxField returns the token ID for "ctx.<field>" (TokCtxValue,
// TokCtxHit, …) or (0, false) if not registered.
func LookupCtxField(field string) (int16, bool) {
	id, ok := ctxFieldMap["ctx."+field]
	return int16(id), ok
}

// LookupEnum returns the token ID for "<Namespace>.<Name>"
// (TokElementFire, TokSourceSkill, …) or (0, false) if not registered.
func LookupEnum(qualified string) (int16, bool) {
	id, ok := enumMap[qualified]
	return int16(id), ok
}

// LookupMethod returns the token ID for an unqualified method name
// (TokMGet, TokMHp, …) or (0, false) if not registered.
func LookupMethod(name string) (int16, bool) {
	id, ok := methodMap[name]
	return int16(id), ok
}

// LookupBuiltin returns the token ID for an unqualified builtin /
// keyword name (TokDeclareCounter, TokDealDamage, TokMin, …) or
// (0, false) if not registered.
func LookupBuiltin(name string) (int16, bool) {
	id, ok := tokenMap[name]
	return int16(id), ok
}
