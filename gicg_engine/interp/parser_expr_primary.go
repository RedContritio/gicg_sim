package interp

import (
	"fmt"
	"strconv"
)

// Primary / postfix expression parsing: parsePostfix (dot/method/call/
// index), parsePrimary (literals / ident / grouped / table / func),
// plus the leaf helpers parseArgs / parseTableCtor / parseFuncLit.
// Precedence-climbing entry + binary operators live in parser_expr.go.

func (p *Parser) parsePostfix() (Node, error) {
	expr, err := p.parsePrimary()
	if err != nil {
		return nil, err
	}
	for {
		switch p.peek().Kind {
		case TkDot:
			p.advance() // consume '.'
			name, err := p.expect(TkIdent)
			if err != nil {
				return nil, err
			}
			expr = &DotAccess{baseNode: baseNode{Line: name.Line}, Object: expr, Field: name.Val}

		case TkColon:
			p.advance() // consume ':'
			name, err := p.expect(TkIdent)
			if err != nil {
				return nil, err
			}
			if _, err := p.expect(TkLParen); err != nil {
				return nil, err
			}
			args, err := p.parseArgs()
			if err != nil {
				return nil, err
			}
			if _, err := p.expect(TkRParen); err != nil {
				return nil, err
			}
			expr = &MethodCall{baseNode: baseNode{Line: name.Line}, Object: expr, Method: name.Val, Args: args}

		case TkLParen:
			p.advance() // consume '('
			args, err := p.parseArgs()
			if err != nil {
				return nil, err
			}
			if _, err := p.expect(TkRParen); err != nil {
				return nil, err
			}
			expr = &Call{baseNode: baseNode{Line: expr.GetLine()}, Func: expr, Args: args}

		case TkLBrack:
			p.advance() // consume '['
			index, err := p.parseExpr()
			if err != nil {
				return nil, err
			}
			if _, err := p.expect(TkRBrack); err != nil {
				return nil, err
			}
			expr = &IndexAccess{baseNode: baseNode{Line: expr.GetLine()}, Object: expr, Index: index}

		default:
			return expr, nil
		}
	}
}

func (p *Parser) parsePrimary() (Node, error) {
	tok := p.peek()
	switch tok.Kind {
	case TkNumber:
		p.advance()
		val, err := strconv.Atoi(tok.Val)
		if err != nil {
			return nil, fmt.Errorf("line %d: invalid number %q", tok.Line, tok.Val)
		}
		return &NumberLit{baseNode: baseNode{Line: tok.Line}, Value: val}, nil

	case TkString:
		p.advance()
		return &StringLit{baseNode: baseNode{Line: tok.Line}, Value: tok.Val}, nil

	case TkTrue:
		p.advance()
		return &BoolLit{baseNode: baseNode{Line: tok.Line}, Value: true}, nil

	case TkFalse:
		p.advance()
		return &BoolLit{baseNode: baseNode{Line: tok.Line}, Value: false}, nil

	case TkNil:
		p.advance()
		return &NilLit{baseNode: baseNode{Line: tok.Line}}, nil

	case TkIdent:
		p.advance()
		return &Ident{baseNode: baseNode{Line: tok.Line}, Name: tok.Val}, nil

	case TkLParen:
		p.advance() // consume '('
		expr, err := p.parseExpr()
		if err != nil {
			return nil, err
		}
		if _, err := p.expect(TkRParen); err != nil {
			return nil, err
		}
		return expr, nil

	case TkLBrace:
		return p.parseTableCtor()

	case TkFunction:
		return p.parseFuncLit()

	default:
		return nil, fmt.Errorf("line %d: unexpected token %d (%q)", tok.Line, tok.Kind, tok.Val)
	}
}

func (p *Parser) parseArgs() ([]Node, error) {
	var args []Node
	if p.check(TkRParen) {
		return args, nil
	}
	first, err := p.parseExpr()
	if err != nil {
		return nil, err
	}
	args = append(args, first)
	for p.match(TkComma) {
		arg, err := p.parseExpr()
		if err != nil {
			return nil, err
		}
		args = append(args, arg)
	}
	return args, nil
}

func (p *Parser) parseTableCtor() (Node, error) {
	line := p.advance().Line // consume '{'
	var fields []TableField
	for !p.check(TkRBrace) && !p.check(TkEOF) {
		name, err := p.expect(TkIdent)
		if err != nil {
			return nil, err
		}
		if _, err := p.expect(TkAssign); err != nil {
			return nil, err
		}
		val, err := p.parseExpr()
		if err != nil {
			return nil, err
		}
		fields = append(fields, TableField{Key: name.Val, Value: val})
		p.match(TkComma) // optional trailing comma
	}
	if _, err := p.expect(TkRBrace); err != nil {
		return nil, err
	}
	return &TableCtor{baseNode: baseNode{Line: line}, Fields: fields}, nil
}

func (p *Parser) parseFuncLit() (Node, error) {
	line := p.advance().Line // consume 'function'
	if _, err := p.expect(TkLParen); err != nil {
		return nil, err
	}
	var params []string
	if !p.check(TkRParen) {
		name, err := p.expect(TkIdent)
		if err != nil {
			return nil, err
		}
		params = append(params, name.Val)
		for p.match(TkComma) {
			name, err := p.expect(TkIdent)
			if err != nil {
				return nil, err
			}
			params = append(params, name.Val)
		}
	}
	if _, err := p.expect(TkRParen); err != nil {
		return nil, err
	}
	body, err := p.parseChunk()
	if err != nil {
		return nil, err
	}
	if _, err := p.expect(TkEnd); err != nil {
		return nil, err
	}
	return &FuncLit{baseNode: baseNode{Line: line}, Params: params, Body: body}, nil
}
