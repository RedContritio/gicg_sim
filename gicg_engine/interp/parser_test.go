package interp

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLexer_BasicTokens(t *testing.T) {
	src := `local x = 42`
	tokens, err := Tokenize([]byte(src))
	if err != nil {
		t.Fatal(err)
	}
	// local, x, =, 42, EOF
	if len(tokens) != 5 {
		t.Fatalf("expected 5 tokens, got %d", len(tokens))
	}
	if tokens[0].Kind != TkLocal {
		t.Errorf("expected TkLocal, got %d", tokens[0].Kind)
	}
	if tokens[1].Kind != TkIdent || tokens[1].Val != "x" {
		t.Errorf("expected ident 'x', got %q", tokens[1].Val)
	}
	if tokens[3].Kind != TkNumber || tokens[3].Val != "42" {
		t.Errorf("expected number 42, got %q", tokens[3].Val)
	}
}

func TestLexer_ChineseIdent(t *testing.T) {
	src := `local 赤蝶 = get_char("赤蝶")`
	tokens, err := Tokenize([]byte(src))
	if err != nil {
		t.Fatal(err)
	}
	if tokens[1].Kind != TkIdent || tokens[1].Val != "赤蝶" {
		t.Errorf("expected ident '赤蝶', got %q", tokens[1].Val)
	}
}

func TestLexer_Comments(t *testing.T) {
	src := "local x = 1 -- this is a comment\nlocal y = 2"
	tokens, err := Tokenize([]byte(src))
	if err != nil {
		t.Fatal(err)
	}
	// local x = 1 local y = 2 EOF → 9 tokens
	if len(tokens) != 9 {
		t.Fatalf("expected 9 tokens, got %d", len(tokens))
	}
}

func TestLexer_Operators(t *testing.T) {
	src := `== ~= <= >= < > =`
	tokens, err := Tokenize([]byte(src))
	if err != nil {
		t.Fatal(err)
	}
	expected := []TokenKind{TkEq, TkNeq, TkLe, TkGe, TkLt, TkGt, TkAssign, TkEOF}
	if len(tokens) != len(expected) {
		t.Fatalf("expected %d tokens, got %d", len(expected), len(tokens))
	}
	for i, e := range expected {
		if tokens[i].Kind != e {
			t.Errorf("token %d: expected %d, got %d", i, e, tokens[i].Kind)
		}
	}
}

func TestParser_LocalDecl(t *testing.T) {
	src := `local x = 42`
	tokens, _ := Tokenize([]byte(src))
	chunk, err := Parse(tokens)
	if err != nil {
		t.Fatal(err)
	}
	if len(chunk.Stmts) != 1 {
		t.Fatalf("expected 1 stmt, got %d", len(chunk.Stmts))
	}
	decl, ok := chunk.Stmts[0].(*LocalDecl)
	if !ok {
		t.Fatalf("expected LocalDecl, got %T", chunk.Stmts[0])
	}
	if len(decl.Names) != 1 || decl.Names[0] != "x" {
		t.Errorf("expected name 'x', got %v", decl.Names)
	}
}

func TestParser_IfStmt(t *testing.T) {
	src := `if x == 1 then return end`
	tokens, _ := Tokenize([]byte(src))
	chunk, err := Parse(tokens)
	if err != nil {
		t.Fatal(err)
	}
	if len(chunk.Stmts) != 1 {
		t.Fatalf("expected 1 stmt, got %d", len(chunk.Stmts))
	}
	_, ok := chunk.Stmts[0].(*IfStmt)
	if !ok {
		t.Fatalf("expected IfStmt, got %T", chunk.Stmts[0])
	}
}

func TestParser_FuncLit(t *testing.T) {
	src := `local f = function(ctx) return end`
	tokens, _ := Tokenize([]byte(src))
	chunk, err := Parse(tokens)
	if err != nil {
		t.Fatal(err)
	}
	decl := chunk.Stmts[0].(*LocalDecl)
	_, ok := decl.Exprs[0].(*FuncLit)
	if !ok {
		t.Fatalf("expected FuncLit, got %T", decl.Exprs[0])
	}
}

func TestParser_MethodCall(t *testing.T) {
	src := `hp:set_at(Player.Enemy, enemy, 1)`
	tokens, _ := Tokenize([]byte(src))
	chunk, err := Parse(tokens)
	if err != nil {
		t.Fatal(err)
	}
	stmt := chunk.Stmts[0].(*ExprStmt)
	mc, ok := stmt.Expr.(*MethodCall)
	if !ok {
		t.Fatalf("expected MethodCall, got %T", stmt.Expr)
	}
	if mc.Method != "set_at" {
		t.Errorf("expected method 'set_at', got %q", mc.Method)
	}
	if len(mc.Args) != 3 {
		t.Errorf("expected 3 args, got %d", len(mc.Args))
	}
}

func TestParser_TableCtor(t *testing.T) {
	src := `local t = { min = 0, max = 10, tag = Tag.Shield }`
	tokens, _ := Tokenize([]byte(src))
	chunk, err := Parse(tokens)
	if err != nil {
		t.Fatal(err)
	}
	decl := chunk.Stmts[0].(*LocalDecl)
	tc, ok := decl.Exprs[0].(*TableCtor)
	if !ok {
		t.Fatalf("expected TableCtor, got %T", decl.Exprs[0])
	}
	if len(tc.Fields) != 3 {
		t.Errorf("expected 3 fields, got %d", len(tc.Fields))
	}
}

func TestParser_DotAccess(t *testing.T) {
	src := `ctx.value = ctx.value - absorb`
	tokens, _ := Tokenize([]byte(src))
	chunk, err := Parse(tokens)
	if err != nil {
		t.Fatal(err)
	}
	assign, ok := chunk.Stmts[0].(*Assign)
	if !ok {
		t.Fatalf("expected Assign, got %T", chunk.Stmts[0])
	}
	da, ok := assign.Target.(*DotAccess)
	if !ok {
		t.Fatalf("expected DotAccess target, got %T", assign.Target)
	}
	if da.Field != "value" {
		t.Errorf("expected field 'value', got %q", da.Field)
	}
}

func TestParser_IndexAccess(t *testing.T) {
	src := `local c = _char_by_slot[p][idx]`
	tokens, _ := Tokenize([]byte(src))
	chunk, err := Parse(tokens)
	if err != nil {
		t.Fatal(err)
	}
	decl := chunk.Stmts[0].(*LocalDecl)
	// Should be IndexAccess(IndexAccess(_char_by_slot, p), idx)
	outer, ok := decl.Exprs[0].(*IndexAccess)
	if !ok {
		t.Fatalf("expected IndexAccess, got %T", decl.Exprs[0])
	}
	inner, ok := outer.Object.(*IndexAccess)
	if !ok {
		t.Fatalf("expected inner IndexAccess, got %T", outer.Object)
	}
	ident, ok := inner.Object.(*Ident)
	if !ok {
		t.Fatalf("expected Ident, got %T", inner.Object)
	}
	if ident.Name != "_char_by_slot" {
		t.Errorf("expected '_char_by_slot', got %q", ident.Name)
	}
}

func TestParser_UnaryMinus(t *testing.T) {
	src := `on_reaction_damage(-10, function(ctx) return end)`
	tokens, _ := Tokenize([]byte(src))
	chunk, err := Parse(tokens)
	if err != nil {
		t.Fatal(err)
	}
	stmt := chunk.Stmts[0].(*ExprStmt)
	call, ok := stmt.Expr.(*Call)
	if !ok {
		t.Fatalf("expected Call, got %T", stmt.Expr)
	}
	unary, ok := call.Args[0].(*UnaryOp)
	if !ok {
		t.Fatalf("expected UnaryOp for first arg, got %T", call.Args[0])
	}
	if unary.Op != "-" {
		t.Errorf("expected '-', got %q", unary.Op)
	}
}

// TestParser_AllDSLFiles verifies that every .lua file under data/ can be parsed.
func TestParser_AllDSLFiles(t *testing.T) {
	dataDir := "../../data"
	var files []string
	filepath.Walk(dataDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil
		}
		if !info.IsDir() && filepath.Ext(path) == ".lua" {
			files = append(files, path)
		}
		return nil
	})

	if len(files) == 0 {
		t.Skip("no .lua files found under data/")
	}

	for _, f := range files {
		t.Run(filepath.Base(f), func(t *testing.T) {
			src, err := os.ReadFile(f)
			if err != nil {
				t.Fatal(err)
			}
			tokens, err := Tokenize(src)
			if err != nil {
				t.Fatalf("lexer error: %v", err)
			}
			_, err = Parse(tokens)
			if err != nil {
				t.Fatalf("parser error: %v", err)
			}
		})
	}
}
