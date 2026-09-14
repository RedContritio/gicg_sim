package engine

// CostSlot identifies one slot in COST space. Cost space has 9 real
// slots (7 specific elements + match + any), plus a sentinel "All"
// that applies a mutation to every real slot at once.
//
// Cost space is DISTINCT from pool space (DiceColor). Pool has omni
// as a wildcard payment token; cost has match (N same-color) and any
// (N any-color) as requirement types. Omni does not exist in cost
// space, match and any do not exist in pool space.
type CostSlot int8

const (
	CostFire    CostSlot = 0 // indices 0..6 match DiceColor constants
	CostIce     CostSlot = 1
	CostWater   CostSlot = 2
	CostElectro CostSlot = 3
	CostGeo     CostSlot = 4
	CostAnemo   CostSlot = 5
	CostDendro  CostSlot = 6
	CostMatch   CostSlot = 7
	CostAny     CostSlot = 8
	CostAll     CostSlot = 9 // sentinel: apply delta to every real slot
)

// DiceCost is the dice-portion requirement of an action. Lives in
// cost space (9 slots: 7 specific + match + any).
//
//   - Specific[i] = N dice of exact color i required (fire..dendro).
//     Omni dice substitute at payment time.
//   - Match = N dice of the same (any) color. Player picks the color
//     at payment time. Omni substitutes for any of the N slots (so
//     k native + (Match−k) omni is a valid payment for any k ∈
//     [0, Match]).
//   - Any = N dice of any color.
type DiceCost struct {
	Specific [7]int
	Match    int
	Any      int
}

// Total returns the total number of dice this cost requires, summing
// all 9 real slots. Values may be negative if caller hasn't Clamped.
func (c DiceCost) Total() int {
	t := c.Match + c.Any
	for _, n := range c.Specific {
		t += n
	}
	return t
}

// IsEmpty reports whether every real slot is zero (or negative).
func (c DiceCost) IsEmpty() bool {
	for _, n := range c.Specific {
		if n > 0 {
			return false
		}
	}
	return c.Match <= 0 && c.Any <= 0
}

// Mod adds delta to the slot identified by s.
//
//   - For real slots (Fire..Dendro, Match, Any), delta is added to
//     that specific slot.
//   - For CostAll, delta is added to every real slot.
//   - Unknown slots are a no-op.
//
// Negative intermediate values are allowed; call Clamp when done to
// normalize. This lets "add_cost(All, -99) + clamp" express "zero
// out every slot" without needing a dedicated zero primitive.
func (c *DiceCost) Mod(s CostSlot, delta int) {
	switch {
	case s >= 0 && s <= 6:
		c.Specific[s] += delta
	case s == CostMatch:
		c.Match += delta
	case s == CostAny:
		c.Any += delta
	case s == CostAll:
		for i := range c.Specific {
			c.Specific[i] += delta
		}
		c.Match += delta
		c.Any += delta
	}
}

// Reduce removes up to amount dice, specific elements first (enum order),
// then same-color requirements, then unrestricted dice. Nonpositive amounts
// do nothing; negative intermediate slots neither consume nor add budget.
func (c *DiceCost) Reduce(amount int) {
	reduce := func(slot *int) {
		if amount <= 0 || *slot <= 0 {
			return
		}
		n := min(amount, *slot)
		*slot -= n
		amount -= n
	}
	for i := range c.Specific {
		reduce(&c.Specific[i])
	}
	reduce(&c.Match)
	reduce(&c.Any)
}

// Clamp brings every slot to >= 0 in place. Call after all mods are
// applied, before handing the cost to EnumerateCostPayments.
func (c *DiceCost) Clamp() {
	for i := range c.Specific {
		if c.Specific[i] < 0 {
			c.Specific[i] = 0
		}
	}
	if c.Match < 0 {
		c.Match = 0
	}
	if c.Any < 0 {
		c.Any = 0
	}
}

// ClampedTotal returns the sum of all slots with negative values
// treated as zero. Used by the DSL cost_total builtin to evaluate the
// gate condition "is there still cost to discount".
func (c DiceCost) ClampedTotal() int {
	t := 0
	for _, n := range c.Specific {
		if n > 0 {
			t += n
		}
	}
	if c.Match > 0 {
		t += c.Match
	}
	if c.Any > 0 {
		t += c.Any
	}
	return t
}

// Cost is the full declaration-time requirement: dice + energy.
// Dice and energy are orthogonal resources — dice are never spent as
// energy, energy is never spent as dice.
type Cost struct {
	Dices  DiceCost
	Energy int
}

// TotalDice is a shortcut for Dices.Total().
func (c Cost) TotalDice() int {
	return c.Dices.Total()
}
