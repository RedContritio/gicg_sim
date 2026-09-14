package engine

import "testing"

func TestActionCharRef(t *testing.T) {
	for color := 0; color < DiceColorCount; color++ {
		if ActionCharRef(Action{Kind: ActionTune, TuneSourceColor: color}) != color {
			t.Fatal("tune source color lost")
		}
	}
	for _, player := range []int{0, 1} {
		for _, target := range []int{0, 1} {
			for char := 0; char < ObsMaxChars; char++ {
				a := Action{Kind: ActionCard, PlayerIdx: player, HasTarget: true, TargetPlayer: target, TargetChar: char}
				want := char
				if target != player {
					want += ObsMaxChars
				}
				if got := ActionCharRef(a); got != want {
					t.Fatalf("%+v: got %d want %d", a, got, want)
				}
			}
		}
	}
	if ActionCharRef(Action{Kind: ActionCard}) != -1 || ActionCharRef(Action{Kind: ActionSkill}) != -1 {
		t.Fatal("untargeted action acquired a target")
	}
	if ActionCharRef(Action{Kind: ActionSwitch, Index: 4}) != 4 {
		t.Fatal("switch target changed")
	}
}
