package engine

// ForceSwitchTo is a rule-driven, free switch. It shares event dispatch and
// deferred-effect handling with death/manual switches but never pays dice,
// prepares a voluntary action, or flips the turn. No change means no event.
func (g *Game) ForceSwitchTo(player, char int) {
	if player < 0 || player >= len(g.Players) {
		panic("forced switch: invalid player")
	}
	p := &g.Players[player]
	if char < 0 || char >= len(p.Chars) || !p.Chars[char].Alive {
		panic("forced switch: invalid or dead target")
	}
	if p.ActiveChar == char {
		return
	}
	g.executeSwitch(Action{Kind: ActionSwitch, PlayerIdx: player, Index: char, Forced: true}, ActForcedReaction)
}
