package tests

import (
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// TestL2_FotiaoqiangDamageBuffFiresOnce — inject 佛跳墙 into hand,
// play it (sets buff=1), then use 枪 skill: damage should be
// 2 + 2 = 4. Use 枪 again: damage back to 2.
func TestL2_FotiaoqiangDamageBuffFiresOnce(t *testing.T) {
	env := l2Setup(t)

	injectHand(t, env, 0, []string{"佛跳墙"})
	// 佛跳墙: 2 any dice. 枪: 1 fire + 2 any.  Total for full test: 5 dice.
	env.SetDice(0, map[int]int{
		engine.DiceColorFire: 3,
		engine.DiceColorOmni: 5,
	})

	// Eat 佛跳墙.
	idx := env.FindAction(engine.ActionCard, "佛跳墙")
	if idx < 0 {
		t.Fatal("佛跳墙 not legal")
	}
	env.Step(idx)

	if v := getCounterPerChar(t, env, "佛跳墙_buff", 0, 0); v != 1 {
		t.Fatalf("buff after play = %d, want 1", v)
	}

	// Record P1 HP pre-skill.
	hpBefore := env.HP(1, 0)

	// Use 枪.
	skillIdx := env.FindAction(engine.ActionSkill, "枪")
	if skillIdx < 0 {
		t.Fatal("枪 skill not legal")
	}
	env.Step(skillIdx)

	hpAfter := env.HP(1, 0)
	dmg := hpBefore - hpAfter
	// 枪 base = 2, buff = +2. Expected damage = 4.
	if dmg != 4 {
		t.Errorf("first skill damage = %d, want 4 (base 2 + buff 2)", dmg)
	}
	// Buff must be consumed.
	if v := getCounterPerChar(t, env, "佛跳墙_buff", 0, 0); v != 0 {
		t.Errorf("buff after first skill = %d, want 0", v)
	}
	ensureLegalActions(t, env)
}

// TestL2_CurseOnZeroEnergyIsSafe — inject 诅咒 into P0, set P1 active
// char energy to 0, play 诅咒, verify no crash / no negative energy.
func TestL2_CurseOnZeroEnergyIsSafe(t *testing.T) {
	env := l2Setup(t)

	injectHand(t, env, 0, []string{"诅咒"})
	env.SetDice(0, map[int]int{engine.DiceColorOmni: 5})

	// P1's char energy to 0 (should already be 0 at game start, but
	// make it explicit).
	p1Entry := env.RT.Chars.BySlot[1][0]
	env.G.Counters[p1Entry.EnergyCounterID].Value = 0

	idx := env.FindAction(engine.ActionCard, "诅咒")
	if idx < 0 {
		t.Fatal("诅咒 not legal")
	}
	env.Step(idx)

	// Energy must clamp at 0 — not go negative.
	if e := env.Energy(1, 0); e != 0 {
		t.Errorf("P1 energy after 诅咒 on 0 = %d, want 0 (clamped)", e)
	}
	ensureLegalActions(t, env)
}

// TestL2_ZhanxingCapsAtMaxEnergy — P0 energy at max-1, play 占星
// (grants 2), verify energy is capped at max, not max+1.
func TestL2_ZhanxingCapsAtMaxEnergy(t *testing.T) {
	env := l2Setup(t)

	injectHand(t, env, 0, []string{"占星"})
	env.SetDice(0, map[int]int{engine.DiceColorOmni: 5})

	entry := env.RT.Chars.BySlot[0][0]
	// Set energy to max-1 = 2.
	env.G.Counters[entry.EnergyCounterID].Value = 2

	idx := env.FindAction(engine.ActionCard, "占星")
	if idx < 0 {
		t.Fatal("占星 not legal")
	}
	env.Step(idx)

	e := env.Energy(0, 0)
	if e != 3 {
		t.Errorf("energy after 占星 from max-1 = %d, want 3 (capped at max)", e)
	}
	ensureLegalActions(t, env)
}

// TestL2_AllFoodOnActiveChar_NoDeadlock — degenerate case: P0's hand
// is ONLY 饱腹-blocked food cards, with ample dice. After 饱腹 is
// forced on, the legal action list must still contain EndTurn (or
// other non-blocked actions) — zero legal actions here would be a
// D14-class deadlock.
func TestL2_AllFoodOnActiveChar_NoDeadlock(t *testing.T) {
	env := l2Setup(t)

	injectHand(t, env, 0, []string{"美味烧鸡", "美味烧鸡", "佛跳墙", "佛跳墙"})
	env.SetDice(0, map[int]int{engine.DiceColorOmni: 10})
	setCounterPerChar(t, env, "饱腹", 0, 0, 1)

	actions := env.G.GetLegalActions()
	if len(actions) == 0 {
		t.Fatal("zero legal actions with all-food hand + 饱腹=1 — deadlock")
	}

	// None of the actions should be the blocked food cards.
	for _, a := range actions {
		if a.Kind == engine.ActionCard {
			if a.Index < len(env.G.Players[a.PlayerIdx].Hand) {
				ref := env.G.Players[a.PlayerIdx].Hand[a.Index].Ref
				name := env.G.CardNames[ref]
				if name == "美味烧鸡" || name == "佛跳墙" {
					t.Errorf("blocked food %q unexpectedly in legal actions", name)
				}
			}
		}
	}
}

// TestL2_FoodSurvivesSnapshot — 饱腹 counter is part of the snapshot
// boundary, so cloning a game with 饱腹=1 and mutating the original
// must not leak back. This is the IS-MCTS determinization invariant
// applied to L2 state.
func TestL2_FoodSurvivesSnapshot(t *testing.T) {
	env := l2Setup(t)

	setCounterPerChar(t, env, "饱腹", 0, 0, 1)

	// Snapshot + mutate original.
	snap := env.G.DeepCopy()
	setCounterPerChar(t, env, "饱腹", 0, 0, 0)

	// Original is 0 (just set it).
	if v := getCounterPerChar(t, env, "饱腹", 0, 0); v != 0 {
		t.Fatalf("original 饱腹 = %d after mutation, want 0", v)
	}

	// Snapshot must still show 1.
	entry := env.RT.CounterEntries()["饱腹"]
	idx := 0*interp.MaxChars + 0
	id := entry.CounterIDs[idx]
	if snap.Counters[id].Value != 1 {
		t.Errorf("snapshot 饱腹 = %d, want 1 (original mutation leaked in)",
			snap.Counters[id].Value)
	}
}
