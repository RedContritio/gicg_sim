// greedy_player.go — F1-D1 minimal port from training/core/matchup/greedy_player.py。
//
// Phase 1.2b minimal scope:
//   - D1 only(no minimax recursion)— each legal action 1-ply argmax via snapshot/restore +
//     ScoreF1。 D2-D4 + dice_greedy 留 Phase 1.2c。
//   - Tiebreak:random among argmax(防 deterministic Switch-spam trap,跟 Python ref 同模式)
//   - 不实现 select_with_info 详细 diagnostic(P1.2c +)
//
// 数值等价目标(per design D2):**winrate gate** Go-D1 vs Python-D1 同 baseline n=128 swap
// 内 95% CI(简单 1-ply argmax,Go side bit-exact 跟 Python 同 ops 顺序应该可保;但 F1 浮点
// 算 + tiebreak random,行为等价是 spec)。
//
// 用法(per GreedyPlayer Python ref):
//
//	gp := NewGreedyPlayer("F1", 1, seed)
//	actionIdx := gp.SelectAction(rt)   // returns index into rt.Game.GetLegalActions()
//	rt.Game.Step(actionIdx)            // caller responsible for executing
//
// snapshot/restore bracket 内 panic safety:用 defer 保 restore 总执行(即使 score fn
// 抛)— mirror Python try/finally。

package dmc

import (
	"fmt"
	"math/rand"

	"gicg_mono/gicg_engine/interp"
	"gicg_mono/gicg_engine/record"
)

// GreedyConfig — features (F1-F5) × depth (1-4) variants。 Phase 1.2b 仅 F1 + D1。
type GreedyConfig struct {
	Features string // "F1" | "F2" | ... (Phase 1.2b 仅 "F1")
	Depth    int    // 1 | 2 | 3 | 4 (Phase 1.2b 仅 1)
}

// GreedyPlayer mirror Python GreedyPlayer class。
type GreedyPlayer struct {
	cfg    GreedyConfig
	scorer ScorerFn
	rng    *rand.Rand
}

// NewGreedyPlayer 构造。 features unknown / depth out-of-range raise(fail loud per Python
// ref)。
func NewGreedyPlayer(features string, depth int, seed int64) (*GreedyPlayer, error) {
	scorer, ok := Scorers[features]
	if !ok {
		return nil, fmt.Errorf("unknown features %q; available: %v", features, scorerNames())
	}
	if depth < 1 || depth > 4 {
		return nil, fmt.Errorf("depth must be 1..4, got %d", depth)
	}
	// Phase 1.2b only support D1。
	if depth != 1 {
		return nil, fmt.Errorf("depth %d not yet implemented (Phase 1.2c — D2-D4 follow-up)", depth)
	}
	return &GreedyPlayer{
		cfg:    GreedyConfig{Features: features, Depth: depth},
		scorer: scorer,
		rng:    rand.New(rand.NewSource(seed)),
	}, nil
}

func scorerNames() []string {
	names := make([]string, 0, len(Scorers))
	for k := range Scorers {
		names = append(names, k)
	}
	return names
}

// SelectAction 选 1 action — 跟 Python `select_action` 等价(D1:1-ply argmax + random
// tiebreak)。 返 index into `rt.Game.GetLegalActions()`。
//
// 不 mutate rt(每 candidate 走 snapshot/restore bracket)。 actions empty → return -1 +
// err(Python ref `RuntimeError('no legal actions')` 等价 fail loud)。
func (gp *GreedyPlayer) SelectAction(rt *interp.Runtime) (int, error) {
	g := rt.Game
	actions := g.GetLegalActions()
	if len(actions) == 0 {
		return -1, fmt.Errorf("GreedyPlayer: env has no legal actions")
	}
	me := g.ActingPlayer()
	viewRoot := record.ExportView(rt)
	eventsRoot := SnapshotEvents(g, me)

	var bestScore float64
	bestSet := make([]int, 0, 4)
	for i := range actions {
		// snapshot/restore bracket — DeepCopy + RestoreFrom 匹配,跟 capi
		// GameSnapshot/GameRestore 同协议(Python ref env.snapshot/restore 走 capi)。
		// Snapshot/StateSnapshot 是更 lightweight 但不兼容 RestoreFrom 签名。
		snap := g.DeepCopy()
		var score float64
		func() {
			defer func() {
				g.RestoreFrom(snap)
			}()
			g.Step(i)
			viewAfter := record.ExportView(rt)
			eventsAfter := SnapshotEvents(g, me)
			score = gp.scorer(viewRoot, viewAfter, eventsRoot, eventsAfter, me)
		}()
		if i == 0 || score > bestScore {
			bestScore = score
			bestSet = bestSet[:0]
			bestSet = append(bestSet, i)
		} else if score == bestScore {
			bestSet = append(bestSet, i)
		}
	}
	// Random tiebreak among argmax — 跟 Python `self.rng.choice(tied)` 等价。
	chosen := bestSet[gp.rng.Intn(len(bestSet))]
	return chosen, nil
}
