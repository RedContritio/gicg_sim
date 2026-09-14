package record

import (
	"encoding/json"
	"fmt"
	"strings"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/internal/strictjson"
)

// ReplayConfig identifies the random protocol and round-start configuration.
// It does not replace a complete mid-game snapshot: a seed alone cannot restore
// a generator after an arbitrary number of draws.
type ReplayConfig struct {
	RandomProtocol string `json:"random_protocol"`
	BaseSeed       int64  `json:"base_seed"`
	MaxRounds      int    `json:"max_rounds"`
	FixDice        []int  `json:"fix_dice"`
}

func writeConfig(b *strings.Builder, g *engine.Game) {
	c := ReplayConfig{engine.RandomProtocol, g.BaseSeed, g.MaxRounds, g.FixDice}
	data, err := json.Marshal(c)
	if err != nil {
		panic(err)
	} // contains only JSON primitive values
	fmt.Fprintf(b, "config: %s\n", data)
}

func (c *ReplayConfig) validate() error {
	if c.RandomProtocol != engine.RandomProtocol {
		return fmt.Errorf("unsupported replay random protocol %q (engine uses %q)", c.RandomProtocol, engine.RandomProtocol)
	}
	if c.MaxRounds < 0 {
		return fmt.Errorf("negative replay max_rounds")
	}
	if len(c.FixDice) != 0 && len(c.FixDice) != engine.DiceColorCount {
		return fmt.Errorf("replay fix_dice must contain %d counts", engine.DiceColorCount)
	}
	for _, count := range c.FixDice {
		if count < 0 {
			return fmt.Errorf("negative replay dice count")
		}
	}
	return nil
}

func parseConfig(src string) (*ReplayConfig, error) {
	var c ReplayConfig
	if err := strictjson.Decode([]byte(src), &c); err != nil {
		return nil, fmt.Errorf("replay config: %w", err)
	}
	if err := c.validate(); err != nil {
		return nil, err
	}
	return &c, nil
}
