package interp

// Expression grammar — precedence-climbing from parseExpr at the top
// through parseOr/And/Comparison/Add/Mul/Unary. Postfix + Primary +
// leaf helpers (Args / TableCtor / FuncLit) live in parser_expr_primary.go.

func (p *Parser) parseExpr() (Node, error) {
	return p.parseOr()
}

func (p *Parser) parseOr() (Node, error) {
	left, err := p.parseAnd()
	if err != nil {
		return nil, err
	}
	for p.check(TkOr) {
		p.advance()
		right, err := p.parseAnd()
		if err != nil {
			return nil, err
		}
		left = &BinOp{baseNode: baseNode{Line: left.GetLine()}, Op: "or", Left: left, Right: right}
	}
	return left, nil
}

func (p *Parser) parseAnd() (Node, error) {
	left, err := p.parseComparison()
	if err != nil {
		return nil, err
	}
	for p.check(TkAnd) {
		p.advance()
		right, err := p.parseComparison()
		if err != nil {
			return nil, err
		}
		left = &BinOp{baseNode: baseNode{Line: left.GetLine()}, Op: "and", Left: left, Right: right}
	}
	return left, nil
}

func (p *Parser) parseComparison() (Node, error) {
	left, err := p.parseAdd()
	if err != nil {
		return nil, err
	}
	for {
		tok := p.peek()
		var op string
		switch tok.Kind {
		case TkEq:
			op = "=="
		case TkNeq:
			op = "~="
		case TkLt:
			op = "<"
		case TkGt:
			op = ">"
		case TkLe:
			op = "<="
		case TkGe:
			op = ">="
		default:
			return left, nil
		}
		p.advance()
		right, err := p.parseAdd()
		if err != nil {
			return nil, err
		}
		left = &BinOp{baseNode: baseNode{Line: left.GetLine()}, Op: op, Left: left, Right: right}
	}
}

func (p *Parser) parseAdd() (Node, error) {
	left, err := p.parseMul()
	if err != nil {
		return nil, err
	}
	for {
		tok := p.peek()
		var op string
		switch tok.Kind {
		case TkPlus:
			op = "+"
		case TkMinus:
			op = "-"
		default:
			return left, nil
		}
		p.advance()
		right, err := p.parseMul()
		if err != nil {
			return nil, err
		}
		left = &BinOp{baseNode: baseNode{Line: left.GetLine()}, Op: op, Left: left, Right: right}
	}
}

func (p *Parser) parseMul() (Node, error) {
	left, err := p.parseUnary()
	if err != nil {
		return nil, err
	}
	for {
		tok := p.peek()
		var op string
		switch tok.Kind {
		case TkStar:
			op = "*"
		case TkSlash:
			op = "/"
		default:
			return left, nil
		}
		p.advance()
		right, err := p.parseUnary()
		if err != nil {
			return nil, err
		}
		left = &BinOp{baseNode: baseNode{Line: left.GetLine()}, Op: op, Left: left, Right: right}
	}
}

func (p *Parser) parseUnary() (Node, error) {
	tok := p.peek()
	if tok.Kind == TkNot {
		p.advance()
		expr, err := p.parseUnary()
		if err != nil {
			return nil, err
		}
		return &UnaryOp{baseNode: baseNode{Line: tok.Line}, Op: "not", Expr: expr}, nil
	}
	if tok.Kind == TkMinus {
		p.advance()
		expr, err := p.parseUnary()
		if err != nil {
			return nil, err
		}
		return &UnaryOp{baseNode: baseNode{Line: tok.Line}, Op: "-", Expr: expr}, nil
	}
	return p.parsePostfix()
}
