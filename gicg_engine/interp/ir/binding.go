package ir

// TypedBindingKind classifies a closure-captured local declared OUTSIDE
// the hook body (the result of declare_counter/card/char/skill).
type TypedBindingKind int16

const (
	BindingCounter  TypedBindingKind = 1
	BindingCard     TypedBindingKind = 2
	BindingChar     TypedBindingKind = 3
	BindingSkill    TypedBindingKind = 4
	BindingReaction TypedBindingKind = 5
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
	}
	return "Unknown"
}

// TypedBinding pairs a closure-captured ident with its engine-assigned ID.
// The ID is opaque to the compiler — it only stamps it into AddrLocalVar
// loads and (for counter methods) AddrCounter loads/stores.
type TypedBinding struct {
	Kind TypedBindingKind
	ID   int16
}
