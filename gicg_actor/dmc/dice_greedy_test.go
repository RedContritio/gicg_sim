// dice_greedy_test.go — filterLogicalActions / buildColorValues / paymentCost 单测。
//
// 真 game(factory.NewGame),不 stub:折叠正确性必须跑真 GetLegalActions() fan-out。

package dmc

import (
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/factory"
)

// newTestGame 构真 game 并 step 到 action phase(过 select-active)。
// 返回 *engine.Game,Extra 已绑 interp.Runtime(DicePoolProvider)。
func newTestGame(t *testing.T) *engine.Game {
	t.Helper()
	cfg := factory.GameConfig{
		Pools: []string{"v_legacy"},
		Seed:  42,
	}
	cfg.Players[0].Chars = []factory.CharDef{{Name: "赤蝶"}, {Name: "墨客"}}
	cfg.Players[1].Chars = []factory.CharDef{{Name: "墨客"}, {Name: "赤蝶"}}
	h, err := factory.NewGame(cfg)
	if err != nil {
		t.Fatalf("NewGame: %v", err)
	}
	g := h.Game

	// Step 过 select-active phase:两玩家各选 1 出战角色(取第一个 legal action)。
	for guard := 0; guard < 64 && g.Phase == engine.PhaseSelectActive; guard++ {
		acts := g.GetLegalActions()
		if len(acts) == 0 {
			t.Fatalf("select-active: no legal actions at phase %v", g.Phase)
		}
		g.Step(0)
	}
	if g.Phase == engine.PhaseGameOver {
		t.Fatalf("game ended during setup")
	}
	return g
}

// TestPaymentCost 守 Σ_c (payment[c] × value[c])。
func TestPaymentCost(t *testing.T) {
	var values [engine.DiceColorCount]int
	values[engine.DiceColorFire] = 1000
	values[engine.DiceColorWater] = 30
	values[engine.DiceColorOmni] = 500

	var payment [engine.DiceColorCount]int8
	payment[engine.DiceColorFire] = 1
	payment[engine.DiceColorWater] = 2
	payment[engine.DiceColorOmni] = 1

	got := paymentCost(payment, values)
	want := 1*1000 + 2*30 + 1*500
	if got != want {
		t.Errorf("paymentCost: got %d, want %d", got, want)
	}

	// 空 payment → 0。
	var empty [engine.DiceColorCount]int8
	if c := paymentCost(empty, values); c != 0 {
		t.Errorf("empty payment cost: got %d, want 0", c)
	}
}

// TestBuildColorValues_Tiers 守 role-based tier 覆盖 + 杂色 pool-count base。
func TestBuildColorValues_Tiers(t *testing.T) {
	g := newTestGame(t)
	me := g.ActingPlayer()

	// 构一个 dice pool:active-color 应被抬到 1000,omni 抬到 500,
	// 杂色 base = 10 × count。
	var pool [engine.DiceColorCount]int
	for c := 0; c < engine.DiceColorCount; c++ {
		pool[c] = c // 0,1,2,...,7 — 任意非平凡分布
	}
	values := buildColorValues(g, me, pool)

	// omni 永远 ≥ 500(即使 pool 里 omni count=7 → junk base 70,被 500 抬上去)。
	if values[engine.DiceColorOmni] < valueOmni {
		t.Errorf("omni value %d < %d", values[engine.DiceColorOmni], valueOmni)
	}

	// 出战角色 element 对应 color 应 = 1000(active tier)。
	activeIdx := g.Players[me].ActiveChar
	if activeIdx >= 0 && activeIdx < len(g.Players[me].Chars) {
		ac := engine.ElementToDiceColor(g.Players[me].Chars[activeIdx].Element)
		if ac >= 0 && values[ac] < valueActive {
			t.Errorf("active color %d value %d < %d", ac, values[ac], valueActive)
		}
	}

	// 杂色(无 role,非 omni)value = 10 × pool_count(无 role override 时)。
	// color 抬升只增不减,所以每个 value ≥ 10 × pool_count。
	for c := 0; c < engine.DiceColorCount; c++ {
		if values[c] < valueJunkPerCount*pool[c] {
			t.Errorf("color %d value %d < junk base %d", c, values[c], valueJunkPerCount*pool[c])
		}
	}
}

// TestBuildColorValues_OmniEvenWhenScarce 守 omni 即使 pool count=0/1 也拿 500。
func TestBuildColorValues_OmniEvenWhenScarce(t *testing.T) {
	g := newTestGame(t)
	me := g.ActingPlayer()
	var pool [engine.DiceColorCount]int // 全 0
	values := buildColorValues(g, me, pool)
	if values[engine.DiceColorOmni] != valueOmni {
		t.Errorf("omni with 0 pool: got %d, want %d", values[engine.DiceColorOmni], valueOmni)
	}
}

// TestFilterLogicalActions_NoDuplicateIdentity 守:折叠后每 identity 只出现一次,
// 且返回 index 数 ≤ len(GetLegalActions())。
func TestFilterLogicalActions_NoDuplicateIdentity(t *testing.T) {
	g := newTestGame(t)
	actions := g.GetLegalActions()
	if len(actions) == 0 {
		t.Skip("no legal actions in this scenario")
	}

	chosen := filterLogicalActions(g)

	if len(chosen) > len(actions) {
		t.Fatalf("folded count %d > total %d", len(chosen), len(actions))
	}
	if len(chosen) == 0 {
		t.Fatal("folded count is 0 but GetLegalActions non-empty")
	}

	// 每个 chosen index 合法 + 升序。
	for i, idx := range chosen {
		if idx < 0 || idx >= len(actions) {
			t.Fatalf("chosen[%d]=%d out of range [0,%d)", i, idx, len(actions))
		}
		if i > 0 && chosen[i-1] >= idx {
			t.Errorf("chosen not strictly ascending at %d: %d >= %d", i, chosen[i-1], idx)
		}
	}

	// chosen 的 identity 集合互异。
	seen := map[[5]int]bool{}
	for _, idx := range chosen {
		key := actionIdentity(g, actions[idx])
		if seen[key] {
			t.Errorf("duplicate identity %v in folded set", key)
		}
		seen[key] = true
	}

	// 折叠完整性:GetLegalActions() 里**每个** identity 都应在 chosen 里被代表。
	allIdentities := map[[5]int]bool{}
	for _, a := range actions {
		allIdentities[actionIdentity(g, a)] = true
	}
	if len(seen) != len(allIdentities) {
		t.Errorf("folded covers %d identities, total distinct %d", len(seen), len(allIdentities))
	}
}

// TestFilterLogicalActions_FoldsFanout 守:确实发生折叠 —
// 找一个有 dice payment fan-out 的场景,验证 N_logical < N。
//
// 引擎对带 'any' cost slot 的动作 fan-out 成 C(pool, k) 个 payment。 用初始
// dice pool(8 omni or 随机色)+ v_legacy 角色,action phase 通常至少一个技能/卡有
// fan-out。 若该场景无 fan-out,扫几步直到出现(或 skip 并说明)。
func TestFilterLogicalActions_FoldsFanout(t *testing.T) {
	g := newTestGame(t)

	foundFanout := false
	for guard := 0; guard < 40 && g.Phase != engine.PhaseGameOver; guard++ {
		actions := g.GetLegalActions()
		if len(actions) == 0 {
			break
		}
		chosen := filterLogicalActions(g)

		if len(chosen) < len(actions) {
			foundFanout = true
			t.Logf("fan-out folded: N=%d → N_logical=%d (step guard=%d, phase=%v)",
				len(actions), len(chosen), guard, g.Phase)

			// 验证折叠确实是"组内选 min payment_cost"。 重算一遍 group → min。
			me := g.ActingPlayer()
			provider := g.Extra.(engine.DicePoolProvider)
			var pool [engine.DiceColorCount]int
			for c := 0; c < engine.DiceColorCount; c++ {
				pool[c] = g.Counters[provider.DiceCounterID(me, c)].Value
			}
			values := buildColorValues(g, me, pool)
			// 对每个 chosen,确认它在自己的 identity group 里 cost 最小。
			for _, idx := range chosen {
				key := actionIdentity(g, actions[idx])
				chosenCost := paymentCost(actions[idx].DicePayment, values)
				for j, a := range actions {
					if actionIdentity(g, a) != key {
						continue
					}
					jCost := paymentCost(a.DicePayment, values)
					if jCost < chosenCost {
						t.Errorf("idx %d (cost %d) not min in group %v: idx %d has cost %d",
							idx, chosenCost, key, j, jCost)
					}
				}
			}
			break
		}
		// 无 fan-out — step 1 步继续找(取折叠后第一个 candidate)。
		g.Step(chosen[0])
	}

	if !foundFanout {
		t.Skip("no dice fan-out encountered in 40 steps for this scenario — engine produced 1 payment per logical action throughout")
	}
}

// TestFilterLogicalActions_GameOver 守 game-over → 空返回(GetLegalActions nil)。
func TestFilterLogicalActions_GameOver(t *testing.T) {
	g := newTestGame(t)
	g.Phase = engine.PhaseGameOver
	if chosen := filterLogicalActions(g); chosen != nil {
		t.Errorf("game-over should yield nil, got %v", chosen)
	}
}
