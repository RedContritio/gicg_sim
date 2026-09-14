package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"gicg_mono/gicg_engine/audit"
	"gicg_mono/gicg_engine/factory"
	"os"
)

func main() {
	input := flag.String("config", "", "factory GameConfig JSON; default current legacy character coverage")
	flag.Parse()
	cfg := factory.GameConfig{DataDir: "data", Pools: []string{"v_legacy", "test_basic"}, Seed: 42}
	for p := 0; p < 2; p++ {
		cfg.Players[p] = factory.PConfig{Chars: []factory.CharDef{{Name: "赤蝶"}, {Name: "墨客"}}, Deck: []string{"碌碌无为"}}
	}
	if *input != "" {
		data, err := os.ReadFile(*input)
		if err != nil {
			panic(err)
		}
		if err = json.Unmarshal(data, &cfg); err != nil {
			panic(err)
		}
	}
	h, err := factory.NewGame(cfg)
	if err != nil {
		panic(err)
	}
	r := audit.Effects(h.Game)
	out := json.NewEncoder(os.Stdout)
	out.SetIndent("", "  ")
	if err = out.Encode(r); err != nil {
		panic(err)
	}
	if len(r.Issues) > 0 {
		fmt.Fprintln(os.Stderr, "effect audit failed")
		os.Exit(1)
	}
}
