package record

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/internal/strictjson"
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
	trimmed := strings.TrimSpace(s)
	return trimmed == "" || strings.HasPrefix(trimmed, "#")
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

		if strings.HasPrefix(trimmed, "config:") {
			if rec.Config != nil {
				return nil, fmt.Errorf("duplicate replay config")
			}
			var err error
			rec.Config, err = parseConfig(strings.TrimSpace(strings.TrimPrefix(trimmed, "config:")))
			if err != nil {
				return nil, err
			}
			p.pos++
			continue
		}
		if m := roundHeaderRe.FindStringSubmatch(trimmed); m != nil {
			num, err := strconv.Atoi(m[1])
			if err != nil || num != len(rec.Rounds)+1 {
				return nil, fmt.Errorf("line %d: round numbers must start at 1 and be consecutive", p.pos+1)
			}
			p.pos++
			round, err := p.parseRound(num, 2)
			if err != nil {
				return nil, err
			}
			rec.Rounds = append(rec.Rounds, round)
			continue
		}

		if m := winnerLineRe.FindStringSubmatch(trimmed); m != nil {
			if rec.Winner != -1 {
				return nil, fmt.Errorf("duplicate winner")
			}
			if m[2] == "平局" {
				rec.Winner = 2
			} else {
				rec.Winner, _ = strconv.Atoi(m[1])
			}
			p.pos++
			continue
		}

		return nil, fmt.Errorf("line %d: unknown record entry %q", p.pos+1, trimmed)
	}
	return rec, nil
}

var (
	roundHeaderRe  = regexp.MustCompile(`^round\s+(\d+):$`)
	winnerLineRe   = regexp.MustCompile(`^胜者:\s*(?:P([01])|(平局))$`)
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
	actionTuneRe   = regexp.MustCompile(`^-\s*P([01])\s+调和卡牌\s+([^:\s]+):?\s*$`)
	actionRerollRe = regexp.MustCompile(`^-\s*P([01])\s+选择重投:?\s*$`)
)

func (p *parser) parseRound(num int, minIndent int) (Round, error) {
	round := Round{Number: num}
	seenActions := false
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
			if round.Start != nil {
				return round, fmt.Errorf("duplicate round state")
			}
			p.pos++
			state, err := p.parseState(ind + 2)
			if err != nil {
				return round, err
			}
			round.Start = state
			continue
		}
		if trimmed == "actions:" {
			if seenActions {
				return round, fmt.Errorf("duplicate round actions")
			}
			seenActions = true
			p.pos++
			actions, err := p.parseActions(ind + 2)
			if err != nil {
				return round, err
			}
			round.Actions = actions
			continue
		}
		// 回合开始:, 回合结束: — skip these (driven by engine hooks)
		if trimmed == "回合开始:" || trimmed == "回合结束:" {
			p.pos++
			p.skipBlock(ind + 2)
			continue
		}
		return round, fmt.Errorf("line %d: unknown round entry %q", p.pos+1, trimmed)
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
			if strings.HasPrefix(strings.TrimSpace(line), "input:") {
				if len(actions) == 0 {
					return nil, fmt.Errorf("input without action")
				}
				a := &actions[len(actions)-1]
				if a.Input != nil {
					return nil, fmt.Errorf("duplicate action input")
				}
				var input engine.ActionInput
				if err := strictjson.Decode([]byte(strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(line), "input:"))), &input); err != nil {
					return nil, fmt.Errorf("action input: %w", err)
				}
				a.Input = &input
				if err := a.validateInput(); err != nil {
					return nil, fmt.Errorf("line %d: %w", p.pos+1, err)
				}
				p.pos++
				continue
			}
			// indented effect line for previous action
			if len(actions) > 0 {
				actions[len(actions)-1].Effects = append(actions[len(actions)-1].Effects, trimIndent(line))
			}
			p.pos++
			continue
		}
		trimmed := trimIndent(line)
		if act, ok := parseActionLine(trimmed); ok {
			if act.Player < 0 || act.Player > 1 {
				return nil, fmt.Errorf("line %d: invalid player %d", p.pos+1, act.Player)
			}
			actions = append(actions, act)
			p.pos++
			continue
		}
		return nil, fmt.Errorf("line %d: unknown action %q", p.pos+1, trimmed)
	}
	return actions, nil
}

func parseActionLine(line string) (Action, bool) {
	if m := actionRerollRe.FindStringSubmatch(line); m != nil {
		p, _ := strconv.Atoi(m[1])
		return Action{Player: p, Kind: ActReroll, TargetPlayer: -1}, true
	}
	if m := actionTuneRe.FindStringSubmatch(line); m != nil {
		p, _ := strconv.Atoi(m[1])
		return Action{Player: p, Kind: ActTune, Name: m[2], TargetPlayer: -1}, true
	}
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
