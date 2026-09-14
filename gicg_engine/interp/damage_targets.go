package interp

// filterDamageTargets snapshots eligible targets before the first hit. This
// selects existing targets; it does not change actor attribution or write the
// selector counter. Counter consumption remains an explicit DSL operation.
func (rt *Runtime) filterDamageTargets(hpIDs []int, selector *PerCharProxy) []int {
	selected := make([]int, 0, len(hpIDs))
	for _, hp := range hpIDs {
		slot := rt.Game.GetCounterChar(hp)
		p, c := slot[0], slot[1]
		if p < 0 || p > 1 || c < 0 || c >= MaxChars {
			continue
		}
		id := selector.IDs[p*MaxChars+c]
		if id >= 0 && rt.Game.ReadCounter(id) > 0 {
			selected = append(selected, hp)
		}
	}
	return selected
}

// Select relative to the original victim, including when it has died or moved.
func (rt *Runtime) otherCharacterHP(ch *CharProxy) []int {
	var ids []int
	for index, entry := range rt.Chars.BySlot[ch.Entry.PlayerIdx] {
		if entry != nil && index != ch.Entry.CharIdx && rt.Game.Players[ch.Entry.PlayerIdx].Chars[index].Alive {
			ids = append(ids, entry.HPCounterID)
		}
	}
	return ids
}
