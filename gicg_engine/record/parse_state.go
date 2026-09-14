package record

import (
	"encoding/json"
	"fmt"
	"gicg_mono/gicg_engine/internal/strictjson"
	"strconv"
	"strings"
)

// parseState parses a state: block.
func (p *parser) parseState(minIndent int) (*State, error) {
	state := &State{}
	seen := map[string]bool{}
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
		key := strings.SplitN(trimmed, ":", 2)[0]
		if seen[key] {
			return nil, fmt.Errorf("duplicate state field %q", key)
		}
		seen[key] = true
		if strings.HasPrefix(trimmed, "checkpoint:") {
			if state.Checkpoint != nil {
				return nil, fmt.Errorf("duplicate checkpoint")
			}
			data := strings.TrimSpace(strings.TrimPrefix(trimmed, "checkpoint:"))
			if !json.Valid([]byte(data)) || !strings.HasPrefix(data, "{") {
				return nil, fmt.Errorf("invalid checkpoint JSON")
			}
			state.Checkpoint = json.RawMessage(data)
			p.pos++
			continue
		}
		if strings.HasPrefix(trimmed, "active_chars:") {
			var slots [2]int
			if err := strictjson.Decode([]byte(strings.TrimSpace(strings.TrimPrefix(trimmed, "active_chars:"))), &slots); err != nil {
				return nil, err
			}
			state.ActiveChars = &slots
			p.pos++
			continue
		}
		if m := playerHeaderRe.FindStringSubmatch(trimmed); m != nil {
			p.pos++
			ps, err := p.parsePlayerState(ind + 2)
			if err != nil {
				return state, err
			}
			if m[1] == "0" {
				state.P0 = ps
			} else {
				state.P1 = ps
			}
			continue
		}
		if m := firstPlayerRe.FindStringSubmatch(trimmed); m != nil {
			state.FirstPlayer, _ = strconv.Atoi(m[1])
			p.pos++
			continue
		}
		return nil, fmt.Errorf("line %d: unknown state field %q", p.pos+1, trimmed)
	}
	return state, nil
}

func (p *parser) parsePlayerState(minIndent int) (PlayerState, error) {
	ps := PlayerState{Counters: make(map[string]int)}
	seen := map[string]bool{}
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
		m := keyValueRe.FindStringSubmatch(trimmed)
		if m == nil {
			return ps, fmt.Errorf("line %d: malformed player field", p.pos+1)
		}
		key, val := m[1], m[2]
		if seen[key] {
			return ps, fmt.Errorf("duplicate player field %q", key)
		}
		seen[key] = true
		switch key {
		case "手牌":
			var err error
			ps.Hand, err = parseCardList(val)
			if err != nil {
				return ps, err
			}
			p.pos++
		case "牌组":
			var err error
			ps.Deck, err = parseCardList(val)
			if err != nil {
				return ps, err
			}
			p.pos++
		case "角色":
			p.pos++
			chars, err := p.parseCharFullStates(ind + 2)
			if err != nil {
				return ps, err
			}
			ps.Chars = chars
		default:
			// Any other key is a player-scope counter (AP, 存活数, …).
			// Value is an int literal.
			iv, err := strconv.Atoi(strings.TrimSpace(val))
			if err != nil {
				return ps, fmt.Errorf("invalid player counter %q: %w", key, err)
			}
			ps.Counters[key] = iv
			p.pos++
		}
	}
	return ps, nil
}

func (p *parser) parseCharFullStates(minIndent int) ([]CharFullState, error) {
	var chars []CharFullState
	seen := map[string]bool{}
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
		m := keyValueRe.FindStringSubmatch(trimmed)
		if m == nil {
			return nil, fmt.Errorf("line %d: malformed character", p.pos+1)
		}
		name, val := m[1], m[2]
		if seen[name] {
			return nil, fmt.Errorf("duplicate character %q", name)
		}
		seen[name] = true
		fields, err := parseInlineMap(val)
		if err != nil {
			return nil, err
		}
		cs := CharFullState{Name: name, Counters: make(map[string]int)}
		for k, v := range fields {
			if k == "状态" {
				// Nested status dict: merge into Counters
				status, err := parseInlineMap(v)
				if err != nil {
					return nil, err
				}
				for sk, sv := range status {
					if _, ok := fields[sk]; ok {
						return nil, fmt.Errorf("duplicate status/counter %q", sk)
					}
					iv, err := strconv.Atoi(sv)
					if err != nil {
						return nil, fmt.Errorf("invalid status %q: %w", sk, err)
					}
					cs.Counters[sk] = iv
				}
				continue
			}
			// Normalize value: "true"/"false" → 1/0, else int literal
			switch v {
			case "true":
				cs.Counters[k] = 1
			case "false":
				cs.Counters[k] = 0
			default:
				iv, err := strconv.Atoi(v)
				if err != nil {
					return nil, fmt.Errorf("invalid counter %q: %w", k, err)
				}
				cs.Counters[k] = iv
			}
		}
		chars = append(chars, cs)
		p.pos++
	}
	return chars, nil
}
