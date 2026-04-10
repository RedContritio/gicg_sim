package lua

import (
	"gicg_mono/gicg_engine"
	"testing"
)

func TestLoadFilesWithDeps_Order(t *testing.T) {
	g := engine.NewGame(engine.GameConfig{
		Players: [2]engine.PlayerConfig{
			{Chars: []engine.CharConfig{{}}},
			{Chars: []engine.CharConfig{{}}},
		},
	})
	g.Players[0].ActiveChar = 0
	g.Players[1].ActiveChar = 0

	s := NewState()
	InitCounterMetatable(s)
	RegisterPrelude(s, g)
	defer s.Close()
	defer Cleanup(s)

	// reaction.lua depends on element.lua (get_counter("attached_fire"))
	// 故意把 reaction.lua 排在 element.lua 前面
	err := s.LoadFilesWithDeps([]string{
		"../../data/system/reaction.lua",
		"../../data/system/element.lua",
	})
	if err != nil {
		t.Fatalf("LoadFilesWithDeps: %v", err)
	}

	// 验证 element counter 存在且可用
	if err := s.DoString(`
		_v = get_counter("attached_fire", Scope.PerChar):get_at(0, 0)
	`); err != nil {
		t.Fatalf("get attached_fire: %v", err)
	}
	v, _ := s.GetGlobalInt("_v")
	if v != 0 {
		t.Fatalf("expected 0, got %d", v)
	}
}
