package interp

// Node is the interface for all AST nodes.
type Node interface {
	nodeTag()
	GetLine() int
}

type baseNode struct{ Line int }

func (b baseNode) nodeTag()     {}
func (b baseNode) GetLine() int { return b.Line }

// --- Statements ---

// Chunk is a sequence of statements (top-level or function body).
type Chunk struct {
	baseNode
	Stmts []Node
}

// LocalDecl: local name = expr  OR  local a, b = expr1, expr2
type LocalDecl struct {
	baseNode
	Names []string
	Exprs []Node // may be shorter than Names (extras get nil)
}

// Assign: lhs = rhs (field or index assignment, e.g. ctx.value = 5)
type Assign struct {
	baseNode
	Target Node // DotAccess or IndexAccess
	Value  Node
}

// IfStmt: if/elseif/else chain
type IfStmt struct {
	baseNode
	Cond     Node
	Body     *Chunk
	ElseIfs  []ElseIfClause
	ElseBody *Chunk // nil if no else
}

type ElseIfClause struct {
	Cond Node
	Body *Chunk
}

// ReturnStmt: return (no value in this DSL)
type ReturnStmt struct {
	baseNode
}

// ExprStmt: expression used as statement (function/method calls)
type ExprStmt struct {
	baseNode
	Expr Node
}

// --- Expressions ---

// NumberLit: integer literal
type NumberLit struct {
	baseNode
	Value int
}

// StringLit: string literal
type StringLit struct {
	baseNode
	Value string
}

// BoolLit: true/false
type BoolLit struct {
	baseNode
	Value bool
}

// NilLit: nil
type NilLit struct {
	baseNode
}

// Ident: variable reference
type Ident struct {
	baseNode
	Name string
}

// BinOp: left op right
type BinOp struct {
	baseNode
	Op    string
	Left  Node
	Right Node
}

// UnaryOp: op expr
type UnaryOp struct {
	baseNode
	Op   string // "not" or "-"
	Expr Node
}

// Call: func(args...)
type Call struct {
	baseNode
	Func Node
	Args []Node
}

// MethodCall: obj:method(args...)
type MethodCall struct {
	baseNode
	Object Node
	Method string
	Args   []Node
}

// DotAccess: obj.field
type DotAccess struct {
	baseNode
	Object Node
	Field  string
}

// IndexAccess: obj[expr]
type IndexAccess struct {
	baseNode
	Object Node
	Index  Node
}

// TableCtor: { key=val, ... }
type TableCtor struct {
	baseNode
	Fields []TableField
}

type TableField struct {
	Key   string
	Value Node
}

// FuncLit: function(params) body end
type FuncLit struct {
	baseNode
	Params []string
	Body   *Chunk
}
