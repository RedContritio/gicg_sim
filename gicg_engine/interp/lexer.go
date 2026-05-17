package interp

import (
	"fmt"
	"unicode"
	"unicode/utf8"
)

type Lexer struct {
	src  []byte
	pos  int
	line int
}

func NewLexer(src []byte) *Lexer {
	return &Lexer{src: src, pos: 0, line: 1}
}

func (l *Lexer) peek() rune {
	if l.pos >= len(l.src) {
		return 0
	}
	r, _ := utf8.DecodeRune(l.src[l.pos:])
	return r
}

func (l *Lexer) advance() rune {
	r, size := utf8.DecodeRune(l.src[l.pos:])
	l.pos += size
	if r == '\n' {
		l.line++
	}
	return r
}

func (l *Lexer) skipWhitespaceAndComments() {
	for l.pos < len(l.src) {
		r := l.peek()
		if r == '-' && l.pos+1 < len(l.src) && l.src[l.pos+1] == '-' {
			// Line comment
			for l.pos < len(l.src) && l.peek() != '\n' {
				l.advance()
			}
			continue
		}
		if r == ' ' || r == '\t' || r == '\r' || r == '\n' {
			l.advance()
			continue
		}
		break
	}
}

func isIdentStart(r rune) bool {
	return r == '_' || unicode.IsLetter(r)
}

func isIdentPart(r rune) bool {
	return r == '_' || unicode.IsLetter(r) || unicode.IsDigit(r)
}

func (l *Lexer) Next() (Token, error) {
	l.skipWhitespaceAndComments()

	if l.pos >= len(l.src) {
		return Token{Kind: TkEOF, Line: l.line}, nil
	}

	line := l.line
	r := l.peek()

	// Number
	if unicode.IsDigit(r) {
		start := l.pos
		for l.pos < len(l.src) && unicode.IsDigit(l.peek()) {
			l.advance()
		}
		return Token{Kind: TkNumber, Val: string(l.src[start:l.pos]), Line: line}, nil
	}

	// String
	if r == '"' {
		l.advance() // skip opening quote
		start := l.pos
		for l.pos < len(l.src) && l.peek() != '"' {
			if l.peek() == '\\' {
				l.advance() // skip escape
			}
			l.advance()
		}
		val := string(l.src[start:l.pos])
		if l.pos < len(l.src) {
			l.advance() // skip closing quote
		}
		return Token{Kind: TkString, Val: val, Line: line}, nil
	}

	// Identifier or keyword
	if isIdentStart(r) {
		start := l.pos
		for l.pos < len(l.src) && isIdentPart(l.peek()) {
			l.advance()
		}
		word := string(l.src[start:l.pos])
		if kind, ok := keywords[word]; ok {
			return Token{Kind: kind, Val: word, Line: line}, nil
		}
		return Token{Kind: TkIdent, Val: word, Line: line}, nil
	}

	// Operators and punctuation
	l.advance()
	switch r {
	case '+':
		return Token{Kind: TkPlus, Line: line}, nil
	case '*':
		return Token{Kind: TkStar, Line: line}, nil
	case '/':
		return Token{Kind: TkSlash, Line: line}, nil
	case '(':
		return Token{Kind: TkLParen, Line: line}, nil
	case ')':
		return Token{Kind: TkRParen, Line: line}, nil
	case '{':
		return Token{Kind: TkLBrace, Line: line}, nil
	case '}':
		return Token{Kind: TkRBrace, Line: line}, nil
	case '[':
		return Token{Kind: TkLBrack, Line: line}, nil
	case ']':
		return Token{Kind: TkRBrack, Line: line}, nil
	case '.':
		return Token{Kind: TkDot, Line: line}, nil
	case ':':
		return Token{Kind: TkColon, Line: line}, nil
	case ',':
		return Token{Kind: TkComma, Line: line}, nil
	case '-':
		// Could be negative number start or minus operator
		// Parser handles unary minus; lexer just returns TkMinus
		return Token{Kind: TkMinus, Line: line}, nil
	case '=':
		if l.pos < len(l.src) && l.peek() == '=' {
			l.advance()
			return Token{Kind: TkEq, Line: line}, nil
		}
		return Token{Kind: TkAssign, Line: line}, nil
	case '~':
		if l.pos < len(l.src) && l.peek() == '=' {
			l.advance()
			return Token{Kind: TkNeq, Line: line}, nil
		}
		return Token{}, fmt.Errorf("line %d: unexpected '~'", line)
	case '<':
		if l.pos < len(l.src) && l.peek() == '=' {
			l.advance()
			return Token{Kind: TkLe, Line: line}, nil
		}
		return Token{Kind: TkLt, Line: line}, nil
	case '>':
		if l.pos < len(l.src) && l.peek() == '=' {
			l.advance()
			return Token{Kind: TkGe, Line: line}, nil
		}
		return Token{Kind: TkGt, Line: line}, nil
	}

	return Token{}, fmt.Errorf("line %d: unexpected character %q", line, r)
}

// Tokenize returns all tokens from the source.
func Tokenize(src []byte) ([]Token, error) {
	lex := NewLexer(src)
	var tokens []Token
	for {
		tok, err := lex.Next()
		if err != nil {
			return nil, err
		}
		tokens = append(tokens, tok)
		if tok.Kind == TkEOF {
			break
		}
	}
	return tokens, nil
}
