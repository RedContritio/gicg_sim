package ir

import (
	"reflect"
	"testing"
)

func TestObservationPreservesLambdaBodiesAndBoundaries(t *testing.T) {
	h := CompiledHook{
		MainOps: []Op{{Opcode: OpDeferFn, Op1: 0}, {Opcode: OpReturn}},
		Lambdas: [][]Op{
			{{Opcode: OpDeferFn, Op1: 1}, {Opcode: OpLoadImm, Dst: 2, Op1: 17}},
			{{Opcode: OpLoadImm, Dst: 3, Op1: -7}},
		},
	}
	out := make([]int32, 45)
	for i := range out {
		out[i] = 999
	}
	h.WriteObsInts(out)
	want := []int32{
		12, 0, 0, 0, 0, 10, 0, 0, 0, 0,
		14, 0, 2, -1, -1, 12, 0, 1, 0, 0, 1, 2, 17, 0, 0,
		14, 1, 1, -1, -1, 1, 3, -7, 0, 0,
		0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
	}
	if !reflect.DeepEqual(out, want) {
		t.Fatalf("lost body, boundary, signed operand or padding: %v", out)
	}
}

func TestObservationRejectsOverflowBeforeWriting(t *testing.T) {
	h := CompiledHook{MainOps: []Op{{Opcode: OpDeferFn}}, Lambdas: [][]Op{{{Opcode: OpReturn}}}}
	out := []int32{7, 7, 7, 7, 7, 7, 7, 7, 7, 7} // 2 slots, requires 3
	defer func() {
		if recover() == nil {
			t.Fatal("truncated observation accepted")
		}
		for _, v := range out {
			if v != 7 {
				t.Fatal("failed export partially overwrote destination")
			}
		}
	}()
	h.WriteObsInts(out)
}
