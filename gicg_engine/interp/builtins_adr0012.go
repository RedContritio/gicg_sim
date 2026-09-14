package interp

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
)

// ADR-0012 spike: prepare-skill state + draw_card + add_dice +
// element_to_dice_color。Registered from RegisterBuiltins in builtins.go.
func (rt *Runtime) registerADR0012Builtins() {
	g := rt.Interp.Global

	// Prepare-skill state. set_preparing(player, skill_id) stores skill_id
	// in Game.Preparing[p]; flipTurn auto-resolves it next time that
	// player's turn comes up. get_preparing returns 0 when no skill
	// queued. clear_preparing resets to 0 (used when an effect cancels
	// the prepare — e.g. freeze).
	g.SetLocal("set_preparing", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		p, _ := ToInt(args[0])
		var skillID int
		switch v := args[1].(type) {
		case *SkillRef:
			skillID = v.ID
		case *LazySkillRef:
			if resolved := v.Resolve(rt); resolved != nil {
				skillID = resolved.ID
			}
		case int:
			skillID = v
		}
		rp := rt.ResolvePlayer(p)
		if rp >= 0 && rp <= 1 {
			rt.Game.Preparing[rp] = skillID
		}
		return nil, nil
	}))
	g.SetLocal("get_preparing", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		p, _ := ToInt(args[0])
		rp := rt.ResolvePlayer(p)
		if rp < 0 || rp > 1 {
			return 0, nil
		}
		return rt.Game.Preparing[rp], nil
	}))
	g.SetLocal("clear_preparing", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		p, _ := ToInt(args[0])
		rp := rt.ResolvePlayer(p)
		if rp >= 0 && rp <= 1 {
			rt.Game.Preparing[rp] = 0
		}
		return nil, nil
	}))

	// draw_card(player, n) — draw n cards from deck top to hand. Already
	// existing internal Game.DrawCard handles single draws and graceful
	// empty-deck behavior; this loops it.
	g.SetLocal("draw_card", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		p, _ := ToInt(args[0])
		n, _ := ToInt(args[1])
		rp := rt.ResolvePlayer(p)
		if rp < 0 || rp > 1 {
			return nil, nil
		}
		for i := 0; i < n; i++ {
			rt.Game.DrawCard(rp)
		}
		return nil, nil
	}))

	// add_dice(player, element_index, n) — increment the player's dice
	// counter for the given color by n. Color indices match DiceColor*
	// constants (0=fire … 7=omni). Doesn't interact with FixDice (which
	// is enforced at round-roll time); add_dice mid-round is treated as
	// an extra resource grant. ADR-0012 D2.
	g.SetLocal("add_dice", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		p, _ := ToInt(args[0])
		elem, _ := ToInt(args[1])
		n, _ := ToInt(args[2])
		rp := rt.ResolvePlayer(p)
		if rp < 0 || rp > 1 || n <= 0 {
			return nil, nil
		}
		if elem < 0 || elem >= engine.DiceColorCount {
			return nil, fmt.Errorf("add_dice: element index %d out of range [0,%d)", elem, engine.DiceColorCount)
		}
		rt.Game.Counters[rt.diceSlot(rp, elem)].Value += n
		return nil, nil
	}))

	// element_to_dice_color(element) — map a game Element enum value to
	// the DiceColor index the dice APIs (add_dice / get_dice_count)
	// expect. The two enums are intentionally distinct spaces
	// (Element.None occupies 0, so Element.Fire=1 ≠ DiceColor.Fire=0);
	// this builtin is the only supported bridge. Non-elemental input
	// (None / Physical / Piercing) has no dice color and raises.
	g.SetLocal("element_to_dice_color", GoFunc(func(rt *Runtime, args []Value) (Value, error) {
		e, _ := ToInt(args[0])
		color := engine.ElementToDiceColor(engine.Element(e))
		if color < 0 {
			return nil, fmt.Errorf("element_to_dice_color: element %d has no dice color", e)
		}
		return color, nil
	}))
}
