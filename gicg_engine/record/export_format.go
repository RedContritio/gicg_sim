package record

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
)

var elementNames = map[int]string{
	int(engine.ElemNone):     "无",
	int(engine.ElemFire):     "火",
	int(engine.ElemIce):      "冰",
	int(engine.ElemWater):    "水",
	int(engine.ElemElectro):  "雷",
	int(engine.ElemGeo):      "岩",
	int(engine.ElemPhysical): "物理",
}

type actionBuilder struct {
	Input   *engine.ActionInput
	Header  string
	Effects []string
}

// isHidden reports whether a counter should be omitted from the per-line log
// because its information is already shown by dedicated events (damage/death)
// or is internal bookkeeping.
func isHidden(role Role) bool {
	switch role {
	case RoleHP, RoleAlive, RoleActive, RoleAliveCount, RoleRoundNum, RoleFirstPlayer:
		return true
	}
	return false
}

func formatActionHeader(g *engine.Game, e engine.LogEntry) string {
	switch e.Type {
	case "action_tune":
		return fmt.Sprintf("P%d 调和卡牌 %s", e.Player, g.CardNames[e.Fields["card_ref"].(int)])
	case "action_reroll":
		return fmt.Sprintf("P%d 选择重投", e.Player)
	case "action_skill":
		sid := e.Fields["skill_id"].(int)
		skill := g.SkillNames[sid]
		return fmt.Sprintf("P%d 出战角色 %s 使用技能 %s", e.Player, charName(g, e.Player, e.Char), skill)
	case "action_card":
		ref := e.Fields["card_ref"].(int)
		card := g.CardNames[ref]
		header := fmt.Sprintf("P%d 出战角色 %s 使用卡牌 %s", e.Player, charName(g, e.Player, e.Char), card)
		if tp, ok := e.Fields["target_player"].(int); ok {
			if tc, ok2 := e.Fields["target_char"].(int); ok2 {
				header += fmt.Sprintf(" → P%d %s", tp, charName(g, tp, tc))
			}
		}
		return header
	case "action_switch":
		target := e.Fields["target_char"].(int)
		return fmt.Sprintf("P%d 切换到 %s", e.Player, charName(g, e.Player, target))
	case "action_end_turn":
		return fmt.Sprintf("P%d 结束回合", e.Player)
	}
	return "?"
}

func formatCounterWrite(g *engine.Game, roleMap RoleMap, e engine.LogEntry) string {
	id := e.Fields["counter_id"].(int)
	op := e.Fields["op"].(int)
	before := e.Fields["before"].(int)
	after := e.Fields["after"].(int)
	role := roleMap[id]
	if isHidden(role) {
		return ""
	}
	name := g.CounterNames[id]
	if name == "" {
		return ""
	}

	// Determine subject: P0/P1 + char name (if per-char) or just player
	mapping := g.GetCounterChar(id)
	p, c := mapping[0], mapping[1]
	var subject string
	if p >= 0 && c >= 0 {
		subject = fmt.Sprintf("P%d %s", p, charName(g, p, c))
	} else if p >= 0 {
		subject = fmt.Sprintf("P%d", p)
	} else {
		subject = "全局"
	}

	delta := after - before
	switch engine.Op(op) {
	case engine.OpSet:
		return fmt.Sprintf("%s %s 设为 %d", subject, name, after)
	case engine.OpAdd:
		verb := "增加"
		if role == RoleEnergy {
			verb = "获得"
		}
		return fmt.Sprintf("%s %s %s %d，当前 %d", subject, name, verb, delta, after)
	case engine.OpSub:
		verb := "减少"
		if role == RoleEnergy {
			verb = "消耗"
		}
		return fmt.Sprintf("%s %s %s %d，当前 %d", subject, name, verb, -delta, after)
	}
	return ""
}

func formatDamage(g *engine.Game, e engine.LogEntry) string {
	srcP := e.Fields["src_player"].(int)
	srcC := e.Fields["src_char"].(int)
	tgtP := e.Fields["tgt_player"].(int)
	tgtC := e.Fields["tgt_char"].(int)
	elem := e.Fields["element"].(int)
	final := e.Fields["final_value"].(int)
	absorbed := e.Fields["absorbed"].(int)
	penetrate, _ := e.Fields["penetrate"].(bool)
	elemName := elementNames[elem]
	if penetrate {
		elemName = "穿透"
	}
	src := charName(g, srcP, srcC)
	tgt := charName(g, tgtP, tgtC)
	if absorbed > 0 {
		return fmt.Sprintf("P%d %s 对 P%d %s 造成 %d %s伤害（护盾吸收 %d）",
			srcP, src, tgtP, tgt, final, elemName, absorbed)
	}
	return fmt.Sprintf("P%d %s 对 P%d %s 造成 %d %s伤害",
		srcP, src, tgtP, tgt, final, elemName)
}

func formatHeal(g *engine.Game, e engine.LogEntry) string {
	tgtP := e.Fields["tgt_player"].(int)
	tgtC := e.Fields["tgt_char"].(int)
	value := e.Fields["value"].(int)
	return fmt.Sprintf("P%d %s 治疗 %d 点", tgtP, charName(g, tgtP, tgtC), value)
}
