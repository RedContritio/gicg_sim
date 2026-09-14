package engine

// Program vocabulary extends existing execution entities, without exposing
// continuation roots, future randomness or the opponent's dice choices.
const (
	ProgramDiceSelection = 4
	ProgramDiceColor     = 5
)

func (g *Game) writeDiceSelectionObs(out []int32, perspective, row int) int {
	f := g.PendingDice
	write := func(program, color, available, selected, remaining int) {
		if row >= ObsBuffRows {
			panic("dice selection observation capacity exceeded")
		}
		values := []int32{1, relativePlayer(f.Player, perspective), -1, int32(available), int32(remaining),
			int32(selected), 0, -1, int32(program), int32(color), 0, 0, EntityExecutionFrame, -1, -1, -1}
		copy(out[row*ObsBuffFields:], values)
		row++
	}
	if perspective == f.Player {
		write(ProgramDiceSelection, f.Color, 0, 0, f.Remaining)
		for color := range f.Pool {
			write(ProgramDiceColor, color, f.Pool[color], f.Selected[color], f.Remaining)
		}
	} else {
		write(ProgramDiceSelection, -1, 0, 0, 0)
	}
	return g.writePublicCauseObs(out, perspective, row, g.BuildRawToActiveHookIdx())
}
