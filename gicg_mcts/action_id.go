package mcts

// ActionId uniquely identifies an MCTS action (skill/card/switch/
// end_turn + dice payment combo). Must match Python's build_action_id
// in training/mcts.py:
//
//	(identity[0], identity[1], identity[2], identity[3], identity[4],
//	 tuple(payment[0..7]))
//
// Two actions with identical identity but different dice payments are
// treated as distinct — the same logical skill fanned out over
// multiple legal dice combos.
//
// Stored flat for cache-friendly compare + hash (used as map key in
// Python; we compare by field here).
type ActionId struct {
	// From GameGetActionIdentities, 5 ints:
	//   kind:   0=skill, 1=card, 2=switch, 3=end_turn
	//   sub_a:  hook_idx or char_idx depending on kind
	//   sub_b:  aux field (skill index / card ref / -1)
	//   sub_c:  aux (reserved)
	//   sub_d:  aux (reserved)
	Kind int32
	SubA int32
	SubB int32
	SubC int32
	SubD int32
	// From GameGetLegalActionPayments, 8 ints (dice combo):
	//   [omni, fire, ice, water, electro, geo, anemo_grass, slot7]
	Payment [8]int32
}

// Less reports ActionId ordering for tie-break in PUCT and stable sort.
// Must match Python tuple comparison (lexicographic).
func (a ActionId) Less(b ActionId) bool {
	if a.Kind != b.Kind {
		return a.Kind < b.Kind
	}
	if a.SubA != b.SubA {
		return a.SubA < b.SubA
	}
	if a.SubB != b.SubB {
		return a.SubB < b.SubB
	}
	if a.SubC != b.SubC {
		return a.SubC < b.SubC
	}
	if a.SubD != b.SubD {
		return a.SubD < b.SubD
	}
	for i := 0; i < 8; i++ {
		if a.Payment[i] != b.Payment[i] {
			return a.Payment[i] < b.Payment[i]
		}
	}
	return false
}

// Equal reports ActionId equality (all 13 fields).
func (a ActionId) Equal(b ActionId) bool {
	return a.Kind == b.Kind && a.SubA == b.SubA && a.SubB == b.SubB &&
		a.SubC == b.SubC && a.SubD == b.SubD && a.Payment == b.Payment
}
