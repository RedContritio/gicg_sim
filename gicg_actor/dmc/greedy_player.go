// greedy_player.go — F1-F5 × D1-D4 GreedyPlayer Go port from
// training/core/matchup/greedy_player.py。
//
// Phase 1.2b 完整 port:F1-F5 scorer × D1-D4 minimax depth。 dice_greedy 折叠
// (dice_greedy.go)已 port:minimax 迭代前调 filterLogicalActions 把 dice-payment
// fan-out 折叠成每逻辑动作 1 个 top-payment(N → N_logical),消除 O(N^depth) 爆炸。
//
// 数值等价目标(per design D2):**winrate gate** Go vs Python 同 baseline n=128 swap 内
// 95% CI。 浮点 ops 顺序在 D1 单层不 critical,D2-D4 minimax 累积浮点 ε 可能造成 tie-break
// 边界不同 — 实测可接受(winrate 是 final 行为等价 verify)。
//
// 用法(per GreedyPlayer Python ref):
//
//	gp, err := NewGreedyPlayer("F5", 4, seed)  // F5 + D4 production-tier
//	actionIdx, err := gp.SelectAction(rt)      // returns index into rt.Game.GetLegalActions()
//	rt.Game.Step(actionIdx)                    // caller responsible for executing
//
// snapshot/restore bracket 内 panic safety:用 defer 保 restore 总执行(即使 score fn
// 抛)— mirror Python try/finally。

package dmc

import (
	"fmt"
	"math/rand"

	"gicg_mono/gicg_actor"
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
	"gicg_mono/gicg_engine/record"
)

// GreedyConfig — features (F1-F5) × depth (1-4) variants + minimax budget。
type GreedyConfig struct {
	Features string
	Depth    int
	// MinimaxBudget — scoreBestResponse 递归 DeepCopy 总数上限 (per SelectAction
	// call 共享)。 0 = 无 cap (Python ref 历史行为, D4 完整跑 ~5-15s/episode)。 > 0 =
	// 超出后停止展开 + 当前节点降级评分 (D4 capped 到 ~D2.7 effective depth)。
	// C2 (2026-05-25) cfg-driven 替代原 const minimaxNodeBudget=4000 硬码,让 Python
	// 端 `training/core/matchup/greedy_player.py` 与 Go 端共用 cfg knob (cross-language
	// fair bench parity)。 production cfg 默认 0 (无 cap) 与 Python production 默认行为
	// 对齐;bench cfg `[paradigm.dmc.opponent_mix].minimax_node_budget` 显式两边设值
	// 才能测纯 pipeline overhead 而非 algo asymmetry。
	MinimaxBudget int
}

// GreedyPlayer mirror Python GreedyPlayer class。
type GreedyPlayer struct {
	cfg    GreedyConfig
	scorer ScorerFn
	rng    *rand.Rand
}

// NewGreedyPlayer 构造。 features unknown / depth out-of-range raise(fail loud per Python
// ref)。 D1-D4 全支持。 “budget“ <= 0 视作无 cap (production 默认行为, 与 Python
// minimax_node_budget=None 对齐)。
func NewGreedyPlayer(features string, depth int, seed int64, budget int) (*GreedyPlayer, error) {
	scorer, ok := Scorers[features]
	if !ok {
		return nil, fmt.Errorf("unknown features %q; available: %v", features, scorerNames())
	}
	if depth < 1 || depth > 4 {
		return nil, fmt.Errorf("depth must be 1..4, got %d", depth)
	}
	if budget < 0 {
		return nil, fmt.Errorf("minimax budget must be >= 0 (0 = no cap), got %d", budget)
	}
	return &GreedyPlayer{
		cfg:    GreedyConfig{Features: features, Depth: depth, MinimaxBudget: budget},
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

// scoreBestResponse — Python ref `_score_best_response` 等价。 Recursive minimax: 当前
// env state 从 “me“ 视角评分,向下看 “depth“ 层。 depth==0:score(viewRoot vs
// env-now)。 caller 应已 snapshot;本函数 leaves env in same state(每个 candidate snap/
// restore)。
//
// acting==me:max(sub_scores),else: min(sub_scores)— mirror Python max/min branching。
//
// “budget“ 是共享 counter (per SelectAction 调用)。 budget==nil → unbounded (production
// 默认 cfg knob=0);budget != nil 且 *budget <= 0 → 停止展开,当前节点降级评分。
// 2026-05-28 后:hot-path snap 从 g.DeepCopy() 换成 g.SnapshotPooled() (pool-backed
// 0-alloc 复用,详 engine/game_snap.go);原 budget cap 是 DeepCopy GC pressure 的
// workaround,SnapshotPooled 后 budget=0 unbounded 直接 viable。
func (gp *GreedyPlayer) scoreBestResponse(
	rt *interp.Runtime,
	viewRoot *record.StateView,
	eventsRoot *EventsSnapshot,
	me int,
	depth int,
	budget *int,
) float64 {
	g := rt.Game
	// budget 耗尽 → 停止展开,当前节点直接评分。 budget==nil 视作 unbounded。
	budgetExhausted := budget != nil && *budget <= 0
	if g.Phase == engine.PhaseGameOver || depth <= 0 || budgetExhausted {
		return gp.scorer(viewRoot, record.ExportView(rt), eventsRoot, SnapshotEvents(g, me), me)
	}
	acting := g.ActingPlayer()
	// dice_greedy fold:把 dice-payment fan-out 折叠成每逻辑动作 1 个 top-payment,
	// minimax 只迭代折叠后的 index 子集(N → N_logical),避免 O(N^depth) 爆炸。
	// 返回的 index 仍是 index into GetLegalActions(),g.Step(idx) 不变。
	candidates := filterLogicalActions(g)
	if len(candidates) == 0 {
		// Mirror Python no-candidates path:return current score(no further step possible)
		return gp.scorer(viewRoot, record.ExportView(rt), eventsRoot, SnapshotEvents(g, me), me)
	}
	hasBest := false
	var best float64
	for _, i := range candidates {
		if budget != nil {
			*budget--
		}
		snapSpan := gicg_actor.Span("game.snapshot_pooled")
		snap := g.SnapshotPooled()
		snapSpan.End()
		var sub float64
		func() {
			defer func() {
				g.RestoreFromSnap(snap)
				engine.ReleaseSnap(snap)
			}()
			g.Step(i)
			sub = gp.scoreBestResponse(rt, viewRoot, eventsRoot, me, depth-1, budget)
		}()
		if !hasBest {
			best = sub
			hasBest = true
		} else if acting == me {
			if sub > best {
				best = sub
			}
		} else {
			if sub < best {
				best = sub
			}
		}
	}
	return best
}

// SelectAction 选 1 action — D1-D4 minimax with random tiebreak among argmax。
// 返 index into rt.Game.GetLegalActions()。 不 mutate rt。 actions empty → -1 + err
// (mirror Python `RuntimeError` 等价 fail loud)。
func (gp *GreedyPlayer) SelectAction(rt *interp.Runtime) (int, error) {
	defer gicg_actor.Span("dmc.opp_minimax_select").End()
	g := rt.Game
	if len(g.GetLegalActions()) == 0 {
		return -1, fmt.Errorf("GreedyPlayer: env has no legal actions")
	}
	me := g.ActingPlayer()
	viewRoot := record.ExportView(rt)
	eventsRoot := SnapshotEvents(g, me)

	// dice_greedy fold:折叠 dice-payment fan-out 后只迭代逻辑动作子集
	// (index into GetLegalActions(),g.Step 不变)。 GetLegalActions() 非空 →
	// filterLogicalActions 至少返 1 个 candidate(end_turn 总在)。
	candidates := filterLogicalActions(g)

	// minimax node budget — 跨整个 SelectAction 共享, 封顶递归 DeepCopy 总数。
	// cfg.MinimaxBudget == 0 → budgetPtr nil → scoreBestResponse 走 unbounded path
	// (mirror Python `minimax_node_budget=None` default — production 历史行为)。
	// > 0 → 按值封顶 (典型 4000 = D4 capped 到 ~D2.7,bench 对齐时设)。
	var budgetPtr *int
	if gp.cfg.MinimaxBudget > 0 {
		budget := gp.cfg.MinimaxBudget
		budgetPtr = &budget
	}

	// Top-level loop:每 candidate snapshot+step→ scoreBestResponse(depth-1 ply lookahead) → restore。
	var bestScore float64
	bestSet := make([]int, 0, 4)
	first := true
	for _, i := range candidates {
		if budgetPtr != nil {
			*budgetPtr--
		}
		snapSpan := gicg_actor.Span("game.snapshot_pooled")
		snap := g.SnapshotPooled()
		snapSpan.End()
		var score float64
		func() {
			defer func() {
				g.RestoreFromSnap(snap)
				engine.ReleaseSnap(snap)
			}()
			g.Step(i)
			score = gp.scoreBestResponse(rt, viewRoot, eventsRoot, me, gp.cfg.Depth-1, budgetPtr)
		}()
		if first || score > bestScore {
			first = false
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
