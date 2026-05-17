package interp

import (
	"fmt"
)

// Proxies hold only immutable lookup data (counter IDs, entry references).
// They do not store a Runtime pointer, because a single proxy instance is
// shared by every Runtime that plays against the same Ruleset. Each method
// call receives the currently-executing Runtime as a parameter; the proxy
// routes through rt.Game / rt.CurrentContextPlayer / etc.

// wrapRef converts the raw int value stored in a ref-tagged counter
// into the corresponding typed Value (*SkillRef / *CardRef) for DSL
// consumption. The sentinel value -1 means "no ref" → returns nil.
func wrapRef(rt *Runtime, kind int, v int) Value {
	if v < 0 {
		return nil
	}
	switch kind {
	case RefKindSkill:
		if ref, ok := rt.Skills.ByID[v]; ok {
			return ref
		}
		return nil
	case RefKindCard:
		if ref, ok := rt.Cards.ByRef[v]; ok {
			return ref
		}
		return nil
	default:
		return v
	}
}

// unwrapRef converts a DSL-supplied ref Value back to the int that
// will be stored in the counter. nil becomes -1. Raw int passes
// through. Kind-mismatch (passing a CardRef to a skill counter) is
// an error. For raw counters, falls through to ToInt.
func unwrapRef(kind int, v Value) (int, error) {
	if v == nil {
		return -1, nil
	}
	switch kind {
	case RefKindSkill:
		if ref, ok := v.(*SkillRef); ok && ref != nil {
			return ref.ID, nil
		}
		return 0, fmt.Errorf("expected *SkillRef or nil, got %T", v)
	case RefKindCard:
		if ref, ok := v.(*CardRef); ok && ref != nil {
			return ref.Ref, nil
		}
		return 0, fmt.Errorf("expected *CardRef or nil, got %T", v)
	default:
		n, ok := ToInt(v)
		if !ok {
			return 0, fmt.Errorf("expected int, got %T", v)
		}
		return n, nil
	}
}

// refArithForbidden reports an error for add/sub ops on ref counters.
// Ref identity is not a numeric quantity.
func refArithForbidden(kind int, op string) error {
	return fmt.Errorf("cannot %s on ref-tagged counter (kind=%d)", op, kind)
}

// --- Counter proxies ---
//
// Per-slot (single counter ID or pair): proxies_counter.go
//   CounterProxy, PerPlayerProxy, SelfSlotProxy
//
// Multi-slot bucket proxies: proxies_bucket.go
//   PerCharProxy, PerPlayerView, CounterGroupProxy
//
// Char / Skill proxies: proxies_char.go
//   CharProxy, LazyCharProxy, LazySkillRef
//
// EventContext proxy: proxies_ctx.go
//   CtxProxy
