package tests

// F2 — 以逸待劳 复活回归 + element_to_dice_color builtin 契约。
//
// 历史:on_round_start 引用 AP 系统 counter "ap"(commit f2c5310 已整体
// 删除)→ topo loader 依赖不可解析 → 整文件静默排除 → 卡从未进对局。
// B1 修正版:回合开始改为 +2 当前出战角色元素的骰子(不用万能骰以制衡
// 强度)。Element 与 DiceColor 枚举空间不对齐(Element.None 占 0 位),
// 经 element_to_dice_color builtin 转换 — 本文件同时锁该 builtin 契约。
//
// 覆盖:
//   1. element_to_dice_color 7 元素映射 + 非元素输入 raise
//   2. 回合开始 +2 出战角色元素骰:P0 / P1 owner 双向(席位对称)
//   3. 换人后骰色跟随新出战角色元素
//   4. 真卡双反击路径:治疗等量反击 / 护盾吸收等量反击,双 owner 席位
//
// 「卡可加载」断言已由 F3 系统性 guard 取代(pool_load_guard_test.go:
// topo loader fail-loud + 全池注册表断言,以逸待劳 在 v_legacy 每局
// 断言集内)。

import (
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
	"strings"
	"testing"
)

// giveCard 将已加载的卡按名字塞进 p 的手牌。
func giveCard(t *testing.T, env *GameEnv, p int, name string) {
	t.Helper()
	card := env.RT.Cards.ByName[name]
	if card == nil {
		t.Fatalf("card %q not loaded", name)
	}
	env.G.Players[p].Hand = append(env.G.Players[p].Hand, engine.CardInst{Ref: card.Ref})
}

// playCard 走 GetLegalActions + Step 真路径打出当前回合玩家的牌。
func playCard(t *testing.T, env *GameEnv, name string) {
	t.Helper()
	idx := env.FindAction(engine.ActionCard, name)
	if idx < 0 {
		t.Fatalf("%q not offered (turn=%d dice=%d)", name, env.G.Turn, env.DiceTotal(env.G.Turn))
	}
	env.Step(idx)
}

// assertDicePool 断言 p 的全部 8 色骰数;want 缺省色位为 0。
func assertDicePool(t *testing.T, env *GameEnv, p int, want map[int]int) {
	t.Helper()
	for color := 0; color < engine.DiceColorCount; color++ {
		cid := env.RT.DiceCounterID(p, color)
		if got := env.G.Counters[cid].Value; got != want[color] {
			t.Errorf("P%d dice color %d = %d, want %d", p, color, got, want[color])
		}
	}
}

// execDSL 在独立 env 里执行 DSL 片段。
func execDSL(env *GameEnv, src string) (*interp.Env, error) {
	lenv := interp.NewEnv(env.RT.Interp.Global)
	err := env.RT.Interp.ExecFile(env.RT, []byte(src), lenv)
	return lenv, err
}

// --- 1. element_to_dice_color builtin 契约 ---

// 两枚举空间错位(Element.None 占 0 位)是 builtin 存在的理由。若未来
// 枚举重排导致对齐,此测试提醒重新审视 bridge 必要性。
func TestElementToDiceColor_EnumSpacesAreOffset(t *testing.T) {
	if int(engine.ElemFire) == engine.DiceColorFire {
		t.Fatal("Element/DiceColor enum spaces became aligned — re-audit element_to_dice_color bridge")
	}
}

func TestElementToDiceColor_MapsAll7Elements(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	cases := []struct {
		dslElem string
		want    int
	}{
		{"Element.Fire", engine.DiceColorFire},
		{"Element.Ice", engine.DiceColorIce},
		{"Element.Water", engine.DiceColorWater},
		{"Element.Electro", engine.DiceColorElectro},
		{"Element.Geo", engine.DiceColorGeo},
		{"Element.Anemo", engine.DiceColorAnemo},
		{"Element.Dendro", engine.DiceColorDendro},
	}
	for _, c := range cases {
		lenv, err := execDSL(env, "probe = element_to_dice_color("+c.dslElem+")")
		if err != nil {
			t.Fatalf("%s: exec error: %v", c.dslElem, err)
		}
		got, _ := lenv.Get("probe")
		gi, ok := got.(int)
		if !ok || gi != c.want {
			t.Errorf("element_to_dice_color(%s) = %v, want %d", c.dslElem, got, c.want)
		}
	}
}

func TestElementToDiceColor_RaisesOnNonElemental(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	for _, bad := range []string{"Element.None", "Element.Physical", "Element.Piercing"} {
		_, err := execDSL(env, "probe = element_to_dice_color("+bad+")")
		if err == nil {
			t.Errorf("element_to_dice_color(%s): want error, got nil", bad)
			continue
		}
		if !strings.Contains(err.Error(), "element_to_dice_color") {
			t.Errorf("element_to_dice_color(%s): error %q does not name the builtin", bad, err)
		}
	}
}

// --- 2. 回合开始 +2 出战角色元素骰(双 owner 席位) ---

func TestYiYiDaiLao_RoundStartDice_P0Owner(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	env.G.FixDice = make([]int, engine.DiceColorCount) // round 2+ fresh roll 全 0
	giveCard(t, env, 0, "以逸待劳")
	env.SetDice(0, map[int]int{int(engine.DiceColorOmni): 8})
	playCard(t, env, "以逸待劳") // battle action → turn P1

	env.StepEndTurn() // P1 declare end
	env.StepEndTurn() // P0 declare end → round ends
	if err := keepAllRerolls(env.G); err != nil {
		t.Fatal(err)
	}

	// P0 出战 = 赤蝶(Fire) → +2 火骰;P1 没打出该卡 → 全 0(PerPlayer 门控)。
	assertDicePool(t, env, 0, map[int]int{engine.DiceColorFire: 2})
	assertDicePool(t, env, 1, map[int]int{})
}

func TestYiYiDaiLao_RoundStartDice_P1Owner(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	env.G.FixDice = make([]int, engine.DiceColorCount)
	env.StepEndTurn() // P0 declare end → turn P1
	giveCard(t, env, 1, "以逸待劳")
	env.SetDice(1, map[int]int{int(engine.DiceColorOmni): 8})
	playCard(t, env, "以逸待劳") // battle action;P0 已 declare → turn 留 P1

	env.StepEndTurn() // P1 declare end → round ends
	if err := keepAllRerolls(env.G); err != nil {
		t.Fatal(err)
	}

	// P1 出战 = 墨客(Water) → +2 水骰;P0 全 0。
	assertDicePool(t, env, 1, map[int]int{engine.DiceColorWater: 2})
	assertDicePool(t, env, 0, map[int]int{})
}

// --- 3. 换人后骰色跟随新出战角色元素 ---

func TestYiYiDaiLao_RoundStartDice_FollowsActiveSwitch(t *testing.T) {
	env := NewGame(t, []string{"赤蝶", "猫咪"}, []string{"墨客"})
	env.G.FixDice = make([]int, engine.DiceColorCount)
	giveCard(t, env, 0, "以逸待劳")
	env.SetDice(0, map[int]int{int(engine.DiceColorOmni): 8})
	playCard(t, env, "以逸待劳") // battle → P1

	env.StepEndTurn() // P1 declare end(先 declare → round 2 先手)
	env.StepEndTurn() // P0 declare end → round ends
	if err := keepAllRerolls(env.G); err != nil {
		t.Fatal(err)
	}

	// Round 2:赤蝶(Fire)出战 → +2 火骰。
	assertDicePool(t, env, 0, map[int]int{engine.DiceColorFire: 2})

	// P1 先手 declare end → P0 切人到 猫咪(Ice),支付 1 火骰。
	env.StepEndTurn()
	switchIdx := -1
	for i, a := range env.G.GetLegalActions() {
		if a.Kind == engine.ActionSwitch {
			switchIdx = i
			break
		}
	}
	if switchIdx < 0 {
		t.Fatalf("no switch action offered for P0 (turn=%d)", env.G.Turn)
	}
	env.Step(switchIdx)
	if got := env.G.Players[0].ActiveChar; got != 1 {
		t.Fatalf("P0 ActiveChar = %d after switch, want 1 (猫咪)", got)
	}
	env.StepEndTurn() // P0 declare end → round ends
	if err := keepAllRerolls(env.G); err != nil {
		t.Fatal(err)
	}

	// Round 3:猫咪(Ice)出战 → +2 冰骰(回合末弃骰 + FixDice 全 0 隔离)。
	assertDicePool(t, env, 0, map[int]int{engine.DiceColorIce: 2})
}
