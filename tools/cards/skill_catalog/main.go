// Export original skill declarations through the same DSL loader as gameplay.
package main

import (
	"encoding/json"
	"gicg_mono/gicg_engine/factory"
	"gicg_mono/gicg_engine/interp"
	"os"
)

func main() {
	var cfg factory.GameConfig
	if err := json.NewDecoder(os.Stdin).Decode(&cfg); err != nil {
		panic(err)
	}
	h, err := factory.NewGame(cfg)
	if err != nil {
		panic(err)
	}
	skills := make([]*interp.SkillRef, 0, len(h.RT.Skills.ByID))
	for id := 0; id < h.RT.Skills.NextID; id++ {
		if skill := h.RT.Skills.ByID[id]; skill != nil {
			skills = append(skills, skill)
		}
	}
	if err := json.NewEncoder(os.Stdout).Encode(skills); err != nil {
		panic(err)
	}
}
