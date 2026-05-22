// Package az — AZ paradigm Go-native adapter for gicg_actor pool。
//
// 当前 P2.1 scaffold(2026-05-22):仅 Configure + 注册;Run loop 走 stub return error。
// 后续 P2.2 ship 完整 self-play MCTS loop using gicg_mcts.Search()。
//
// Design:
// - AZ self-play:两侧都走 MCTS,actor pool 内 single actor 即 single self-play game
// - MCTS Search 入 gicg_mcts.Search,SendEval/RecvEval 走 inference_client(每个 leaf
//   eval 通过 socket 发到 Python InfServer batched_forward)
// - 每 episode 结束写 transition,每条 transition payload 含:
//   · dyn + refs + pay + static_hash(同 DMC reuse obs encoder)
//   · root visits distribution(MCTS visit counts per legal action)
//   · root_value(network V(s) at root,bootstrap target)
//   · chosen action idx
//   · terminal reward(winner sign)
//
// 边界:
// - gicg_engine 仍零侵入(走 factory + interp 现 API)
// - gicg_mcts 直接 import(Go-to-Go,Python 端的 mcts_search_go cgo binding 在 Go-native
//   actor pool 路径不必要,直接调 gicg_mcts.Search)
// - Determinizations 走 Go-side 简单 sample(opponent hand 当前局可见 = 0,opponent
//   deck/dice 用 rng);P3 perf 数据驱动 vs Python 端复杂 CardPoolSpec 决策是否 port

package az

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"

	"gicg_mono/gicg_actor"
	"gicg_mono/gicg_engine/factory"
)

// AZConfig — paradigm config JSON schema。 跟 DMCConfig 类似但加 MCTS 配置。
type AZConfig struct {
	gicg_actor.BaseActorConfig

	// MCTS-specific
	NRollouts        int     `json:"n_rollouts"`        // per move,1-1024 typical
	ParallelRollouts int     `json:"parallel_rollouts"` // concurrent rollout goroutines
	CPuct            float32 `json:"c_puct"`            // exploration constant
	DirichletAlpha   float32 `json:"dirichlet_alpha"`   // root noise alpha
	DirichletWeight  float32 `json:"dirichlet_weight"`  // (1-w)*prior + w*Dir(alpha)
	TemperatureMoves int     `json:"temperature_moves"` // first N moves sample by visits^(1/T)
	TemperatureValue float32 `json:"temperature_value"` // T value(>0;1.0 默认)
}

// AZParadigm — gicg_actor.Paradigm impl。
type AZParadigm struct {
	cfg     AZConfig
	gameCfg factory.GameConfig
}

func (p *AZParadigm) Name() string {
	return "az"
}

// Configure 反序列化 AZConfig + 预解 GameSpec → factory.GameConfig。
func (p *AZParadigm) Configure(jsonCfg string) error {
	if jsonCfg == "" {
		return fmt.Errorf("AZParadigm.Configure: empty JSON config")
	}
	var c AZConfig
	if err := json.Unmarshal([]byte(jsonCfg), &c); err != nil {
		return fmt.Errorf("AZParadigm.Configure: unmarshal AZConfig: %w", err)
	}
	if err := c.Validate(); err != nil {
		return fmt.Errorf("AZParadigm.Configure: %w", err)
	}
	if c.NRollouts <= 0 {
		return fmt.Errorf("AZParadigm.Configure: n_rollouts=%d must be positive", c.NRollouts)
	}
	if c.ParallelRollouts <= 0 {
		c.ParallelRollouts = 1
	}
	if c.CPuct <= 0 {
		return fmt.Errorf("AZParadigm.Configure: c_puct=%f must be positive", c.CPuct)
	}
	if c.TemperatureValue <= 0 {
		c.TemperatureValue = 1.0
	}
	var gameCfg factory.GameConfig
	if err := json.Unmarshal(c.GameSpec, &gameCfg); err != nil {
		return fmt.Errorf("AZParadigm.Configure: unmarshal game_spec: %w", err)
	}
	p.cfg = c
	p.gameCfg = gameCfg
	return nil
}

// Run — P2.1 scaffold stub。 P2.2 ship 完整 self-play MCTS loop。
func (p *AZParadigm) Run(ctx context.Context, actorID int, infCli *gicg_actor.InferenceClient, transWri *gicg_actor.TransitionWriter) error {
	_ = ctx
	_ = actorID
	_ = infCli
	_ = transWri
	return fmt.Errorf("AZParadigm.Run: P2.1 scaffold — full MCTS self-play loop deferred to P2.2")
}

var registerOnce sync.Once

func init() {
	registerOnce.Do(func() {
		gicg_actor.RegisterParadigm("az", &AZParadigm{})
	})
}
