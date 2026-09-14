package mcts

import (
	"errors"
	"testing"
	"time"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/factory"
)

func TestSearchReturnsFailuresWithoutDeadlock(t *testing.T) {
	for _, mode := range []string{"rule", "send", "receive"} {
		t.Run(mode, func(t *testing.T) {
			h, err := factory.NewGame(factory.GameConfig{
				DataDir: "../data", Seed: 42,
				Players: [2]factory.PConfig{{Chars: []factory.CharDef{{Name: "赤蝶"}}}, {Chars: []factory.CharDef{{Name: "墨客"}}}},
			})
			if err != nil {
				t.Fatal(err)
			}
			g := h.Game
			g.Step(0)
			g.Step(0)
			ids := LegalActionIds(g)
			prior := make([]float32, len(ids))
			for i := range prior {
				prior[i] = 1 / float32(len(prior))
			}
			failure := errors.New("intentional search failure")
			if mode == "rule" {
				g.Hooks.Register(engine.Hook{Type: engine.HookActionCheck, Fn: func(g *engine.Game, ctx *engine.EventContext) { g.FailRule(failure, ctx.CurrentHookID) }})
			}
			input := &SearchInput{Runtime: h.RT, Snap: g.DeepCopy(), RootActions: ids, RootPrior: prior,
				Config: &Config{NRollouts: 100, ParallelRollouts: 4, MaxRolloutDepth: 2, CPuct: 1, ValueMixLambda: 1},
				SendEval: func(req *EvalRequest) error {
					if mode == "send" {
						return failure
					}
					return nil
				},
				RecvEval: func(resp *EvalResponse) error { return failure },
			}
			result := make(chan error, 1)
			go func() { _, err := Search(input); result <- err }()
			select {
			case err := <-result:
				if !errors.Is(err, failure) {
					t.Fatalf("lost failure: %v", err)
				}
			case <-time.After(5 * time.Second):
				t.Fatal("search workers/dispatcher deadlocked after failure")
			}
			if g.Failure != nil {
				t.Fatal("failed speculative game polluted live game")
			}
		})
	}
}
