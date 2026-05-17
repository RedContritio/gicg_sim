package record

import (
	"regexp"
	"strconv"
	"strings"
)

// Parse parses a game record from text.
func Parse(src string) (*Record, error) {
	p := &parser{lines: strings.Split(src, "\n")}
	return p.parse()
}

type parser struct {
	lines []string
	pos   int
}

// peek returns the current line without advancing, or empty if at EOF.
func (p *parser) peek() string {
	if p.pos >= len(p.lines) {
		return ""
	}
	return p.lines[p.pos]
}

func (p *parser) advance() string {
	line := p.peek()
	p.pos++
	return line
}

// indent returns the leading whitespace count (spaces only).
func indent(s string) int {
	n := 0
	for _, c := range s {
		if c == ' ' {
			n++
		} else if c == '\t' {
			n += 4
		} else {
			break
		}
	}
	return n
}

// trim leading spaces/tabs.
func trimIndent(s string) string {
	return strings.TrimLeft(s, " \t")
}

// isBlank returns true for empty or whitespace-only lines.
func isBlank(s string) bool {
	return strings.TrimSpace(s) == ""
}

func (p *parser) parse() (*Record, error) {
	rec := &Record{Winner: -1}
	for p.pos < len(p.lines) {
		line := p.peek()
		trimmed := strings.TrimSpace(line)

		if isBlank(line) || strings.HasPrefix(trimmed, "#") {
			p.pos++
			continue
		}

		if m := roundHeaderRe.FindStringSubmatch(trimmed); m != nil {
			num, _ := strconv.Atoi(m[1])
			p.pos++
			round, err := p.parseRound(num, 2)
			if err != nil {
				return nil, err
			}
			rec.Rounds = append(rec.Rounds, round)
			continue
		}

		if m := winnerLineRe.FindStringSubmatch(trimmed); m != nil {
			if m[1] == "平局" {
				rec.Winner = 2
			} else {
				rec.Winner, _ = strconv.Atoi(m[1])
			}
			p.pos++
			continue
		}

		// Unknown line, skip
		p.pos++
	}
	return rec, nil
}

var (
	roundHeaderRe  = regexp.MustCompile(`^round\s+(\d+):$`)
	winnerLineRe   = regexp.MustCompile(`^胜者:\s*(?:P(\d)|(平局))$`)
	playerHeaderRe = regexp.MustCompile(`^P([01]):$`)
	firstPlayerRe  = regexp.MustCompile(`^先手:\s*P([01])$`)
	keyValueRe     = regexp.MustCompile(`^([^:]+):\s*(.*)$`)
	// Action headers: "- P0 出战角色 <char> 使用技能 <name>:"
	//                 "- P1 使用卡牌 <name>:" / "- P1 结束回合:" / "- P0 切换到 <char>:"
	// Name is captured greedily but excludes trailing colon.
	actionSkillRe  = regexp.MustCompile(`^-\s*P(\d)\s+出战角色\s+(\S+?)\s+使用技能\s+([^:\s]+):?\s*$`)
	actionCardRe   = regexp.MustCompile(`^-\s*P(\d)\s+出战角色\s+(\S+?)\s+使用卡牌\s+([^:→\s]+)(?:\s+→\s+P(\d)\s+(\S+?))?:?\s*$`)
	actionSwitchRe = regexp.MustCompile(`^-\s*P(\d)\s+切换到\s+([^:\s]+):?\s*$`)
	actionEndRe    = regexp.MustCompile(`^-\s*P(\d)\s+结束回合:?\s*$`)
)

func (p *parser) parseRound(num int, minIndent int) (Round, error) {
	round := Round{Number: num}
	for p.pos < len(p.lines) {
		line := p.peek()
		if isBlank(line) {
			p.pos++
			continue
		}
		ind := indent(line)
		if ind < minIndent {
			break
		}
		trimmed := trimIndent(line)
		if trimmed == "state:" {
			p.pos++
			state, err := p.parseState(ind + 2)
			if err != nil {
				return round, err
			}
			round.Start = state
			continue
		}
		if trimmed == "actions:" {
			p.pos++
			actions, err := p.parseActions(ind + 2)
			if err != nil {
				return round, err
			}
			round.Actions = actions
			continue
		}
		// 回合开始:, 回合结束: — skip these (driven by engine hooks)
		if strings.HasSuffix(trimmed, ":") {
			p.pos++
			p.skipBlock(ind + 2)
			continue
		}
		p.pos++
	}
	return round, nil
}

// skipBlock skips lines with indent >= minIndent.
func (p *parser) skipBlock(minIndent int) {
	for p.pos < len(p.lines) {
		line := p.peek()
		if isBlank(line) {
			p.pos++
			continue
		}
		if indent(line) < minIndent {
			return
		}
		p.pos++
	}
}

// parseActions parses the actions list. Each entry starts with "- Pn ...:" and
// may have indented effect lines below it.
func (p *parser) parseActions(minIndent int) ([]Action, error) {
	var actions []Action
	for p.pos < len(p.lines) {
		line := p.peek()
		if isBlank(line) {
			p.pos++
			continue
		}
		ind := indent(line)
		if ind < minIndent {
			break
		}
		if ind > minIndent {
			// indented effect line for previous action
			if len(actions) > 0 {
				actions[len(actions)-1].Effects = append(actions[len(actions)-1].Effects, trimIndent(line))
			}
			p.pos++
			continue
		}
		trimmed := trimIndent(line)
		if act, ok := parseActionLine(trimmed); ok {
			actions = append(actions, act)
			p.pos++
			continue
		}
		// Unknown line at this level; skip
		p.pos++
	}
	return actions, nil
}

func parseActionLine(line string) (Action, bool) {
	if m := actionSkillRe.FindStringSubmatch(line); m != nil {
		p, _ := strconv.Atoi(m[1])
		return Action{Player: p, Kind: ActSkill, Name: m[3], TargetPlayer: -1}, true
	}
	if m := actionCardRe.FindStringSubmatch(line); m != nil {
		p, _ := strconv.Atoi(m[1])
		act := Action{Player: p, Kind: ActCard, Name: m[3], TargetPlayer: -1}
		if m[4] != "" {
			act.TargetPlayer, _ = strconv.Atoi(m[4])
			act.TargetChar = m[5]
		}
		return act, true
	}
	if m := actionSwitchRe.FindStringSubmatch(line); m != nil {
		p, _ := strconv.Atoi(m[1])
		return Action{Player: p, Kind: ActSwitch, Name: m[2], TargetPlayer: -1}, true
	}
	if m := actionEndRe.FindStringSubmatch(line); m != nil {
		p, _ := strconv.Atoi(m[1])
		return Action{Player: p, Kind: ActEndTurn, TargetPlayer: -1}, true
	}
	return Action{}, false
}

// parseState / parsePlayerState / parseCharFullStates + inline-map helpers
// live in parse_state.go.
