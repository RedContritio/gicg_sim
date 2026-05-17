package interp

import (
	engine "gicg_mono/gicg_engine"
)

// registerEnums installs all DSL-visible enum tables into the global
// environment. Called from RegisterBuiltins.
func (rt *Runtime) registerEnums() {
	g := rt.Interp.Global

	setEnum := func(name string, vals map[string]int) {
		t := NewTable()
		for k, v := range vals {
			t.Fields[k] = v
		}
		g.SetLocal(name, t)
	}

	setEnum("Element", map[string]int{
		"None": int(engine.ElemNone), "Fire": int(engine.ElemFire),
		"Ice": int(engine.ElemIce), "Water": int(engine.ElemWater),
		"Electro": int(engine.ElemElectro), "Geo": int(engine.ElemGeo),
		"Anemo": int(engine.ElemAnemo), "Dendro": int(engine.ElemDendro),
		"Physical": int(engine.ElemPhysical),
		"Piercing": int(engine.ElemPiercing), // ADR-0019 §B.1
	})
	setEnum("Scope", map[string]int{
		"Self": ScopeSelf, "ActiveStatus": ScopeActiveStatus,
		"PerChar": ScopePerChar, "PerPlayer": ScopePerPlayer, "Global": ScopeGlobal,
	})
	setEnum("Player", map[string]int{
		"Own": PlayerOwn, "Enemy": PlayerEnemy, "All": PlayerAll,
	})
	setEnum("Op", map[string]int{
		"Set": int(engine.OpSet), "Add": int(engine.OpAdd), "Sub": int(engine.OpSub),
	})
	setEnum("Tag", map[string]int{
		"Summon": 1, "Element": 2, "Equip": 3, "Food": 4,
		"Support": 5, "Shield": 6, "Dice": 7, "Specialty": 8,
	})
	setEnum("DiceColor", map[string]int{
		"Fire":    engine.DiceColorFire,
		"Ice":     engine.DiceColorIce,
		"Water":   engine.DiceColorWater,
		"Electro": engine.DiceColorElectro,
		"Geo":     engine.DiceColorGeo,
		"Anemo":   engine.DiceColorAnemo,
		"Dendro":  engine.DiceColorDendro,
		"Omni":    engine.DiceColorOmni,
	})
	// CostSlot identifies a slot in COST space (distinct from DiceColor
	// which is pool space). 0..6 map to fire..dendro (same indices as
	// DiceColor), 7 = Match (same-color), 8 = Any, 9 = All (sentinel for
	// add_cost that spreads the delta across all 9 real slots).
	setEnum("CostSlot", map[string]int{
		"Fire":    int(engine.CostFire),
		"Ice":     int(engine.CostIce),
		"Water":   int(engine.CostWater),
		"Electro": int(engine.CostElectro),
		"Geo":     int(engine.CostGeo),
		"Anemo":   int(engine.CostAnemo),
		"Dendro":  int(engine.CostDendro),
		"Match":   int(engine.CostMatch),
		"Any":     int(engine.CostAny),
		"All":     int(engine.CostAll),
	})
	setEnum("Target", map[string]int{
		"EnemyActive": 1, "EnemyAll": 2, "OwnAll": 3,
		"EnemyNonActive": 4, "OwnActive": 5, "CardTarget": 6,
	})
	// ADR-0019 §A.2: find_char_by_kind 的 CharKind 枚举(closure spike 证伪后 enum-based)
	setEnum("CharKind", map[string]int{
		"LowestHp":        CharKindLowestHp,        // 0 — 治疗 / 召唤物随机最低
		"HighestHp":       CharKindHighestHp,       // 1
		"LeastDamaged":    CharKindLeastDamaged,    // 2 — 万众瞩目"受伤最少的我方角色"
		"RandomNonActive": CharKindRandomNonActive, // 3 — 部分召唤物"敌方场上随机一名"
		"PreviousActive":  CharKindPreviousActive,  // 4 — 追踪爆弹(future, fallback 到 active)
	})
	// ADR-0019 §A.3 Phase 1: Arkhe(始基力)typed namespace。跟 Element 同质 —
	// engine 知集合命名,不知反应规则;具体湮灭行为 100% DSL 决定。枫丹版本
	// 引入 4 张机关 + N 角色含始基,buff-owned 反应路径见 data/system/arche.lua。
	setEnum("Arkhe", map[string]int{
		"None":   0,
		"Pneuma": 1, // 芒性
		"Ousia":  2, // 荒性
	})
	setEnum("Source", map[string]int{
		"Skill": int(engine.SrcSkill), "Card": int(engine.SrcCard),
		"Status": int(engine.SrcStatus), "Summon": int(engine.SrcSummon),
		"Support": int(engine.SrcSupport), "Reaction": int(engine.SrcReaction),
	})
	setEnum("ActionKind", map[string]int{
		"Skill": int(engine.ActionSkill), "Card": int(engine.ActionCard),
		"Switch": int(engine.ActionSwitch), "EndTurn": int(engine.ActionEndTurn),
	})
	setEnum("Zone", map[string]int{
		"Hand": 0, "Deck": 1,
	})
	setEnum("Weapon", map[string]int{
		"None": 0, "Sword": 1, "Polearm": 2, "Bow": 3,
		"Claymore": 4, "Catalyst": 5,
	})
	setEnum("Slot", map[string]int{
		"None": 0, "Equip": 1, "Support": 2, "Specialty": 3,
	})
	setEnum("Action", map[string]int{
		"Switch": int(engine.ActSwitch),
	})
	// RefKind tags declared counters so DSL get/set auto-wraps the
	// stored int into the corresponding typed Value (nil for empty).
	setEnum("RefKind", map[string]int{
		"None":  RefKindNone,
		"Skill": RefKindSkill,
		"Card":  RefKindCard,
	})
}
