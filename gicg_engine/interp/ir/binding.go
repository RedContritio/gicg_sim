package ir

// TypedBindingKind classifies a closure-captured local declared OUTSIDE
// the hook body (the result of declare_counter/card/char/skill).
//
// BindingConst (RC2) — top-level numeric/bool constant, e.g.
// `local INITIAL_HAND = 5`. The compiler inlines these as OpLoadImm
// at every read site (binding.ConstValue carries the int16); the ID
// field stays opaque to match the other kinds' layout.
type TypedBindingKind int16

const (
	BindingCounter  TypedBindingKind = 1
	BindingCard     TypedBindingKind = 2
	BindingChar     TypedBindingKind = 3
	BindingSkill    TypedBindingKind = 4
	BindingReaction TypedBindingKind = 5
	BindingConst    TypedBindingKind = 6
)

// String — readable name for error messages (default %d would print raw int).
func (k TypedBindingKind) String() string {
	switch k {
	case BindingCounter:
		return "Counter"
	case BindingCard:
		return "Card"
	case BindingChar:
		return "Char"
	case BindingSkill:
		return "Skill"
	case BindingReaction:
		return "Reaction"
	case BindingConst:
		return "Const"
	}
	return "Unknown"
}

// TypedBinding pairs a closure-captured ident with its engine-assigned ID.
// The ID is opaque to the compiler — it only stamps it into AddrLocalVar
// loads and (for counter methods) AddrCounter loads/stores.
//
// For BindingConst, ConstValue holds the inline immediate; ID is unused
// (the compiler emits OpLoadImm and never references ID).
type TypedBinding struct {
	Kind       TypedBindingKind
	ID         int16
	ConstValue int16
}
