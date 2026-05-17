package record

import (
	"strconv"
	"strings"
)

// parseState parses a state: block.
func (p *parser) parseState(minIndent int) (*State, error) {
	state := &State{}
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
		p.pos++
	}
	return state, nil
}

func (p *parser) parsePlayerState(minIndent int) (PlayerState, error) {
	ps := PlayerState{Counters: make(map[string]int)}
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
			p.pos++
			continue
		}
		key, val := m[1], m[2]
		switch key {
		case "手牌":
			ps.Hand = parseCardList(val)
			p.pos++
		case "牌组":
			ps.Deck = parseCardList(val)
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
			if iv, err := strconv.Atoi(strings.TrimSpace(val)); err == nil {
				ps.Counters[key] = iv
			}
			p.pos++
		}
	}
	return ps, nil
}

func (p *parser) parseCharFullStates(minIndent int) ([]CharFullState, error) {
	var chars []CharFullState
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
			p.pos++
			continue
		}
		name, val := m[1], m[2]
		fields := parseInlineMap(val)
		cs := CharFullState{Name: name, Counters: make(map[string]int)}
		for k, v := range fields {
			if k == "状态" {
				// Nested status dict: merge into Counters
				status := parseInlineMap(v)
				for sk, sv := range status {
					if iv, err := strconv.Atoi(sv); err == nil {
						cs.Counters[sk] = iv
					}
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
				if iv, err := strconv.Atoi(v); err == nil {
					cs.Counters[k] = iv
				}
			}
		}
		chars = append(chars, cs)
		p.pos++
	}
	return chars, nil
}

// parseInlineMap parses "{ k: v, k: v }" into a map.
// Values are returned as raw strings.
func parseInlineMap(s string) map[string]string {
	result := make(map[string]string)
	s = strings.TrimSpace(s)
	s = strings.TrimPrefix(s, "{")
	s = strings.TrimSuffix(s, "}")
	s = strings.TrimSpace(s)
	if s == "" {
		return result
	}
	// Split by comma, but respect nested { } for 状态 fields
	parts := splitTopLevel(s, ',')
	for _, part := range parts {
		part = strings.TrimSpace(part)
		kv := strings.SplitN(part, ":", 2)
		if len(kv) != 2 {
			continue
		}
		k := strings.TrimSpace(kv[0])
		v := strings.TrimSpace(kv[1])
		result[k] = v
	}
	return result
}

// splitTopLevel splits s by sep, ignoring sep inside {} or [].
func splitTopLevel(s string, sep rune) []string {
	var out []string
	depth := 0
	start := 0
	for i, c := range s {
		switch c {
		case '{', '[':
			depth++
		case '}', ']':
			depth--
		case sep:
			if depth == 0 {
				out = append(out, s[start:i])
				start = i + 1
			}
		}
	}
	out = append(out, s[start:])
	return out
}

// parseCardList parses "[a, b, c]" or "[]".
func parseCardList(s string) []string {
	s = strings.TrimSpace(s)
	s = strings.TrimPrefix(s, "[")
	s = strings.TrimSuffix(s, "]")
	s = strings.TrimSpace(s)
	if s == "" {
		return nil
	}
	var out []string
	for _, p := range strings.Split(s, ",") {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}
