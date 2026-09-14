package tests

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"testing"
)

func TestRetaliationOwnerAndTargets(t *testing.T) {
	for _, p := range []int{0, 1} {
		for _, trigger := range []string{"enemy_overheal", "absorb"} {
			t.Run(fmt.Sprintf("%d/%s", p, trigger), func(t *testing.T) {
				e := currentCardGame(t, p)
				auditPlay(t, e, p, "以逸待劳")
				e.G.RewardAccum = [2]engine.RewardEvents{}
				hp := e.RT.Chars.BySlot[p][0].HPCounterID
				if trigger == "enemy_overheal" {
					e.G.ExecuteEffect(engine.EventFrame{Player: 1 - p, Char: 0, Source: engine.SrcCard}, func(g *engine.Game) { g.Heal(hp, 3) })
					if e.HP(p, 0) != 15 || e.HP(1-p, 0) != 12 || e.G.RewardAccum[p].DamageDealt != 3 || e.G.RewardAccum[1-p].DamageDealt != 0 {
						t.Fatalf("enemy healing misattributed or mistargeted: HP=%d/%d reward=%+v", e.HP(p, 0), e.HP(1-p, 0), e.G.RewardAccum)
					}
				} else {
					id := findCounterIDPerPlayer(e, "结晶护盾", p)
					e.G.WriteCounter(id, engine.OpSet, 2)
					e.G.ExecuteEffect(engine.EventFrame{Player: 1 - p, Char: 0, Source: engine.SrcCard}, func(g *engine.Game) {
						g.DealDamage(hp, engine.ElemPhysical, 3, engine.DamageOpts{ActorPlayer: -1, ActorChar: -1})
					})
					if e.HP(p, 0) != 14 || e.HP(1-p, 0) != 13 || e.G.RewardAccum[p].DamageDealt != 2 || e.G.RewardAccum[1-p].DamageDealt != 1 {
						t.Fatalf("absorption retaliation misattributed: HP=%d/%d reward=%+v", e.HP(p, 0), e.HP(1-p, 0), e.G.RewardAccum)
					}
				}
			})
		}
	}
}
