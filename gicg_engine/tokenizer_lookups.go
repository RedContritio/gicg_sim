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

// LookupKwArg returns the token ID for a TableCtor field key used as a
// kwarg to a builtin call (TokKwSource, TokKwElement, …) or
// (0, false) if not registered.
func LookupKwArg(key string) (int16, bool) {
	id, ok := kwArgMap[key]
	return int16(id), ok
}

// LookupBridge returns the token ID for an engine-managed global table
// name (_chars → TokBridgeChars, _char_by_slot → TokBridgeCharBySlot)
// or (0, false) if not registered.
func LookupBridge(name string) (int16, bool) {
	id, ok := bridgeMap[name]
	return int16(id), ok
}

// ReverseLookup inverts a name→id map; used by diagnostic / showcase tools
// that decode IR ops back to source-level names. Returns ("", false) if
// no name maps to id. Kind selects which map to scan.
//
// Kind values: "builtin" / "ctx_field" / "enum" / "method" / "kwarg" / "bridge".
func ReverseLookup(kind string, id int16) (string, bool) {
	var m map[string]int
	switch kind {
	case "builtin":
		m = tokenMap
	case "ctx_field":
		m = ctxFieldMap
	case "enum":
		m = enumMap
	case "method":
		m = methodMap
	case "kwarg":
		m = kwArgMap
	case "bridge":
		m = bridgeMap
	default:
		return "", false
	}
	for name, candidate := range m {
		if int16(candidate) == id {
			return name, true
		}
	}
	return "", false
}
