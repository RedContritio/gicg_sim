package tests

import (
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
)

// TestObs_DicePoolLabels verifies that both players' 8 dice-color
// counters are reachable via the observation's ActiveCounterSlotLabels
// metadata. This guards against regressions where a counter is
// declared but not classified into a player slot (e.g. missing
// RegisterCounterChar call) and silently vanishes from obs.
func TestObs_DicePoolLabels(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	labels := env.G.ActiveCounterSlotLabels()

	wantColors := []string{"fire", "ice", "water", "electro", "geo", "anemo", "dendro", "omni"}
	for _, pi := range []int{0, 1} {
		for _, color := range wantColors {
			needle := "P" + itoa(pi) + ":dice_" + color
			found := false
			for _, l := range labels {
				if strings.Contains(l, needle) {
					found = true
					break
				}
			}
			if !found {
				t.Errorf("missing dice label %q in ActiveCounterSlotLabels", needle)
			}
		}
	}
}

// TestObs_DicePoolValues verifies that dice counter values actually
// reach the dynamic observation — i.e. when we force a specific pool
// and call BuildDynamicObs, the values appear in the expected player
// slot region (not the char / global regions).
//
// This exercises the groupCounters path plus the writeValues loop in
// BuildDynamicObs for the player-bucket slice.
func TestObs_DicePoolValues(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})

	// Seed a deterministic pool for P0.
	env.SetDice(0, map[int]int{
		engine.DiceColorFire:  3,
		engine.DiceColorWater: 2,
		engine.DiceColorOmni:  1,
	})

	obs := env.G.BuildDynamicObs(0) // perspective = P0
	// The labels tell us the slot layout; find where P0:dice_fire lives
	// and sanity-check its value.
	labels := env.G.ActiveCounterSlotLabels()

	// BuildDynamicObs offset = Meta(3) + char block + char block + player block
	// where the player block starts after all char counters, and labels
	// follow the SAME order. So the slot index in `labels` aligns with
	// the slot index in `obs[ObsMetaSize:]`.
	//
	// But ActiveCounterSlotLabels is perspective=0-only and BuildDynamicObs
	// swaps own/enemy per perspective. For perspective=0 they align.
	want := map[string]int{
		"P0:dice_fire":  3,
		"P0:dice_water": 2,
		"P0:dice_omni":  1,
		"P0:dice_ice":   0,
	}
	for needle, wantVal := range want {
		idx := -1
		for i, l := range labels {
			if l == needle {
				idx = i
				break
			}
		}
		if idx < 0 {
			t.Errorf("label %q not found", needle)
			continue
		}
		got := int(obs[engine.ObsMetaSize+idx])
		if got != wantVal {
			t.Errorf("obs[%q] = %d, want %d", needle, got, wantVal)
		}
	}
}

// itoa imported from the existing test helpers (helpers_test.go may
// not expose it, so redeclare a local one).
func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var buf [12]byte
	i := len(buf)
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		buf[i] = '-'
	}
	return string(buf[i:])
}
