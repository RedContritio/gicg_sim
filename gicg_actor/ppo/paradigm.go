// Package ppo — PPO paradigm Go-native adapter for gicg_actor pool。
//
// 当前 P2.1 scaffold(2026-05-22):仅 Configure + 注册;Run loop 走 stub return error。
// 后续 ship 完整 on-policy rollout loop with rollout_opponent 支持。
//
// Design:
// - PPO 不像 AZ 走 MCTS — 直接 forward + sample from logits + step,opp 走配置的
//   rollout_opponent('self' / 'random' / 'F{i}-D{j}')
// - Self-play 模式:两侧 me forward + sample(actor pool 内 actor 跑 me;p1 走 me 网络
//   或 frozen snapshot,见 PPO _rollout 的 rollout_opponent='self' 路径)
// - 每 transition payload 含:dyn / refs / pay / log_prob / value(GAE bootstrap)/
//   reward / done / action,reward 是 per-step engine-derived reward(非 terminal-only
//   like DMC)
//
// PPO opp 路线 vs DMC:
// - DMC opp = GreedyPlayer 跑生产 F1-D2,actor pool 内 sync 调用(no network)
// - PPO opp 可以是 GreedyPlayer 同 case 或 self(用同 me 网络 forward — 需要再发
//   InferenceClient request);P2.X ship 时 default 'F1-D2' (简单),self 走 P3 perf
//   驱动

package ppo

import (
	"encoding/json"
	"fmt"
	"sync"

	"gicg_mono/gicg_actor"
	"gicg_mono/gicg_engine/factory"
)

// PPOConfig — paradigm config JSON schema。 加 rollout_opponent + GAE 参数 vs DMC。
type PPOConfig struct {
	gicg_actor.BaseActorConfig

	MyPlayerStrategy string `json:"my_player_strategy"` // alternate | fixed_0 | fixed_1

	// PPO-specific
	RolloutOpponent string  `json:"rollout_opponent"` // 'self' | 'random' | 'F{i}-D{j}[-nogreedy]'
	Gamma           float32 `json:"gamma"`            // discount factor (0.99 typical)
	GAELambda       float32 `json:"gae_lambda"`       // GAE 平滑参数 (0.95 typical)
	Temperature     float32 `json:"temperature"`      // sampling temperature(1.0 = standard;0.0 = argmax)
}

// PPOParadigm implements gicg_actor.Paradigm。
type PPOParadigm struct {
	cfg     PPOConfig
	gameCfg factory.GameConfig
}

func (p *PPOParadigm) Name() string {
	return "ppo"
}

func (p *PPOParadigm) Configure(jsonCfg string) error {
	if jsonCfg == "" {
		return fmt.Errorf("PPOParadigm.Configure: empty JSON config")
	}
	var c PPOConfig
	if err := json.Unmarshal([]byte(jsonCfg), &c); err != nil {
		return fmt.Errorf("PPOParadigm.Configure: unmarshal PPOConfig: %w", err)
	}
	if err := c.Validate(); err != nil {
		return fmt.Errorf("PPOParadigm.Configure: %w", err)
	}
	if c.RolloutOpponent == "" {
		return fmt.Errorf("PPOParadigm.Configure: rollout_opponent missing(self|random|F{i}-D{j})")
	}
	if c.Gamma <= 0 || c.Gamma > 1 {
		return fmt.Errorf("PPOParadigm.Configure: gamma=%f must be in (0,1]", c.Gamma)
	}
	if c.GAELambda <= 0 || c.GAELambda > 1 {
		return fmt.Errorf("PPOParadigm.Configure: gae_lambda=%f must be in (0,1]", c.GAELambda)
	}
	if c.Temperature < 0 {
		return fmt.Errorf("PPOParadigm.Configure: temperature=%f must be >= 0", c.Temperature)
	}
	switch c.MyPlayerStrategy {
	case "alternate", "fixed_0", "fixed_1":
	case "":
		c.MyPlayerStrategy = "alternate"
	default:
		return fmt.Errorf("PPOParadigm.Configure: unknown my_player_strategy=%q", c.MyPlayerStrategy)
	}
	var gameCfg factory.GameConfig
	if err := json.Unmarshal(c.GameSpec, &gameCfg); err != nil {
		return fmt.Errorf("PPOParadigm.Configure: unmarshal game_spec: %w", err)
	}
	p.cfg = c
	p.gameCfg = gameCfg
	return nil
}

// Run — 完整 on-policy rollout loop。 impl 在 run.go(同 package,split for file budget)。

var registerOnce sync.Once

func init() {
	registerOnce.Do(func() {
		gicg_actor.RegisterParadigm("ppo", &PPOParadigm{})
	})
}
