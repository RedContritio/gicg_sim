package record

import (
	engine "gicg_mono/gicg_engine"
	"testing"
)

func TestPlayerZonesUseInstancesAndSupportSlots(t *testing.T) {
	g := &engine.Game{Hooks: engine.NewHookRegistry(), CardNames: map[int]string{42: "支援牌"}, CounterNames: map[int]string{}}
	add := func(name string, player, char int, summon bool, value int) int {
		id := g.CreateCounter(0, 0, 9)
		g.CounterNames[id] = name
		g.RegisterCounterChar(id, player, char)
		g.EnableCounterOrder(id, false)
		g.BuffDefinitions[g.Counters[id].BuffIndex].Summon = summon
		g.WriteCounter(id, engine.OpSet, value)
		return id
	}
	add("支援计数", 0, -1, false, 2)
	supportID := g.Buffs[0].ID
	g.Players[0].Supports = []engine.SupportInst{{Ref: 42, BuffID: supportID}}
	summon := add("名字不含召唤字样", 0, -1, true, 3)
	add("队伍状态", 0, -1, false, 4)
	add("角色状态", 0, 0, false, 1)
	add("对方效果", 1, -1, true, 2)
	supports, summons, statuses := buildPlayerZones(g, 0)
	if len(supports) != 1 || supports[0].Name != "支援牌" || supports[0].Value != 2 {
		t.Fatalf("supports: %+v", supports)
	}
	if len(summons) != 1 || summons[0].Name != "名字不含召唤字样" || summons[0].Value != 3 {
		t.Fatalf("summons: %+v", summons)
	}
	if len(statuses) != 1 || statuses[0].Name != "队伍状态" {
		t.Fatalf("statuses: %+v", statuses)
	}
	g.WriteCounter(summon, engine.OpSet, 0)
	_, summons, _ = buildPlayerZones(g, 0)
	if len(summons) != 0 {
		t.Fatal("consumed summon remains on board")
	}
}
