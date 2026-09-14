package record

import (
	"fmt"
	"strings"
)

func parseInlineMap(s string) (map[string]string, error) {
	parts, err := literalParts(s, '{', '}')
	if err != nil {
		return nil, err
	}
	result := map[string]string{}
	for _, part := range parts {
		kv := strings.SplitN(part, ":", 2)
		if len(kv) != 2 {
			return nil, fmt.Errorf("invalid map entry %q", part)
		}
		key, value := strings.TrimSpace(kv[0]), strings.TrimSpace(kv[1])
		if key == "" || value == "" {
			return nil, fmt.Errorf("empty map key/value")
		}
		if _, ok := result[key]; ok {
			return nil, fmt.Errorf("duplicate map key %q", key)
		}
		result[key] = value
	}
	return result, nil
}

func parseCardList(s string) ([]string, error) { return literalParts(s, '[', ']') }

// The legacy record grammar uses unquoted names, with nested status maps.
// Reject malformed delimiters instead of silently extracting a partial state.
func literalParts(s string, open, close byte) ([]string, error) {
	s = strings.TrimSpace(s)
	if len(s) < 2 || s[0] != open || s[len(s)-1] != close {
		return nil, fmt.Errorf("malformed literal %q", s)
	}
	s = strings.TrimSpace(s[1 : len(s)-1])
	if s == "" {
		return nil, nil
	}
	var parts []string
	var stack []rune
	start := 0
	for i, c := range s {
		switch c {
		case '{', '[':
			stack = append(stack, c)
		case '}', ']':
			if len(stack) == 0 || (c == '}' && stack[len(stack)-1] != '{') || (c == ']' && stack[len(stack)-1] != '[') {
				return nil, fmt.Errorf("unbalanced literal %q", s)
			}
			stack = stack[:len(stack)-1]
		case ',':
			if len(stack) == 0 {
				parts = append(parts, strings.TrimSpace(s[start:i]))
				start = i + 1
			}
		}
	}
	if len(stack) != 0 {
		return nil, fmt.Errorf("unbalanced literal %q", s)
	}
	parts = append(parts, strings.TrimSpace(s[start:]))
	for _, part := range parts {
		if part == "" {
			return nil, fmt.Errorf("empty literal entry")
		}
	}
	return parts, nil
}
