package engine

import "fmt"

// LogEntry is a single event in the game log.
type LogEntry struct {
	Step   int
	Round  int
	Turn   int
	Type   string
	Player int
	Char   int
	Fields map[string]interface{}
}

// StateSnapshot is a human-readable diagnostic projection. Checkpoint, when
// present, additionally preserves the complete gameplay state at a round pause.
//
// ⚠ Ref scope contract: Hands / Decks store bare `[]int` card refs.
// These refs are PROCESS-SCOPED (assigned during DSL load by the
// interp layer). Snapshots are safe to consume within the SAME Game
// (and its clones via DeepCopy) that produced them — all consumers
// (record.writeState, VerifyAgainstSnap, etc.) look up refs via
// g.CardNames on the same Game pointer.
//
// Cross-process / cross-scenario consumption is OUT OF SCOPE: if a
// snapshot's Hands[0] contains ref=7 and the consuming process loaded
// a different card order where ref=7 names a different card, the
// output degrades gracefully (cardListStr prints `?7` for unresolved
// refs via g.CardNames lookup miss — no panic or buffer OOB). But
// the semantic replay won't match. Serialize-to-string (via
// record.Export) before cross-process transfer when round-trip matters.
type StateSnapshot struct {
	Checkpoint  []byte // exact portable gameplay checkpoint, when captured at round pause
	Round       int
	Turn        int
	FirstPlayer int // who will go first in the upcoming round (resolved from FirstEnd at round pause)
	Phase       Phase
	Counters    []int     // snapshot of all counter values
	Hands       [2][]int  // card refs in hand (process-scoped; see above)
	Decks       [2][]int  // card refs in deck (process-scoped; see above)
	ActiveChars [2]int    // active char index per player
	Alive       [2][]bool // alive status per player per char
}

// EventLog collects game events. Set to nil to disable logging.
type EventLog struct {
	Entries         []LogEntry
	step            int
	RoundStartSnaps []*StateSnapshot // captured at the start of each round (before round_start hooks)
}

func NewEventLog() *EventLog {
	return &EventLog{}
}

func (el *EventLog) Append(g *Game, typ string, player, char int, fields map[string]interface{}) {
	el.Entries = append(el.Entries, LogEntry{
		Step:   el.step,
		Round:  g.Round,
		Turn:   g.Turn,
		Type:   typ,
		Player: player,
		Char:   char,
		Fields: fields,
	})
}

func (el *EventLog) NextStep() {
	el.step++
}

// Print outputs the log in human-readable format.
func (el *EventLog) Print(skillNames map[int]string, cardNames map[int]string, charNames map[[2]int]string) {
	charName := func(p, c int) string {
		if n, ok := charNames[[2]int{p, c}]; ok {
			return n
		}
		return fmt.Sprintf("P%dC%d", p, c)
	}

	for _, e := range el.Entries {
		prefix := fmt.Sprintf("[R%d S%03d P%d]", e.Round, e.Step, e.Turn)
		switch e.Type {
		case "action_skill":
			skillName := "?"
			if sid, ok := e.Fields["skill_id"]; ok {
				if n, ok2 := skillNames[sid.(int)]; ok2 {
					skillName = n
				}
			}
			fmt.Printf("%s %s uses %s\n", prefix, charName(e.Player, e.Char), skillName)

		case "action_card":
			cardName := "?"
			if ref, ok := e.Fields["card_ref"]; ok {
				if n, ok2 := cardNames[ref.(int)]; ok2 {
					cardName = n
				}
			}
			fmt.Printf("%s %s plays %s\n", prefix, charName(e.Player, e.Char), cardName)

		case "action_switch":
			targetChar := e.Fields["target_char"].(int)
			fmt.Printf("%s %s switches to %s\n", prefix, charName(e.Player, e.Char), charName(e.Player, targetChar))

		case "action_end_turn":
			fmt.Printf("%s %s ends turn\n", prefix, charName(e.Player, e.Char))

		case "damage":
			src := charName(e.Fields["src_player"].(int), e.Fields["src_char"].(int))
			tgt := charName(e.Fields["tgt_player"].(int), e.Fields["tgt_char"].(int))
			raw := e.Fields["raw_value"].(int)
			final := e.Fields["final_value"].(int)
			absorbed := e.Fields["absorbed"].(int)
			elem := e.Fields["element"].(int)
			elemNames := []string{"None", "Fire", "Ice", "Water", "Electro", "Geo", "Physical"}
			elemName := "?"
			if elem >= 0 && elem < len(elemNames) {
				elemName = elemNames[elem]
			}
			if absorbed > 0 {
				fmt.Printf("%s   %s → %s: %d %s damage (-%d shield, %d dealt)\n", prefix, src, tgt, raw, elemName, absorbed, final)
			} else {
				fmt.Printf("%s   %s → %s: %d %s damage\n", prefix, src, tgt, final, elemName)
			}

		case "heal":
			tgt := charName(e.Fields["tgt_player"].(int), e.Fields["tgt_char"].(int))
			value := e.Fields["value"].(int)
			fmt.Printf("%s   %s healed %d\n", prefix, tgt, value)

		case "death":
			fmt.Printf("%s   ☠ %s died\n", prefix, charName(e.Player, e.Char))

		case "round_start":
			fmt.Printf("%s === Round %d Start ===\n", prefix, e.Round)

		case "round_end":
			fmt.Printf("%s === Round %d End ===\n", prefix, e.Round)

		case "winner":
			winner := e.Fields["winner"].(int)
			if winner >= 0 {
				fmt.Printf("%s ★ Player %d wins!\n", prefix, winner)
			} else {
				fmt.Printf("%s ★ Draw\n", prefix)
			}

		default:
			fmt.Printf("%s %s p%d c%d %v\n", prefix, e.Type, e.Player, e.Char, e.Fields)
		}
	}
}
