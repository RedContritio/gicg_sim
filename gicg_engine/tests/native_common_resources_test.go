package tests

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestNativeResourceCardsBothSeats(t *testing.T) {
	for _, p := range []int{0, 1} {
		t.Run(fmt.Sprintf("P%d", p), func(t *testing.T) {
			e := nativeTalentGame(t, "凯亚")
			auditPlay(t, e, p, "星天之兆")
			if e.Energy(p, 0) != 1 || e.Energy(p, 1) != 0 || e.Energy(1-p, 0) != 0 || e.DiceTotal(p) != 14 {
				t.Fatal("starsigns changed wrong energy or cost")
			}
			ref := e.cardRef("甜甜花酿鸡")
			e.G.Players[p].Deck = []engine.CardInst{{Ref: ref}, {Ref: ref}, {Ref: e.cardRef("莲花酥")}}
			auditPlay(t, e, p, "运筹帷幄")
			if len(e.G.Players[p].Deck) != 1 || len(e.G.Players[p].Hand) != 2 ||
				len(e.G.Players[1-p].Hand) != 0 || e.DiceTotal(p) != 13 {
				t.Fatal("strategize must draw exactly two for its owner and cost one")
			}
			e.SetDice(p, map[int]int{engine.DiceColorFire: 2})
			auditPlay(t, e, p, "最好的伙伴！")
			if e.DiceTotal(p) != 2 || e.RT.DicePool(p)[engine.DiceColorOmni] != 2 || e.G.Turn != p {
				t.Fatal("companion must convert payment into two omni dice as a fast action")
			}
		})
	}
}

func TestNativeRoundLimitedFoodsExpireUnused(t *testing.T) {
	for _, p := range []int{0, 1} {
		for _, spec := range []struct{ name, counter string }{
			{"莲花酥", "莲花酥_状态"}, {"北地烟熏鸡", "北地烟熏鸡_次数"}, {"兽肉薄荷卷", "兽肉薄荷卷_次数"},
		} {
			t.Run(fmt.Sprintf("%s_P%d", spec.name, p), func(t *testing.T) {
				e := nativeTalentGame(t, "凯亚")
				nativePlayTarget(t, e, p, 1, spec.name)
				e.playToRoundEnd(t)
				if e.counterByChar(spec.counter, p, 1) != 0 || e.counterByChar("饱腹", p, 1) != 0 {
					t.Fatal("unused food or satiety survived the round")
				}
			})
		}
	}
}
