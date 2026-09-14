package tests

import (
	"bytes"
	"encoding/json"
	"fmt"
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/factory"
	"gicg_mono/gicg_engine/record"
	"math/rand"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"testing"
)

// Reproduce one failed case: GICG_AUDIT_SEED=N go test ./gicg_engine/tests
// -run TestRandomEffectSequences -count=1. Failure artifacts contain exact inputs.
func TestRandomEffectSequences(t *testing.T) {
	seeds := []int64{1, 2, 3, 4, 5, 6, 7, 8, 19, 31, 47, 73}
	if v := os.Getenv("GICG_AUDIT_SEED"); v != "" {
		n, err := strconv.ParseInt(v, 10, 64)
		if err != nil {
			t.Fatal(err)
		}
		seeds = []int64{n}
	}
	seenKinds := map[engine.ActionKind]int{}
	seenEffects := map[string]bool{}
	totalInputs, totalRounds, deaths := 0, 0, 0
	cards := []string{"乘胜追击", "佛跳墙", "荷花酥", "速速茶点", "反制", "以牙还牙", "以逸待劳", "蝶鳞", "守正", "西风剑", "西风长枪", "瞬身之术", "伏兵之术", "美味烧鸡", "清洁时间", "玄冰", "以攻代守"}
	for _, seed := range seeds {
		t.Run(fmt.Sprint(seed), func(t *testing.T) {
			cfg := factory.GameConfig{DataDir: dataDir, Pools: []string{"v_legacy", "test_basic"}, Seed: seed, MaxRounds: 8, FixDice: []int{0, 0, 0, 0, 0, 0, 0, 12}, CardPool: cards}
			for p := 0; p < 2; p++ {
				cfg.Players[p] = factory.PConfig{Chars: []factory.CharDef{{Name: "赤蝶"}, {Name: "墨客"}}, Deck: cards}
			}
			h, err := factory.NewGame(cfg)
			if err != nil {
				t.Fatal(err)
			}
			g := h.Game
			chooser := rand.New(rand.NewSource(seed))
			var inputs []int
			defer func() {
				failure := recover()
				defer func() {
					if failure != nil {
						panic(failure)
					}
				}()
				if t.Failed() || failure != nil {
					root := os.Getenv("GICG_AUDIT_FAILURE_DIR")
					if root == "" {
						root = filepath.Join(os.TempDir(), "gicg-audit-failures")
					}
					if err := os.MkdirAll(root, 0755); err != nil {
						t.Log(err)
						return
					}
					data, _ := json.MarshalIndent(struct {
						Seed   int64
						Config factory.GameConfig
						Inputs []int
					}{seed, cfg, inputs}, "", "  ")
					name := filepath.Join(root, fmt.Sprintf("seed-%d.json", seed))
					if err := os.WriteFile(name, data, 0644); err != nil {
						t.Log(err)
					} else {
						t.Log("failure input artifact:", name)
					}
				}
			}()
			restored, pooled := h.RT.Clone(), h.RT.Clone()
			for step := 0; step < 180 && g.Phase != engine.PhaseGameOver; step++ {
				actions := g.GetLegalActions()
				if len(actions) == 0 {
					t.Fatal("no legal actions in nonterminal state")
				}
				// Balance action kinds rather than letting numerous dice payments dominate.
				groups := map[engine.ActionKind][]int{}
				var kinds []engine.ActionKind
				for i, a := range actions {
					if _, ok := groups[a.Kind]; !ok {
						kinds = append(kinds, a.Kind)
					}
					groups[a.Kind] = append(groups[a.Kind], i)
				}
				kind := kinds[chooser.Intn(len(kinds))]
				options := groups[kind]
				index := options[chooser.Intn(len(options))]
				inputs = append(inputs, index)
				seenKinds[actions[index].Kind]++
				before, exportErr := g.ExportCheckpoint()
				snap := g.SnapshotPooled()
				clone := h.RT.Clone()
				branches := map[string]*engine.Game{"clone": clone.Game, "pooled": pooled.Game}
				if exportErr == nil {
					branches["checkpoint"] = restored.Game
					if err := restored.Game.RestoreCheckpoint(before); err != nil {
						t.Fatal(err)
					}
				} else if g.PendingAction == nil && g.PendingCardTarget == nil {
					t.Fatal(exportErr)
				}
				pooled.Game.RestoreFromSnap(snap)
				engine.ReleaseSnap(snap)
				g.Step(index)
				g.GetLegalActions()
				want := sequenceState(t, g)
				for _, buff := range g.Buffs {
					seenEffects[g.CounterNames[g.BuffDefinitions[buff.Definition].CounterID]] = true
				}
				for label, branch := range branches {
					if !reflect.DeepEqual(actions, branch.GetLegalActions()) {
						t.Fatalf("seed=%d step=%d %s legal actions differ", seed, step, label)
					}
					branch.Step(index)
					branch.GetLegalActions()
					if got := sequenceState(t, branch); !bytes.Equal(got, want) {
						t.Fatalf("seed=%d step=%d %s: %s", seed, step, label, checkpointDiff(want, got))
					}
					for p := 0; p < 2; p++ {
						if !reflect.DeepEqual(g.BuildDynamicObs(p), branch.BuildDynamicObs(p)) {
							t.Fatalf("%s observation differs", label)
						}
					}
				}
			}
			rec, err := record.Parse(record.Export(h.RT))
			if err != nil {
				t.Fatal(err)
			}
			replay := h.RT.Clone()
			if err := record.ReplayTo(replay, rec, record.TotalSteps(rec)); err != nil {
				t.Fatal(err)
			}
			replay.Game.GetLegalActions()
			if !bytes.Equal(sequenceState(t, g), sequenceState(t, replay.Game)) {
				t.Fatalf("replay: %s", checkpointDiff(sequenceState(t, g), sequenceState(t, replay.Game)))
			}
			totalInputs += len(inputs)
			totalRounds += g.Round
			for _, p := range g.Players {
				for _, c := range p.Chars {
					if !c.Alive {
						deaths++
					}
				}
			}
			t.Logf("seed=%d inputs=%d rounds=%d", seed, len(inputs), g.Round)
		})
	}
	if os.Getenv("GICG_AUDIT_SEED") == "" {
		if len(seenKinds) < 5 || len(seenEffects) < 8 || deaths == 0 {
			t.Fatalf("insufficient generated coverage: kinds=%v effects=%v deaths=%d", seenKinds, seenEffects, deaths)
		}
	}
	t.Logf("coverage: inputs=%d rounds=%d deaths=%d effects=%v", totalInputs, totalRounds, deaths, seenEffects)

}

func sequenceState(t *testing.T, g *engine.Game) []byte {
	t.Helper()
	snap := g.SnapshotPooled()
	defer engine.ReleaseSnap(snap)
	data, err := json.Marshal(map[string]any{"State": snap})
	if err != nil {
		t.Fatal(err)
	}
	var value any
	if err = json.Unmarshal(data, &value); err != nil {
		t.Fatal(err)
	}
	var canonical func(any) any
	canonical = func(v any) any {
		switch x := v.(type) {
		case []any:
			if len(x) == 0 {
				return nil
			}
			for i := range x {
				x[i] = canonical(x[i])
			}
		case map[string]any:
			for k := range x {
				x[k] = canonical(x[k])
			}
		}
		return v
	}
	data, err = json.Marshal(canonical(value))
	if err != nil {
		t.Fatal(err)
	}
	return data
}
