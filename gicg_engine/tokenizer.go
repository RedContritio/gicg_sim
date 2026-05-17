package engine

import (
	"regexp"
	"strconv"
	"strings"
)

// Token vocabulary IDs

// Token type constants (~200 values) live in tokenizer_tokens.go.

type TokenPair struct {
	Type  int16
	Value int16
}

// Keyword / enum / ctx-field / method maps live in tokenizer_maps.go.

var luaTokenRe = regexp.MustCompile(
	`--[^\n]*` + // comment
		`|~=|==|<=|>=|` + // two-char operators
		`[+\-*/<>=~(){}:.,]` + // single-char operators
		`|\b\d+\b` + // numbers
		`|"[^"]*"` + // strings
		`|\b[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)?` + // identifiers (including X.Y)
		`|:[a-zA-Z_]\w*`, // method calls
)

// TokenizeLua converts Lua source into a token pair sequence.
func TokenizeLua(src string) []TokenPair {
	var tokens []TokenPair

	matches := luaTokenRe.FindAllString(src, -1)
	for _, m := range matches {
		// Skip comments
		if strings.HasPrefix(m, "--") {
			continue
		}

		// Operators
		switch m {
		case "==":
			tokens = append(tokens, TokenPair{int16(TokEq), 0})
			continue
		case "~=":
			tokens = append(tokens, TokenPair{int16(TokNeq), 0})
			continue
		case "<=":
			tokens = append(tokens, TokenPair{int16(TokLe), 0})
			continue
		case ">=":
			tokens = append(tokens, TokenPair{int16(TokGe), 0})
			continue
		case "<":
			tokens = append(tokens, TokenPair{int16(TokLt), 0})
			continue
		case ">":
			tokens = append(tokens, TokenPair{int16(TokGt), 0})
			continue
		case "+":
			tokens = append(tokens, TokenPair{int16(TokAdd), 0})
			continue
		case "-":
			tokens = append(tokens, TokenPair{int16(TokSub), 0})
			continue
		case "*":
			tokens = append(tokens, TokenPair{int16(TokMul), 0})
			continue
		case "/":
			tokens = append(tokens, TokenPair{int16(TokDiv), 0})
			continue
		case "=":
			tokens = append(tokens, TokenPair{int16(TokAssign), 0})
			continue
		case ".":
			tokens = append(tokens, TokenPair{int16(TokDot), 0})
			continue
		case ",":
			tokens = append(tokens, TokenPair{int16(TokComma), 0})
			continue
		case "(":
			tokens = append(tokens, TokenPair{int16(TokLParen), 0})
			continue
		case ")":
			tokens = append(tokens, TokenPair{int16(TokRParen), 0})
			continue
		case "{":
			tokens = append(tokens, TokenPair{int16(TokLBrace), 0})
			continue
		case "}":
			tokens = append(tokens, TokenPair{int16(TokRBrace), 0})
			continue
		}

		// Method calls (:name)
		if strings.HasPrefix(m, ":") {
			name := m[1:]
			if id, ok := methodMap[name]; ok {
				tokens = append(tokens, TokenPair{int16(id), 0})
			}
			continue
		}

		// Numbers
		if n, err := strconv.Atoi(m); err == nil {
			tokens = append(tokens, TokenPair{int16(TokLitNumber), int16(n)})
			continue
		}

		// Strings
		if strings.HasPrefix(m, "\"") {
			// Hash the string content to a value
			inner := m[1 : len(m)-1]
			h := int16(0)
			for _, c := range inner {
				h = h*31 + int16(c)
			}
			tokens = append(tokens, TokenPair{int16(TokLitString), h})
			continue
		}

		// Enum values (X.Y)
		if id, ok := enumMap[m]; ok {
			tokens = append(tokens, TokenPair{int16(id), 0})
			continue
		}

		// ctx fields
		if id, ok := ctxFieldMap[m]; ok {
			tokens = append(tokens, TokenPair{int16(id), 0})
			continue
		}

		// Keywords and API calls
		if id, ok := tokenMap[m]; ok {
			tokens = append(tokens, TokenPair{int16(id), 0})
			continue
		}

		// Local variable reference
		if m == "ctx" {
			continue // skip bare ctx (handled by ctx.field)
		}

		// Unknown identifier = variable reference
		h := int16(0)
		for _, c := range m {
			h = h*31 + int16(c)
		}
		tokens = append(tokens, TokenPair{int16(TokVarRef), h})
	}

	return tokens
}

// ExtractHookBodies extracts function bodies from on_XXX(..., function(ctx)...end) patterns.
// Returns one token sequence per hook registration found in the source.
func ExtractHookBodies(src string) [][]TokenPair {
	var results [][]TokenPair

	// Simple approach: find each "function(ctx)" and extract until matching "end)"
	funcRe := regexp.MustCompile(`function\s*\(\s*ctx\s*\)`)
	locs := funcRe.FindAllStringIndex(src, -1)

	for _, loc := range locs {
		// Find matching end) by counting nesting
		start := loc[1] // after "function(ctx)"
		depth := 1
		pos := start
		for pos < len(src) && depth > 0 {
			// Simple keyword matching for nesting
			rest := src[pos:]
			if strings.HasPrefix(rest, "function") {
				depth++
				pos += 8
			} else if strings.HasPrefix(rest, "end") && (pos+3 >= len(src) || !isIdentChar(src[pos+3])) {
				depth--
				if depth == 0 {
					break
				}
				pos += 3
			} else {
				pos++
			}
		}

		if depth == 0 {
			body := src[start:pos]
			tokens := TokenizeLua(body)
			results = append(results, tokens)
		}
	}

	return results
}

func isIdentChar(b byte) bool {
	return (b >= 'a' && b <= 'z') || (b >= 'A' && b <= 'Z') || (b >= '0' && b <= '9') || b == '_'
}
