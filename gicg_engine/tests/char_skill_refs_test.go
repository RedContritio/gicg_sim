package tests

import (
	"math/rand"
	"testing"

	engine "gicg_mono/gicg_engine"
)

// charSkillRefsRegion extracts the char_skill_refs segment from a
// freshly-built static obs. Layout (see observation.go):
//
//	[CounterMeta: obsCounterSlots() * 3]
//	[CharSkillRefs: 2 * ObsMaxChars * ObsMaxSkillsPerChar]
//	[HookTokens: ObsMaxHooks * ObsMaxTokensPerHook * 2]
//
// Returns a view shaped [2][ObsMaxChars][ObsMaxSkillsPerChar]int32.
func charSkillRefsRegion(g *engine.Game) [2][engine.ObsMaxChars][engine.ObsMaxSkillsPerChar]int32 {
	obs := g.BuildStaticObs()
	counterMetaSize := (2*engine.ObsMaxChars*engine.ObsCharSlots +
		2*engine.ObsPlayerSlots + engine.ObsGlobalSlots) * 3
	offset := counterMetaSize
	var out [2][engine.ObsMaxChars][engine.ObsMaxSkillsPerChar]int32
	for pi := 0; pi < 2; pi++ {
		for ci := 0; ci < engine.ObsMaxChars; ci++ {
			for si := 0; si < engine.ObsMaxSkillsPerChar; si++ {
				out[pi][ci][si] = obs[offset]
				offset++
			}
		}
	}
	return out
}

// TestCharSkillRefs_Mirror: P0 and P1 each have 赤蝶; both slots should
// have positive refs for the char's first N skills and -1 for the rest.
// The two sides' refs must be distinct (per-binding → different hook IDs).
func TestCharSkillRefs_Mirror(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"赤蝶"})
	refs := charSkillRefsRegion(env.G)

	p0Skills := env.G.Players[0].Chars[0].Skills
	p1Skills := env.G.Players[1].Chars[0].Skills
	if len(p0Skills) == 0 || len(p1Skills) == 0 {
		t.Fatalf("mirror match: expected skills on both sides, got %v / %v",
			p0Skills, p1Skills)
	}

	for si := 0; si < len(p0Skills); si++ {
		if refs[0][0][si] < 0 {
			t.Errorf("P0 赤蝶 skill slot %d should have non-negative ref, got %d",
				si, refs[0][0][si])
		}
		if refs[1][0][si] < 0 {
			t.Errorf("P1 赤蝶 skill slot %d should have non-negative ref, got %d",
				si, refs[1][0][si])
		}
		if refs[0][0][si] == refs[1][0][si] {
			t.Errorf("mirror: P0 and P1 skill slot %d share active idx %d "+
				"(expected distinct per-binding hooks)",
				si, refs[0][0][si])
		}
	}
	// Beyond char's actual skill count → -1
	for si := len(p0Skills); si < engine.ObsMaxSkillsPerChar; si++ {
		if refs[0][0][si] != -1 {
			t.Errorf("P0 slot (0,%d) beyond skill count should be -1, got %d",
				si, refs[0][0][si])
		}
	}
}

// TestCharSkillRefs_EmptyCharSlots: chars beyond the team size get all -1.
// 赤蝶 single-char team → ci=0 populated, ci=1..5 all -1.
func TestCharSkillRefs_EmptyCharSlots(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"赤蝶"})
	refs := charSkillRefsRegion(env.G)
	for pi := 0; pi < 2; pi++ {
		for ci := 1; ci < engine.ObsMaxChars; ci++ {
			for si := 0; si < engine.ObsMaxSkillsPerChar; si++ {
				if refs[pi][ci][si] != -1 {
					t.Errorf("empty char slot P%d c%d s%d should be -1, got %d",
						pi, ci, si, refs[pi][ci][si])
				}
			}
		}
	}
}

// TestCharSkillRefs_NonMirror: distinct char on each side → refs don't
// collide; each side's refs resolve within its own skill count.
func TestCharSkillRefs_NonMirror(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	refs := charSkillRefsRegion(env.G)

	p0Skills := env.G.Players[0].Chars[0].Skills
	p1Skills := env.G.Players[1].Chars[0].Skills
	for si := 0; si < len(p0Skills); si++ {
		if refs[0][0][si] < 0 {
			t.Errorf("P0 赤蝶 skill %d should be resolved", si)
		}
	}
	for si := 0; si < len(p1Skills); si++ {
		if refs[1][0][si] < 0 {
			t.Errorf("P1 墨客 skill %d should be resolved", si)
		}
	}
	// P0 refs should not equal any P1 ref (distinct canonical hooks)
	p0Set := map[int32]bool{}
	for si := 0; si < len(p0Skills); si++ {
		p0Set[refs[0][0][si]] = true
	}
	for si := 0; si < len(p1Skills); si++ {
		if p0Set[refs[1][0][si]] {
			t.Errorf("P1 墨客 skill %d active idx %d collides with P0 赤蝶",
				si, refs[1][0][si])
		}
	}
}

// TestCharSkillRefs_Shuffled: InitShuffle installs SkillSlotPerm — physical
// slot order is randomized per (p, c). Verifies:
//  1. SkillSlotPerm is a valid permutation of [0, ObsMaxSkillsPerChar)
//  2. The multiset of non-(-1) refs per (p, c) matches the char's real skill
//     count — no refs lost or duplicated by the perm
//  3. Two (p, c) slots with same char get independent perms (the skills of
//     a char appear at DIFFERENT physical positions on P0 vs P1 in mirror),
//     which is the anti-ID signal
func TestCharSkillRefs_Shuffled(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"赤蝶"})
	env.G.InitShuffle(rand.New(rand.NewSource(7)))

	// Validate perm shape + permutation property
	if env.G.SkillSlotPerm == nil {
		t.Fatal("InitShuffle should populate SkillSlotPerm")
	}
	for pi := 0; pi < 2; pi++ {
		for ci := 0; ci < engine.ObsMaxChars; ci++ {
			p := env.G.SkillSlotPerm[pi][ci]
			if len(p) != engine.ObsMaxSkillsPerChar {
				t.Errorf("SkillSlotPerm[%d][%d] len=%d, want %d",
					pi, ci, len(p), engine.ObsMaxSkillsPerChar)
			}
			seen := make(map[int]bool, len(p))
			for _, v := range p {
				if v < 0 || v >= engine.ObsMaxSkillsPerChar {
					t.Errorf("SkillSlotPerm[%d][%d] value %d out of range", pi, ci, v)
				}
				if seen[v] {
					t.Errorf("SkillSlotPerm[%d][%d] duplicate value %d", pi, ci, v)
				}
				seen[v] = true
			}
		}
	}

	refs := charSkillRefsRegion(env.G)
	p0Skills := env.G.Players[0].Chars[0].Skills

	// Count non-(-1) refs per (p, c=0) — should equal the skill count.
	countNonNeg := func(pi, ci int) int {
		n := 0
		for si := 0; si < engine.ObsMaxSkillsPerChar; si++ {
			if refs[pi][ci][si] >= 0 {
				n++
			}
		}
		return n
	}
	if got := countNonNeg(0, 0); got != len(p0Skills) {
		t.Errorf("P0 c0: non-negative ref count=%d, want %d (= skill count)",
			got, len(p0Skills))
	}
	if got := countNonNeg(1, 0); got != len(p0Skills) {
		t.Errorf("P1 c0: non-negative ref count=%d, want %d (= skill count)",
			got, len(p0Skills))
	}

	// Anti-ID: P0 and P1 perms are independent with high probability.
	// Check that SkillSlotPerm[0][0] != SkillSlotPerm[1][0] (at least
	// some element differs — identical by chance for a length-10 perm
	// has probability 1/10! which is ~2.7e-7, negligible).
	if equalSlices(env.G.SkillSlotPerm[0][0], env.G.SkillSlotPerm[1][0]) {
		t.Errorf("P0 and P1 have identical SkillSlotPerm[_][0] — expected "+
			"independent shuffles (probability of equality ~1/10!): %v",
			env.G.SkillSlotPerm[0][0])
	}
}

func equalSlices(a, b []int) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// TestCharSkillRefs_TeamSize2: team of 2 chars — refs populated for ci=0
// and ci=1, nothing past.
func TestCharSkillRefs_TeamSize2(t *testing.T) {
	env := NewGame(t, []string{"赤蝶", "墨客"}, []string{"猫咪", "天星"})
	refs := charSkillRefsRegion(env.G)

	for pi := 0; pi < 2; pi++ {
		for ci := 0; ci < 2; ci++ {
			skills := env.G.Players[pi].Chars[ci].Skills
			if len(skills) == 0 {
				t.Errorf("P%d c%d should have skills", pi, ci)
				continue
			}
			if refs[pi][ci][0] < 0 {
				t.Errorf("P%d c%d first skill should resolve, got %d",
					pi, ci, refs[pi][ci][0])
			}
		}
		for ci := 2; ci < engine.ObsMaxChars; ci++ {
			for si := 0; si < engine.ObsMaxSkillsPerChar; si++ {
				if refs[pi][ci][si] != -1 {
					t.Errorf("P%d c%d (beyond team) should be -1, got %d",
						pi, ci, refs[pi][ci][si])
				}
			}
		}
	}
}
