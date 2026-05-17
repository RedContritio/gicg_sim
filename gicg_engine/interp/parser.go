package interp

import (
	"fmt"
)

type Parser struct {
	tokens []Token
	pos    int
}

func NewParser(tokens []Token) *Parser {
	return &Parser{tokens: tokens, pos: 0}
}

func (p *Parser) peek() Token {
	if p.pos >= len(p.tokens) {
		return Token{Kind: TkEOF}
	}
	return p.tokens[p.pos]
}

func (p *Parser) advance() Token {
	tok := p.peek()
	if p.pos < len(p.tokens) {
		p.pos++
	}
	return tok
}

func (p *Parser) expect(kind TokenKind) (Token, error) {
	tok := p.advance()
	if tok.Kind != kind {
		return tok, fmt.Errorf("line %d: expected %d, got %d (%q)", tok.Line, kind, tok.Kind, tok.Val)
	}
	return tok, nil
}

func (p *Parser) check(kind TokenKind) bool {
	return p.peek().Kind == kind
}

func (p *Parser) match(kind TokenKind) bool {
	if p.check(kind) {
		p.advance()
		return true
	}
	return false
}

// Parse parses the entire source into a Chunk.
func Parse(tokens []Token) (*Chunk, error) {
	p := NewParser(tokens)
	chunk, err := p.parseChunk()
	if err != nil {
		return nil, err
	}
	if !p.check(TkEOF) {
		tok := p.peek()
		return nil, fmt.Errorf("line %d: unexpected token %q", tok.Line, tok.Val)
	}
	return chunk, nil
}

func (p *Parser) parseChunk() (*Chunk, error) {
	chunk := &Chunk{baseNode: baseNode{Line: p.peek().Line}}
	for {
		tok := p.peek()
		if tok.Kind == TkEOF || tok.Kind == TkEnd || tok.Kind == TkElse || tok.Kind == TkElseif {
			break
		}
		stmt, err := p.parseStatement()
		if err != nil {
			return nil, err
		}
		chunk.Stmts = append(chunk.Stmts, stmt)
	}
	return chunk, nil
}

func (p *Parser) parseStatement() (Node, error) {
	tok := p.peek()
	switch tok.Kind {
	case TkLocal:
		return p.parseLocalDecl()
	case TkIf:
		return p.parseIfStmt()
	case TkReturn:
		return p.parseReturn()
	default:
		return p.parseAssignOrCall()
	}
}

func (p *Parser) parseLocalDecl() (Node, error) {
	line := p.advance().Line // consume 'local'
	name, err := p.expect(TkIdent)
	if err != nil {
		return nil, err
	}
	names := []string{name.Val}
	for p.match(TkComma) {
		n, err := p.expect(TkIdent)
		if err != nil {
			return nil, err
		}
		names = append(names, n.Val)
	}
	var exprs []Node
	if p.match(TkAssign) {
		first, err := p.parseExpr()
		if err != nil {
			return nil, err
		}
		exprs = append(exprs, first)
		for p.match(TkComma) {
			e, err := p.parseExpr()
			if err != nil {
				return nil, err
			}
			exprs = append(exprs, e)
		}
	}
	return &LocalDecl{baseNode: baseNode{Line: line}, Names: names, Exprs: exprs}, nil
}

func (p *Parser) parseIfStmt() (Node, error) {
	line := p.advance().Line // consume 'if'
	cond, err := p.parseExpr()
	if err != nil {
		return nil, err
	}
	if _, err := p.expect(TkThen); err != nil {
		return nil, err
	}
	body, err := p.parseChunk()
	if err != nil {
		return nil, err
	}

	var elseifs []ElseIfClause
	for p.check(TkElseif) {
		p.advance() // consume 'elseif'
		eicond, err := p.parseExpr()
		if err != nil {
			return nil, err
		}
		if _, err := p.expect(TkThen); err != nil {
			return nil, err
		}
		eibody, err := p.parseChunk()
		if err != nil {
			return nil, err
		}
		elseifs = append(elseifs, ElseIfClause{Cond: eicond, Body: eibody})
	}

	var elseBody *Chunk
	if p.match(TkElse) {
		elseBody, err = p.parseChunk()
		if err != nil {
			return nil, err
		}
	}

	if _, err := p.expect(TkEnd); err != nil {
		return nil, err
	}
	return &IfStmt{
		baseNode: baseNode{Line: line},
		Cond:     cond,
		Body:     body,
		ElseIfs:  elseifs,
		ElseBody: elseBody,
	}, nil
}

func (p *Parser) parseReturn() (Node, error) {
	line := p.advance().Line // consume 'return'
	return &ReturnStmt{baseNode: baseNode{Line: line}}, nil
}

func (p *Parser) parseAssignOrCall() (Node, error) {
	expr, err := p.parseExpr()
	if err != nil {
		return nil, err
	}
	// Check for assignment: target = value
	if p.match(TkAssign) {
		val, err := p.parseExpr()
		if err != nil {
			return nil, err
		}
		return &Assign{baseNode: baseNode{Line: expr.GetLine()}, Target: expr, Value: val}, nil
	}
	// Otherwise it's an expression statement (call)
	return &ExprStmt{baseNode: baseNode{Line: expr.GetLine()}, Expr: expr}, nil
}

// --- Expression parsing (precedence climbing) ---

// Expression-grammar functions (parseExpr and below, parseArgs,
// parseTableCtor, parseFuncLit) live in parser_expr.go.
