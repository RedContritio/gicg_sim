package tests

// TestFindCharByKindSpike — ADR-0019 §A.2 spike。
// 验证 find_char_by_kind(player, kind) 返回正确 char_idx 对 5 种 Kind:
//   - LowestHp:HP 最低活角色
//   - HighestHp:HP 最高
//   - LeastDamaged:Init - Value 最小(受伤最少)
//   - RandomNonActive:随机非出战(deterministic 用 fixed RNG)
//   - PreviousActive:fallback 到 active(future 未实现)
//
// 用 1v3 测试场景:玛薇卡(HP 10) + 歼灭机关 ×2(HP 10),手动 set HP
// 制造差异。

import (
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

func TestFindCharByKindSpike(t *testing.T) {
	env := NewGameWithDeck(t, []string{"歼灭机关", "歼灭机关", "歼灭机关"}, []string{"歼灭机关"})
	g := env.G

	// 取 P0 三角色 HP counter ID
	hpIDs := []int{
		env.RT.Chars.BySlot[0][0].HPCounterID,
		env.RT.Chars.BySlot[0][1].HPCounterID,
		env.RT.Chars.BySlot[0][2].HPCounterID,
	}
	for _, id := range hpIDs {
		if id < 0 {
			t.Fatalf("char HPCounterID -1, char registry not bound")
		}
	}

	// 手动 set HP:char 0 = 5,char 1 = 10,char 2 = 3
	g.Counters[hpIDs[0]].Value = 5
	g.Counters[hpIDs[1]].Value = 10
	g.Counters[hpIDs[2]].Value = 3
	// Init 是初始 max HP = 10(歼灭机关 default)
	for _, id := range hpIDs {
		if g.Counters[id].Init != 10 {
			t.Fatalf("counter %d Init = %d, expect 10 (歼灭机关 max HP)", id, g.Counters[id].Init)
		}
	}

	// 通过 lua DSL 调 find_char_by_kind 获取结果 — 用 set_local 接收
	tests := []struct {
		name     string
		kind     int
		expected int // -1 表示 unknown(随机 case 验另路径)
	}{
		{"LowestHp", interp.CharKindLowestHp, 2},         // HP 3 (char 2)
		{"HighestHp", interp.CharKindHighestHp, 1},       // HP 10 (char 1)
		{"LeastDamaged", interp.CharKindLeastDamaged, 1}, // Init-Value=0
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// 通过直接 Go 调用验证(避开 lua eval 复杂性):
			// 我们直接 call rt.builtinFindCharByKind via reflection 不便,
			// 改用 lua exec 然后 read variable
			src := `local r = find_char_by_kind(0, ` + intStr(tt.kind) + `)
result_var = r`
			env_lua := interp.NewEnv(env.RT.Interp.Global)
			env_lua.SetLocal("result_var", -999)
			if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env_lua); err != nil {
				t.Fatalf("ExecFile: %v", err)
			}
			r, _ := env_lua.Get("result_var")
			got, _ := interp.ToInt(r)
			if got != tt.expected {
				t.Errorf("kind=%d (%s): got char_idx=%d, want %d", tt.kind, tt.name, got, tt.expected)
			}
		})
	}

	// RandomNonActive:active = char 0;非出战 = {1, 2};用 deterministic RNG
	// 应 deterministic 选其中之一(具体哪个看 RNG 实现,主要验"不是 active")
	t.Run("RandomNonActive", func(t *testing.T) {
		src := `local r = find_char_by_kind(0, ` + intStr(interp.CharKindRandomNonActive) + `)
result_var = r`
		env_lua := interp.NewEnv(env.RT.Interp.Global)
		env_lua.SetLocal("result_var", -999)
		if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env_lua); err != nil {
			t.Fatalf("ExecFile: %v", err)
		}
		r, _ := env_lua.Get("result_var")
		got, _ := interp.ToInt(r)
		active := g.Players[0].ActiveChar
		if got == active {
			t.Errorf("RandomNonActive returned active char %d", active)
		}
		if got != 1 && got != 2 {
			t.Errorf("RandomNonActive got %d, expect 1 or 2", got)
		}
	})

	// PreviousActive:fallback 到 active(future 未实现)
	t.Run("PreviousActive_fallback", func(t *testing.T) {
		src := `local r = find_char_by_kind(0, ` + intStr(interp.CharKindPreviousActive) + `)
result_var = r`
		env_lua := interp.NewEnv(env.RT.Interp.Global)
		env_lua.SetLocal("result_var", -999)
		if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env_lua); err != nil {
			t.Fatalf("ExecFile: %v", err)
		}
		r, _ := env_lua.Get("result_var")
		got, _ := interp.ToInt(r)
		active := g.Players[0].ActiveChar
		if got != active {
			t.Errorf("PreviousActive (future fallback) got %d, expect active=%d", got, active)
		}
	})

	// 边界:dead char 不应被找到
	t.Run("DeadCharExcluded", func(t *testing.T) {
		// kill char 2 (HP=3 设 alive=false)
		g.Players[0].Chars[2].Alive = false
		src := `local r = find_char_by_kind(0, ` + intStr(interp.CharKindLowestHp) + `)
result_var = r`
		env_lua := interp.NewEnv(env.RT.Interp.Global)
		env_lua.SetLocal("result_var", -999)
		if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env_lua); err != nil {
			t.Fatalf("ExecFile: %v", err)
		}
		r, _ := env_lua.Get("result_var")
		got, _ := interp.ToInt(r)
		// 现在活角色 = char 0 (HP=5) + char 1 (HP=10),最低 = char 0
		if got != 0 {
			t.Errorf("DeadCharExcluded LowestHp got %d, expect 0", got)
		}
		// 恢复
		g.Players[0].Chars[2].Alive = true
	})

	// 边界:全员死亡返回 -1
	t.Run("AllDeadReturnsMinus1", func(t *testing.T) {
		for i := range g.Players[0].Chars {
			g.Players[0].Chars[i].Alive = false
		}
		src := `local r = find_char_by_kind(0, ` + intStr(interp.CharKindLowestHp) + `)
result_var = r`
		env_lua := interp.NewEnv(env.RT.Interp.Global)
		env_lua.SetLocal("result_var", -999)
		if err := env.RT.Interp.ExecFile(env.RT, []byte(src), env_lua); err != nil {
			t.Fatalf("ExecFile: %v", err)
		}
		r, _ := env_lua.Get("result_var")
		got, _ := interp.ToInt(r)
		if got != -1 {
			t.Errorf("AllDead expect -1, got %d", got)
		}
		// 恢复(无所谓,test 结束)
		_ = engine.OpSet
	})
}

func intStr(i int) string {
	if i == 0 {
		return "0"
	}
	neg := false
	if i < 0 {
		neg = true
		i = -i
	}
	var buf []byte
	for i > 0 {
		buf = append([]byte{byte('0' + i%10)}, buf...)
		i /= 10
	}
	if neg {
		buf = append([]byte{'-'}, buf...)
	}
	return string(buf)
}
