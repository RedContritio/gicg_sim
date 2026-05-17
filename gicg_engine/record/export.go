package record

import (
	"fmt"
	"strings"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// Export generates a textual game record from a Runtime's Game + EventLog.
// Takes *interp.Runtime so we can identify counters by role (via CharEntry
// refs and well-known names) instead of hardcoded Chinese display strings.
func Export(rt *interp.Runtime) string {
	g := rt.Game
	if g.Log == nil || len(g.Log.RoundStartSnaps) == 0 {
		return "# empty record (no log)\n"
	}
	roleMap := buildRoleMap(rt)
	var b strings.Builder
	writeRounds(&b, g, roleMap)
	return b.String()
}

// writeRounds iterates through the log entries and emits rounds.
func writeRounds(b *strings.Builder, g *engine.Game, roleMap RoleMap) {
	entries := g.Log.Entries
	startSnaps := g.Log.RoundStartSnaps

	roundIdx := -1
	var curActions []*actionBuilder
	var curStartEffects []string
	var curEndEffects []string
	phase := "start" // start, actions, roundend
	var curAction *actionBuilder

	flushRound := func() {
		if roundIdx < 0 {
			return
		}
		fmt.Fprintf(b, "round %d:\n", roundIdx)
		if roundIdx-1 < len(startSnaps) {
			writeState(b, g, roleMap, startSnaps[roundIdx-1])
		}
		if len(curStartEffects) > 0 {
			b.WriteString("  回合开始:\n")
			for _, e := range curStartEffects {
				fmt.Fprintf(b, "    - %s\n", e)
			}
		}
		if len(curActions) > 0 {
			b.WriteString("  actions:\n")
			for _, a := range curActions {
				fmt.Fprintf(b, "    - %s:\n", a.Header)
				for _, e := range a.Effects {
					fmt.Fprintf(b, "        - %s\n", e)
				}
			}
		}
		if len(curEndEffects) > 0 {
			b.WriteString("  回合结束:\n")
			for _, e := range curEndEffects {
				fmt.Fprintf(b, "    - %s\n", e)
			}
		}
		b.WriteString("\n")
	}

	for _, e := range entries {
		switch e.Type {
		case "round_start":
			flushRound()
			roundIdx = e.Round
			curActions = nil
			curStartEffects = nil
			curEndEffects = nil
			curAction = nil
			phase = "start"

		case "round_end":
			phase = "roundend"
			curAction = nil

		case "action_skill", "action_card", "action_switch", "action_end_turn":
			phase = "actions"
			curAction = &actionBuilder{}
			curAction.Header = formatActionHeader(g, e)
			curActions = append(curActions, curAction)

		case "counter_write":
			line := formatCounterWrite(g, roleMap, e)
			if line == "" {
				break
			}
			switch phase {
			case "start":
				curStartEffects = append(curStartEffects, line)
			case "roundend":
				curEndEffects = append(curEndEffects, line)
			default:
				if curAction != nil {
					curAction.Effects = append(curAction.Effects, line)
				} else {
					curStartEffects = append(curStartEffects, line)
				}
			}

		case "damage":
			line := formatDamage(g, e)
			if curAction != nil {
				curAction.Effects = append(curAction.Effects, line)
			} else if phase == "roundend" {
				curEndEffects = append(curEndEffects, line)
			}

		case "heal":
			line := formatHeal(g, e)
			if curAction != nil {
				curAction.Effects = append(curAction.Effects, line)
			} else if phase == "roundend" {
				curEndEffects = append(curEndEffects, line)
			}

		case "death":
			line := fmt.Sprintf("%s 死亡", charName(g, e.Player, e.Char))
			if curAction != nil {
				curAction.Effects = append(curAction.Effects, line)
			} else if phase == "roundend" {
				curEndEffects = append(curEndEffects, line)
			}

		case "hand_add":
			ref := e.Fields["card_ref"].(int)
			cardNm := g.CardNames[ref]
			if cardNm == "" {
				cardNm = fmt.Sprintf("card_%d", ref)
			}
			from, _ := e.Fields["from"].(string)
			var line string
			if from == "deck" {
				line = fmt.Sprintf("P%d 摸到手牌 %s", e.Player, cardNm)
			} else {
				line = fmt.Sprintf("P%d 获得手牌 %s", e.Player, cardNm)
			}
			if curAction != nil {
				curAction.Effects = append(curAction.Effects, line)
			} else if phase == "start" {
				curStartEffects = append(curStartEffects, line)
			} else if phase == "roundend" {
				curEndEffects = append(curEndEffects, line)
			}

		case "hand_remove":
			ref := e.Fields["card_ref"].(int)
			cardNm := g.CardNames[ref]
			if cardNm == "" {
				cardNm = fmt.Sprintf("card_%d", ref)
			}
			line := fmt.Sprintf("P%d 失去手牌 %s", e.Player, cardNm)
			if curAction != nil {
				curAction.Effects = append(curAction.Effects, line)
			} else if phase == "roundend" {
				curEndEffects = append(curEndEffects, line)
			}

		case "winner":
			w := e.Fields["winner"].(int)
			line := fmt.Sprintf("胜者: P%d", w)
			if curAction != nil {
				curAction.Effects = append(curAction.Effects, line)
			}
		}
	}
	flushRound()
	if g.Winner >= 0 && g.Winner < 2 {
		fmt.Fprintf(b, "胜者: P%d\n", g.Winner)
	} else if g.Winner == 2 {
		b.WriteString("胜者: 平局\n")
	}
}

// formatActionHeader / formatCounterWrite / formatDamage / formatHeal /
// isHidden / elementNames / actionBuilder live in export_format.go.
// writeState / writeCharState / formatFieldValue / rolePriority /
// charName / cardListStr live in export_state.go.
