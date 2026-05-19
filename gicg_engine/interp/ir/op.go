// Package ir compiles hook-body AST chunks (gicg_engine/interp.Chunk)
// into a 3-address-code IR (Op slice). It replaces the legacy
// token-stream obs that hashed identifiers into a numeric field, which
// blew up fp32 backward in training (see Stage 3 NaN report).
//
// IR design: every operand is a typed int16 slot. Memory reads/writes
// go through OpLoadAddr / OpStoreAddr keyed by (AddrKind, addr_id,
// idx_reg) — addr_id is reused from engine's tokenizer token IDs
// (TokCtxValue, TokMHp, …) so the encoder embedding table is shared.
//
// OpCall has two interpretations of Op2:
//   - regular builtins / char-attr — Op2 = n_args, Op3 = reg_base
//     (args sit in regs reg_base, reg_base+1, …, reg_base+n_args-1)
//   - counter side-effect methods (TokMAdd..TokMFillAll) — Op2 =
//     counter_id (typed AddrCounter), Op3 = reg_base for non-receiver
//     args. The interpreter dispatches on Op1 to pick interpretation;
//     keeping it in a single opcode avoids growing the encoder vocab.
//
// Counter :get / :get_at / :set / :set_at compile to OpLoadAddr /
// OpStoreAddr directly (they are pure load/store, not effects). All
// other counter methods (:add, :sub, :cmin, :cmax, :decay_all,
// :fill_all) route via OpCall — the compiler refuses to encode
// "how to lower :add into load-binop-store"; that policy lives in
// the IR-3 interpreter.
//
// Scope: this is IR-1 only. We do NOT touch the engine.Hook struct,
// observation schema, capi, or Python — those are IR-2/3/4.
package ir

// Op is one 3-address-code instruction. Operand semantics depend on Opcode.
type Op struct {
	Opcode int16
	Dst    int16
	Op1    int16
	Op2    int16
	Op3    int16
}

// Opcodes. Encoder (Python) treats Opcode as embedding index so values are frozen.
const (
	OpNop       int16 = 0
	OpLoadImm   int16 = 1
	OpLoadReg   int16 = 2
	OpLoadAddr  int16 = 3
	OpStoreAddr int16 = 4
	OpBinOp     int16 = 5
	OpUnaryOp   int16 = 6
	OpCall      int16 = 7
	OpCJump     int16 = 8
	OpJump      int16 = 9
	OpReturn    int16 = 10
)

// AddrKind — memory address class for OpLoadAddr / OpStoreAddr.
const (
	AddrCtxField int16 = 1 // addr_id ∈ TokCtxValue..TokCtxNeedTarget
	AddrCounter  int16 = 2 // addr_id = counter slot ID; Op3 = idx reg (NullReg if scalar)
	AddrCharAttr int16 = 3 // addr_id ∈ TokMHp..TokMWeapon; Op3 = receiver reg
	AddrLocalVar int16 = 4 // addr_id = typed-binding ID (engine-assigned)
	AddrEnum     int16 = 5 // addr_id ∈ TokElementFire..TokZoneDeck
)

// BinOp / UnaryOp kinds (OpBinOp.Op1 / OpUnaryOp.Op1).
const (
	BinAdd int16 = 1
	BinSub int16 = 2
	BinMul int16 = 3
	BinDiv int16 = 4
	BinEq  int16 = 5
	BinNeq int16 = 6
	BinLt  int16 = 7
	BinGt  int16 = 8
	BinLe  int16 = 9
	BinGe  int16 = 10
	BinAnd int16 = 11
	BinOr  int16 = 12

	UnaryNot int16 = 1
	UnaryNeg int16 = 2
)

// NullReg — operand slot unused.
const NullReg int16 = -1

// MaxRegs — hard cap on register count per hook (IR observation slot budget).
// Exported so the IR-3 interpreter + Python encoder validate against the same
// constant rather than the literal 32.
const MaxRegs = 32

// binOpKindByString — Lua operator string → BinOp kind. Pure data table;
// compiler reads via a single lookup + ok check.
var binOpKindByString = map[string]int16{
	"+":   BinAdd,
	"-":   BinSub,
	"*":   BinMul,
	"/":   BinDiv,
	"==":  BinEq,
	"~=":  BinNeq,
	"<":   BinLt,
	">":   BinGt,
	"<=":  BinLe,
	">=":  BinGe,
	"and": BinAnd,
	"or":  BinOr,
}

// unaryOpKindByString — Lua unary operator string → UnaryOp kind.
var unaryOpKindByString = map[string]int16{
	"not": UnaryNot,
	"-":   UnaryNeg,
}

// counterMethodArity — recognized counter method names mapped to
// non-receiver arg count. Methods absent here are rejected as unknown.
// The load/store subset (get/set/get_at/set_at) lowers to OpLoadAddr /
// OpStoreAddr; the rest lower to a single OpCall (see Op2 dual
// interpretation above).
var counterMethodArity = map[string]int{
	"get": 0, "set": 1, "get_at": 1, "set_at": 2,
	"add": 1, "sub": 1, "add_at": 2, "sub_at": 2,
	"cmin": 1, "cmax": 1, "decay_all": 0, "fill_all": 1,
}

// charAttrMethods — names dispatched in compileCharAttrMethod (pure
// 0-arg reads → AddrCharAttr load with receiver in Op3). Set-shape
// (not map[string]int like counterMethodArity) because arity is fixed
// at 0 by construction; asymmetry is intentional, see compileCharAttrMethod
// for the arity assertion.
var charAttrMethods = map[string]struct{}{
	"hp": {}, "energy": {}, "alive": {},
	"owner_player": {}, "owner_char": {},
	"name": {}, "element": {}, "weapon": {},
}
