package tests

// TestArcheLibSpike — ADR-0019 §A.3 Phase 1 spike。
// 验证 Arkhe 基础设施加载后:
//   1. Arkhe enum 注册 (None / Pneuma / Ousia 全局可访问,跟 Element 同质 namespace)
//   2. _arche_marker counter declared 全局可 get_counter
//   3. counter set/get round-trip 工作
//   4. set Arkhe.Ousia 后另一 hook get_counter 读出 Arkhe.Ousia(跨 hook 共享)
//
// 完整始基反应实施(N 张机关 / 克洛琳德等角色)留 Phase 2 per-card commit。
// 本 spike 仅验证基础设施 + DSL 接口可用。

import (
	"testing"

	"gicg_mono/gicg_engine/interp"
)

func TestArcheLibSpike(t *testing.T) {
	env := NewGameWithDeck(t, []string{"墨客"}, []string{"墨客"})
	sandbox := interp.NewEnv(env.RT.Interp.Global)

	// Test 1: Arkhe enum 全局可访问 + 值正确
	src1 := `
result_none = Arkhe.None
result_pneuma = Arkhe.Pneuma
result_ousia = Arkhe.Ousia
`
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src1), sandbox); err != nil {
		t.Fatalf("Arkhe enum access: %v", err)
	}
	type expectVal struct {
		name string
		want int
	}
	expects := []expectVal{
		{"result_none", 0},
		{"result_pneuma", 1},
		{"result_ousia", 2},
	}
	for _, e := range expects {
		v, _ := sandbox.Get(e.name)
		got, _ := toIntForArche(v)
		if got != e.want {
			t.Errorf("%s = %d, want %d", e.name, got, e.want)
		}
	}

	// Test 2: _arche_marker counter set/get round-trip
	src2 := `
local arche = get_counter("_arche_marker", Scope.Global)
arche:set(Arkhe.Ousia)
result_marker = arche:get()
`
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src2), sandbox); err != nil {
		t.Fatalf("counter set/get: %v", err)
	}
	v, _ := sandbox.Get("result_marker")
	got, _ := toIntForArche(v)
	if got != 2 {
		t.Errorf("after arche:set(Ousia) result = %d, want 2", got)
	}

	// Test 3: 跨 hook 共享 — set 后另一 ExecFile 仍能读到值
	src3 := `
local arche = get_counter("_arche_marker", Scope.Global)
result_persisted = arche:get()
`
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src3), sandbox); err != nil {
		t.Fatalf("counter persisted: %v", err)
	}
	v2, _ := sandbox.Get("result_persisted")
	got2, _ := toIntForArche(v2)
	if got2 != 2 {
		t.Errorf("counter persisted across ExecFile = %d, want 2", got2)
	}

	// Test 4: reset 行为 — set None 后 get 返 0
	src4 := `
local arche = get_counter("_arche_marker", Scope.Global)
arche:set(Arkhe.None)
result_reset = arche:get()
`
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src4), sandbox); err != nil {
		t.Fatalf("reset: %v", err)
	}
	v3, _ := sandbox.Get("result_reset")
	got3, _ := toIntForArche(v3)
	if got3 != 0 {
		t.Errorf("after arche:set(None) = %d, want 0", got3)
	}
}

// toIntForArche — 简化版 ToInt,避开 interp package import。
func toIntForArche(v any) (int, bool) {
	switch x := v.(type) {
	case int:
		return x, true
	case int64:
		return int(x), true
	case float64:
		return int(x), true
	}
	return 0, false
}
