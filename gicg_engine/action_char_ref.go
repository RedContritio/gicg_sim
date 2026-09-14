package engine

// ActionCharRef is the third semantic action-reference field. Switches use
// an own character slot. Targeted cards use own-first slots: own 0..5,
// enemy 6..11. Tune uses the source die color. Other untargeted actions
// use -1. Shared by C API and Go actors.
func ActionCharRef(a Action) int {
	if a.Kind == ActionReroll {
		if a.RerollColor < 0 || a.RerollColor > DiceColorCount || a.Index < 0 || (a.RerollColor == DiceColorCount && a.Index != 0) {
			panic("invalid semantic reroll choice")
		}
		return a.RerollColor
	}
	if a.Kind == ActionCard && a.HasSupportTarget {
		if a.TargetSupport < 0 || a.TargetSupport >= MaxSupportSlots {
			panic("invalid semantic support target")
		}
		return -2 - ObsBuffRows - a.TargetSupport
	}
	if a.Kind == ActionCard && a.HasBuffTarget {
		if a.TargetBuff < 0 {
			panic("invalid semantic buff target")
		}
		return -2 - a.TargetBuff
	}
	if a.Kind == ActionTune {
		return a.TuneSourceColor
	}
	if a.Kind == ActionSwitch {
		return a.Index
	}
	if a.Kind != ActionCard || !a.HasTarget {
		return -1
	}
	if a.TargetPlayer < 0 || a.TargetPlayer > 1 || a.TargetChar < 0 || a.TargetChar >= ObsMaxChars {
		panic("invalid semantic card target")
	}
	slot := a.TargetChar
	if a.TargetPlayer != a.PlayerIdx {
		slot += ObsMaxChars
	}
	return slot
}
