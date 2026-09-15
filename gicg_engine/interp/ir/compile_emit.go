package ir

// Low-level emit helpers shared by every lowering site: register
// allocation, op append, and the error stamper. Split out of compile.go
// so the generic AST visitor there stays focused on node dispatch.

import (
	"fmt"
	"reflect"

	"gicg_mono/gicg_engine/interp"
)

// --- low-level emit helpers --------------------------------------------------

func (c *compiler) allocReg() (int16, error) {
	if c.regNext >= MaxRegs {
		return 0, fmt.Errorf("hook exceeds %d registers (got %d)", MaxRegs, c.regNext+1)
	}
	r := c.regNext
	c.regNext++
	return r, nil
}

func (c *compiler) emit(op Op) { c.ops = append(c.ops, op) }

// wrapErr stamps node type + line onto an error so each error site stays
// one line. Type is the unqualified Go name (e.g. "Assign") — the
// "*interp." prefix is dropped because it's noise the reader doesn't need.
func wrapErr(n interp.Node, format string, args ...any) error {
	t := reflect.TypeOf(n)
	if t.Kind() == reflect.Pointer {
		t = t.Elem()
	}
	return fmt.Errorf("ir: %s at line %d: %s", t.Name(), n.GetLine(), fmt.Sprintf(format, args...))
}

func (c *compiler) emitLoadImm(v int16) (int16, error) {
	r, err := c.allocReg()
	if err != nil {
		return 0, err
	}
	c.emit(Op{Opcode: OpLoadImm, Dst: r, Op1: v})
	return r, nil
}

func (c *compiler) emitLoadAddr(kind, addr, idx int16) (int16, error) {
	r, err := c.allocReg()
	if err != nil {
		return 0, err
	}
	c.emit(Op{Opcode: OpLoadAddr, Dst: r, Op1: kind, Op2: addr, Op3: idx})
	return r, nil
}

// emitArithOp covers OpBinOp / OpUnaryOp. op1 is always set (left for
// binary, sole operand for unary); op2 is 0 for unary.
func (c *compiler) emitArithOp(opcode, kind int16, op1, op2 int16) (int16, error) {
	r, err := c.allocReg()
	if err != nil {
		return 0, err
	}
	c.emit(Op{Opcode: opcode, Dst: r, Op1: kind, Op2: op1, Op3: op2})
	return r, nil
}
