package engine

// CanAfford reports whether the given dice pool can pay the given
// cost. pool indexes by DiceColor: pool[0..6] = fire..dendro,
// pool[7] = omni. Omni can substitute for any specific color, for
// the same-color (Match) slot, and for any-color slots.
//
// The check treats omni as a wildcard pool: specific shortfalls are
// filled from omni first. Then Match (if any) requires some color c
// where remaining_native[c] + remaining_omni ≥ cost.Match. Any is
// satisfied by whatever dice remain after Specific and Match.
func CanAfford(pool [DiceColorCount]int, cost DiceCost) bool {
	omniLeft := pool[DiceColorOmni]
	// Specific: use native first, omni to fill shortfall. Track the
	// per-color remainder so the Match check below can pick any
	// single-color column to satisfy the same-color requirement.
	remaining := [DiceColorCount]int{}
	for color, need := range cost.Specific {
		have := pool[color]
		if have >= need {
			remaining[color] = have - need
			continue
		}
		short := need - have
		if omniLeft < short {
			return false
		}
		omniLeft -= short
		remaining[color] = 0
	}
	remaining[DiceColorOmni] = omniLeft

	// Match: pick any single color c (0..6) whose remainder plus the
	// remaining omni covers cost.Match. Omni-only payment is covered
	// when native_c == 0 and omni_left ≥ Match, appearing under every
	// color choice (all collapse to the same multiset post-dedup in
	// enumeration). CanAfford only needs existence.
	if cost.Match > 0 {
		feasible := false
		for c := 0; c < 7; c++ {
			if remaining[c]+remaining[DiceColorOmni] >= cost.Match {
				feasible = true
				break
			}
		}
		if !feasible {
			return false
		}
	}

	// Any-slots: the total dice not yet committed to Specific or
	// Match must be ≥ cost.Any. We compute total(pool) − sum(Specific)
	// − Match directly; Specific and Match each consume exactly that
	// many dice from the pool regardless of how native/omni split.
	total := 0
	for _, v := range pool {
		total += v
	}
	specDemand := 0
	for _, n := range cost.Specific {
		specDemand += n
	}
	return total-specDemand-cost.Match >= cost.Any
}

// multisetKey returns a canonical key for a [DiceColorCount]int8
// payment multiset, used to deduplicate equivalent payments during
// enumeration. Two orderings of the same multiset produce the same key.
func multisetKey(m [DiceColorCount]int8) [DiceColorCount]int8 {
	return m // already canonical: indexed by color, same color same slot
}

// EnumerateCostPayments returns all distinct payment multisets (each
// as a count-per-color vector) that can satisfy the given cost from
// the given dice pool. Payments are deduplicated by multiset identity
// (order within a payment is meaningless).
//
// Returned slices are independent copies; callers may freely store
// them as Action.DicePayment without aliasing.
//
// Three-phase enumeration:
//  1. Specific: each specific-color slot independently picks how many
//     omni substitute. Omni fungibility across specific slots is
//     captured by carrying a running omni-used count in the prefix.
//  2. Match (if any): for each specific prefix, choose a single color
//     c ∈ {0..6} and enumerate (native_c, omni_use) splits totalling
//     cost.Match. Omni-only payments appear under every color choice
//     and collapse to one multiset post-dedup.
//  3. Any: for each (specific + match) prefix, enumerate size-cost.Any
//     multisets of the remaining pool.
//
// Final dedup by multiset key removes cross-path duplicates (e.g.,
// all-omni Match under c=fire vs c=ice yield the same multiset).
func EnumerateCostPayments(pool [DiceColorCount]int, cost DiceCost) [][DiceColorCount]int8 {
	if !CanAfford(pool, cost) {
		return nil
	}

	specific := cost.Specific
	anyN := cost.Any
	seen := make(map[[DiceColorCount]int8]bool)
	var out [][DiceColorCount]int8

	// Step 1: enumerate specific-part payments (for each specific color
	// requirement, choose how many omni to substitute).
	var specPayments [][DiceColorCount]int8
	specPayments = append(specPayments, [DiceColorCount]int8{})
	for color := 0; color < 7; color++ {
		need := specific[color]
		if need == 0 {
			continue
		}
		var next [][DiceColorCount]int8
		for _, prev := range specPayments {
			// omniUse = number of omni substituted for this specific color
			// non-omni use = need - omniUse, must not exceed dice pool of this color
			for omniUse := 0; omniUse <= need; omniUse++ {
				nativeUse := need - omniUse
				if nativeUse > pool[color]-int(prev[color]) {
					continue
				}
				if omniUse > pool[DiceColorOmni]-int(prev[DiceColorOmni]) {
					continue
				}
				p := prev
				p[color] += int8(nativeUse)
				p[DiceColorOmni] += int8(omniUse)
				next = append(next, p)
			}
		}
		specPayments = next
	}

	// Step 2 (optional): extend each spec prefix with a Match payment.
	// Pick one of 7 specific colors as the "match color"; enumerate
	// omni substitution within it. Leave specPayments untouched when
	// Match is 0 so the downstream Any loop stays one-liner.
	matchPrefixes := specPayments
	if cost.Match > 0 {
		matchPrefixes = matchPrefixes[:0] // reuse underlying storage
		for _, prev := range specPayments {
			var remaining [DiceColorCount]int
			for i := 0; i < DiceColorCount; i++ {
				remaining[i] = pool[i] - int(prev[i])
			}
			for c := 0; c < 7; c++ {
				for omniUse := 0; omniUse <= cost.Match; omniUse++ {
					nativeUse := cost.Match - omniUse
					if nativeUse > remaining[c] {
						continue
					}
					if omniUse > remaining[DiceColorOmni] {
						continue
					}
					p := prev
					p[c] += int8(nativeUse)
					p[DiceColorOmni] += int8(omniUse)
					matchPrefixes = append(matchPrefixes, p)
				}
			}
		}
	}

	// Step 3: for each (specific + match) prefix, enumerate any-payment
	// multisets (which dice to spend for the any-cost portion).
	for _, prefix := range matchPrefixes {
		var remaining [DiceColorCount]int
		for i := 0; i < DiceColorCount; i++ {
			remaining[i] = pool[i] - int(prefix[i])
		}
		anyCombos := enumerateMultiset(remaining, int(anyN))
		for _, combo := range anyCombos {
			total := prefix
			for i := 0; i < DiceColorCount; i++ {
				total[i] += combo[i]
			}
			key := multisetKey(total)
			if seen[key] {
				continue
			}
			seen[key] = true
			out = append(out, total)
		}
	}
	return out
}

// enumerateMultiset returns all distinct multisets of size n drawable
// from the given pool of dice. Each returned slot is a count-per-color
// int8 array.
func enumerateMultiset(pool [DiceColorCount]int, n int) [][DiceColorCount]int8 {
	if n == 0 {
		return [][DiceColorCount]int8{{}}
	}
	var out [][DiceColorCount]int8
	var rec func(startColor, remaining int, current [DiceColorCount]int8)
	rec = func(startColor, remaining int, current [DiceColorCount]int8) {
		if remaining == 0 {
			cp := current
			out = append(out, cp)
			return
		}
		if startColor >= DiceColorCount {
			return
		}
		maxHere := pool[startColor]
		if maxHere > remaining {
			maxHere = remaining
		}
		for take := 0; take <= maxHere; take++ {
			current[startColor] = int8(take)
			rec(startColor+1, remaining-take, current)
		}
		current[startColor] = 0
	}
	rec(0, n, [DiceColorCount]int8{})
	return out
}
