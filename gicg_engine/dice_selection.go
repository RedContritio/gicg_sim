package engine

import "fmt"

// DiceSelection is a value-only decision frame. Color==DiceColorCount asks
// for confirmation. Pool/Selected belong to the owner, never the opponent.
type DiceSelection struct {
	Player, Remaining, Color int
	Pool, Selected           [DiceColorCount]int
}

func copyDiceSelection(f *DiceSelection) *DiceSelection {
	if f == nil {
		return nil
	}
	copy := *f
	return &copy
}

func (g *Game) diceSelectionActions() []Action {
	f := g.PendingDice
	if f == nil {
		return nil
	}
	max := 0
	if f.Color < DiceColorCount {
		max = f.Pool[f.Color]
	}
	actions := make([]Action, max+1)
	for count := range actions {
		actions[count] = Action{Kind: ActionReroll, PlayerIdx: f.Player, Index: count, RerollColor: f.Color}
	}
	return actions
}

// ChooseReroll pauses its enclosing managed operation for each color and
// confirmation. No dice or random state changes until confirmation. After
// the final reroll, the interrupted rule continues exactly once.
func (g *Game) ChooseReroll(player, times int) {
	if player < 0 || player > 1 || times <= 0 || g.executing == nil {
		g.FailRule(fmt.Errorf("invalid reroll request or unmanaged operation"), -1)
	}
	rt := g.Extra.(DicePoolProvider)
	for remaining := times; remaining > 0; remaining-- {
		f := DiceSelection{Player: player, Remaining: remaining}
		for c := range f.Pool {
			f.Pool[c] = g.Counters[rt.DiceCounterID(player, c)].Value
		}
		for color, available := range f.Pool {
			if available == 0 {
				continue
			}
			f.Color = color
			f.Selected[color] = g.requestDiceInput(f)
		}
		f.Color = DiceColorCount
		g.requestDiceInput(f)
		// The confirmed branch owns its RNG; reconstruction must not use the
		// original root RNG when exploring another sampled continuation.
		total := 0
		for c, n := range f.Selected {
			cid := rt.DiceCounterID(player, c)
			if n > g.Counters[cid].Value {
				g.FailRule(fmt.Errorf("reroll selection exceeds current dice"), -1)
			}
			g.Counters[cid].Value -= n
			total += n
		}
		for range total {
			g.Counters[rt.DiceCounterID(player, g.Rng.Intn(DiceColorCount))].Value++
		}
	}
}

func (g *Game) requestDiceInput(frame DiceSelection) int {
	g.PendingDice = copyDiceSelection(&frame)
	x := g.executing
	if x.next == len(x.choices) {
		panic(inputSuspension{})
	}
	choice := x.choices[x.next]
	x.next++
	a := choice.action
	if a.Kind != ActionReroll || a.PlayerIdx != frame.Player || a.RerollColor != frame.Color ||
		choice.state.PendingDice == nil || *choice.state.PendingDice != frame || a.Index < 0 || a.Index >= len(g.diceSelectionActions()) {
		g.FailRule(fmt.Errorf("continuation dice selection changed"), -1)
	}
	g.restoreGameplay(choice.state)
	g.resume = nil
	g.PendingDice = nil
	g.logAction(a)
	return a.Index
}
