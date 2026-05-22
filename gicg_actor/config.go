// config.go — paradigm-agnostic actor config 基类。
//
// DMC / AZ / PPO 三个 paradigm 的 cfg struct 都需要 game_spec / max_actions /
// max_episode_steps / base_seed 这组字段 —— 抽成 BaseActorConfig,各 paradigm cfg
// anonymous-embed 它(Go encoding/json 自动提升 embedded struct 的 tagged 字段,
// 故 wire 格式不变)。 paradigm-specific 字段(DMC 对手 / AZ MCTS / PPO GAE)各自留。

package gicg_actor

import (
	"encoding/json"
	"fmt"
)

// BaseActorConfig — 所有 paradigm actor cfg 共享的通用字段。
type BaseActorConfig struct {
	GameSpec        json.RawMessage `json:"game_spec"`
	MaxActions      int             `json:"max_actions"`
	MaxEpisodeSteps int             `json:"max_episode_steps"`
	BaseSeed        int64           `json:"base_seed"`
}

// Validate — 通用字段校验,各 paradigm Configure 调用(fail loud,不静默纠正)。
func (c *BaseActorConfig) Validate() error {
	if len(c.GameSpec) == 0 || string(c.GameSpec) == "null" {
		return fmt.Errorf("game_spec missing")
	}
	if c.MaxActions <= 0 {
		return fmt.Errorf("max_actions=%d must be positive", c.MaxActions)
	}
	if c.MaxEpisodeSteps <= 0 {
		return fmt.Errorf("max_episode_steps=%d must be positive", c.MaxEpisodeSteps)
	}
	return nil
}
