package tests

import (
	"math/rand"
	"testing"

	engine "gicg_mono/gicg_engine"
)

// Static obs layout for locating the char-element block:
//
//	[CounterMeta : obsCounterSlots() * 3]
//	[CharSkillRefs : 2 * ObsMaxChars * ObsMaxSkillsPerChar]
//	[HookIROps  : ObsMaxHooks * ObsIntsPerHook]   (IR-2.b.2 cutover)
//	[CharElementIDs : 2 * ObsMaxChars]   ← this block
//
// Each int32 at offset (charElemStart + pi*ObsMaxChars + ci) holds the
// Element enum for that (player, char slot), or -1 for unbound.
func charElementRegion(g *engine.Game) [2][engine.ObsMaxChars]int32 {
	obs := g.BuildStaticObs()
	counterMetaSize := (2*engine.ObsMaxChars*engine.ObsCharSlots +
		2*engine.ObsPlayerSlots + engine.ObsGlobalSlots) * 3
	skillRefsSize := 2 * engine.ObsMaxChars * engine.ObsMaxSkillsPerChar
	hookIRSize := engine.ObsMaxHooks * engine.ObsIntsPerHook
	offset := counterMetaSize + skillRefsSize + hookIRSize
	var out [2][engine.ObsMaxChars]int32
	for pi := 0; pi < 2; pi++ {
		for ci := 0; ci < engine.ObsMaxChars; ci++ {
			out[pi][ci] = obs[offset]
			offset++
		}
	}
	return out
}

// TestCharElement_Basic: bound chars have their Element emitted;
// unbound slots are -1.
func TestCharElement_Basic(t *testing.T) {
	// 赤蝶 is Fire, 墨客 is Water, per data/characters/*/*.lua.
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	elems := charElementRegion(env.G)

	if elems[0][0] != int32(engine.ElemFire) {
		t.Errorf("P0 c0 (赤蝶): want ElemFire (%d), got %d",
			int(engine.ElemFire), elems[0][0])
	}
	if elems[1][0] != int32(engine.ElemWater) {
		t.Errorf("P1 c0 (墨客): want ElemWater (%d), got %d",
			int(engine.ElemWater), elems[1][0])
	}
	// Every other slot is an unbound phantom → -1.
	for pi := 0; pi < 2; pi++ {
		for ci := 1; ci < engine.ObsMaxChars; ci++ {
			if elems[pi][ci] != -1 {
				t.Errorf("unbound slot P%d c%d should be -1, got %d",
					pi, ci, elems[pi][ci])
			}
		}
	}
}

// TestCharElement_Team2: 2-char teams populate the first two slots on
// each side; chars 2..5 are phantom. Element values match DSL declarations.
func TestCharElement_Team2(t *testing.T) {
	// 测试角色A is Fire, 测试角色B is Electro (see their .lua files).
	env := NewGame(t, []string{"测试角色A", "测试角色B"}, []string{"测试角色A", "测试角色B"})
	elems := charElementRegion(env.G)

	for pi := 0; pi < 2; pi++ {
		if elems[pi][0] != int32(engine.ElemFire) {
			t.Errorf("P%d c0 (测试角色A): want ElemFire, got %d", pi, elems[pi][0])
		}
		if elems[pi][1] != int32(engine.ElemElectro) {
			t.Errorf("P%d c1 (测试角色B): want ElemElectro, got %d", pi, elems[pi][1])
		}
		for ci := 2; ci < engine.ObsMaxChars; ci++ {
			if elems[pi][ci] != -1 {
				t.Errorf("P%d c%d (phantom): want -1, got %d", pi, ci, elems[pi][ci])
			}
		}
	}
}

// TestCharElement_ObsSizeIncludesBlock: StaticObsSize() includes the
// element block and the definition-link trailer.
func TestCharElement_ObsSizeIncludesBlock(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	obs := env.G.BuildStaticObs()
	if len(obs) != engine.StaticObsSize() {
		t.Fatalf("obs length %d != StaticObsSize() %d", len(obs), engine.StaticObsSize())
	}
	counterMeta := (2*engine.ObsMaxChars*engine.ObsCharSlots +
		2*engine.ObsPlayerSlots + engine.ObsGlobalSlots) * 3
	skillRefs := 2 * engine.ObsMaxChars * engine.ObsMaxSkillsPerChar
	hookIR := engine.ObsMaxHooks * engine.ObsIntsPerHook
	expected := counterMeta + skillRefs + hookIR + engine.ObsCharElementSlots + engine.ObsDefinitionLinkSlots
	if engine.StaticObsSize() != expected {
		t.Errorf("StaticObsSize(): want %d (meta+skill+hookIR+elements+definition-links), got %d",
			expected, engine.StaticObsSize())
	}
}

// TestCharElement_InRangeForEmbedding: emitted values (excluding -1
// phantom sentinel) lie in the closed interval [ElemNone, ElemPhysical].
// A learned embedding table sized to (N+2) — for the 9 Element values
// plus a "phantom" slot — will cover the valid range if the consumer
// shifts -1 → 0 and Element → Element+1.
func TestCharElement_InRangeForEmbedding(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶", "墨客", "猫咪"}, []string{"刻师傅", "天星"})
	elems := charElementRegion(env.G)
	for pi := 0; pi < 2; pi++ {
		for ci := 0; ci < engine.ObsMaxChars; ci++ {
			v := elems[pi][ci]
			if v == -1 {
				continue // phantom
			}
			if v < int32(engine.ElemNone) || v > int32(engine.ElemPhysical) {
				t.Errorf("P%d c%d element %d out of [%d, %d]",
					pi, ci, v, int(engine.ElemNone), int(engine.ElemPhysical))
			}
		}
	}
}

// Silence unused-import lint for rand when no randomized fixture is
// added — kept in scope for parity with sibling obs_*_test.go files.
var _ = rand.Int
