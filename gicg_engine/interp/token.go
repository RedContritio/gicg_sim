package interp

type TokenKind int

const (
	TkEOF TokenKind = iota

	// Literals
	TkNumber // 42
	TkString // "hello"
	TkIdent  // variable_name, 赤蝶

	// Keywords
	TkLocal
	TkIf
	TkThen
	TkElseif
	TkElse
	TkEnd
	TkReturn
	TkFunction
	TkAnd
	TkOr
	TkNot
	TkTrue
	TkFalse
	TkNil

	// Operators
	TkPlus   // +
	TkMinus  // -
	TkStar   // *
	TkSlash  // /
	TkEq     // ==
	TkNeq    // ~=
	TkLt     // <
	TkGt     // >
	TkLe     // <=
	TkGe     // >=
	TkAssign // =

	// Punctuation
	TkLParen // (
	TkRParen // )
	TkLBrace // {
	TkRBrace // }
	TkLBrack // [
	TkRBrack // ]
	TkDot    // .
	TkColon  // :
	TkComma  // ,
)

type Token struct {
	Kind TokenKind
	Val  string // raw text for number/string/ident
	Line int
}

var keywords = map[string]TokenKind{
	"local":    TkLocal,
	"if":       TkIf,
	"then":     TkThen,
	"elseif":   TkElseif,
	"else":     TkElse,
	"end":      TkEnd,
	"return":   TkReturn,
	"function": TkFunction,
	"and":      TkAnd,
	"or":       TkOr,
	"not":      TkNot,
	"true":     TkTrue,
	"false":    TkFalse,
	"nil":      TkNil,
}
