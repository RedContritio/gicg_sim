package tests

// IR showcase — opt-in demo. Run:
//   IR_SHOWCASE=1 go test ./gicg_engine/tests/ -run TestIRShowcase -v
//
// Picks a real hook from a known DSL file, prints its Lua source body
// side-by-side with the compiled IR ops (operands decoded to token
// names where possible). Not a test in the assertion sense — purely
// diagnostic output for human inspection.

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
	"gicg_mono/gicg_engine/interp/ir"
)

func TestIRShowcase(t *testing.T) {
	if os.Getenv("IR_SHOWCASE") == "" {
		t.Skip("set IR_SHOWCASE=1 to run")
	}

	env := NewGame(t, []string{"赤蝶"}, []string{"赤蝶"})
	finalizeHookIRsForTest(t, env.G, env.RT)

	// Pick interesting hooks: 6-50 ops, from named DSL files (not
	// canonical procedural markers). Show 3 across complexity range.
	type pick struct {
		fileBase string // basename like "玄冰"
		h        *engine.Hook
	}
	var picks []pick
	for _, h := range env.G.Hooks.AllHooks() {
		if h.Repr == nil {
			continue
		}
		ch, ok := h.Repr.(ir.CompiledHook)
		if !ok {
			continue
		}
		n := len(ch.MainOps)
		if n < 5 {
			continue
		}
		base := h.Source
		if i := strings.IndexByte(base, '#'); i >= 0 {
			base = base[:i]
		}
		// Skip system-level files (less interesting semantically than
		// char skill / buff hooks).
		if base == "round" || base == "draw" || base == "dice" || base == "tag" || base == "phase" {
			continue
		}
		picks = append(picks, pick{fileBase: base, h: h})
	}
	if len(picks) == 0 {
		t.Fatalf("no non-trivial compiled hooks — RC2 may not have landed")
	}

	sort.Slice(picks, func(i, j int) bool {
		return len(picks[i].h.Repr.(ir.CompiledHook).MainOps) < len(picks[j].h.Repr.(ir.CompiledHook).MainOps)
	})

	// Pick small / medium / large by op count.
	idxs := []int{
		0,
		len(picks) / 2,
		len(picks) - 1,
	}
	seen := map[int]bool{}
	for _, idx := range idxs {
		if seen[idx] {
			continue
		}
		seen[idx] = true
		showHook(t, env.RT, picks[idx])
	}
}

func showHook(t *testing.T, rt *interp.Runtime, p struct {
	fileBase string
	h        *engine.Hook
}) {
	t.Helper()
	ch := p.h.Repr.(ir.CompiledHook)
	srcPath := findLuaPath(rt, p.fileBase)
	t.Logf("================================================================================")
	t.Logf("hook source = %s    (HookType = %d)", p.h.Source, p.h.Type)
	t.Logf("file        = %s", srcPath)
	t.Logf("ops         = %d MainOps + %d Lambdas", len(ch.MainOps), len(ch.Lambdas))
	t.Logf("")

	if srcPath != "" {
		t.Logf("---- lua source (full file) ----")
		body, err := os.ReadFile(srcPath)
		if err == nil {
			for i, line := range strings.Split(string(body), "\n") {
				t.Logf("  %3d  %s", i+1, line)
			}
		}
		t.Logf("")
	}

	t.Logf("---- IR ops (decoded) ----")
	for i, op := range ch.MainOps {
		t.Logf("  %3d  %s", i, decodeOp(op))
	}
	t.Logf("")
}

func findLuaPath(rt *interp.Runtime, base string) string {
	for _, p := range rt.LoadedFiles {
		if strings.TrimSuffix(filepath.Base(p), ".lua") == base {
			return p
		}
	}
	return ""
}

func decodeOp(op ir.Op) string {
	opcodeName := map[int16]string{
		ir.OpNop: "Nop", ir.OpLoadImm: "LoadImm", ir.OpLoadReg: "LoadReg",
		ir.OpLoadAddr: "LoadAddr", ir.OpStoreAddr: "StoreAddr",
		ir.OpBinOp: "BinOp", ir.OpUnaryOp: "UnaryOp", ir.OpCall: "Call",
		ir.OpCJump: "CJump", ir.OpJump: "Jump", ir.OpReturn: "Return",
		ir.OpKwArg: "KwArg", ir.OpDeferFn: "DeferFn", ir.OpLoadNil: "LoadNil",
	}[op.Opcode]
	if opcodeName == "" {
		opcodeName = fmt.Sprintf("?op%d", op.Opcode)
	}
	dst := "dst=_"
	if op.Dst >= 0 {
		dst = fmt.Sprintf("dst=r%d", op.Dst)
	}
	binOpName := map[int16]string{
		ir.BinAdd: "+", ir.BinSub: "-", ir.BinMul: "*", ir.BinDiv: "/",
		ir.BinEq: "==", ir.BinNeq: "!=", ir.BinLt: "<", ir.BinGt: ">",
		ir.BinLe: "<=", ir.BinGe: ">=", ir.BinAnd: "and", ir.BinOr: "or",
	}
	addrKind := map[int16]string{
		1: "CtxField", 2: "Counter", 3: "CharAttr", 4: "LocalVar", 5: "Enum",
	}

	switch op.Opcode {
	case ir.OpLoadImm:
		return fmt.Sprintf("%-10s %-7s imm=%d", opcodeName, dst, op.Op1)
	case ir.OpLoadReg:
		return fmt.Sprintf("%-10s %-7s src=r%d", opcodeName, dst, op.Op1)
	case ir.OpLoadAddr, ir.OpStoreAddr:
		kind := addrKind[op.Op1]
		name := decodeAddr(op.Op1, op.Op2)
		return fmt.Sprintf("%-10s %-7s kind=%-8s addr=%d(%s) idx_reg=%s", opcodeName, dst, kind, op.Op2, name, regName(op.Op3))
	case ir.OpBinOp:
		return fmt.Sprintf("%-10s %-7s %s r%d, r%d", opcodeName, dst, binOpName[op.Op1], op.Op2, op.Op3)
	case ir.OpCall:
		return fmt.Sprintf("%-10s %-7s fn=%-22s argc=%d reg_base=%s", opcodeName, dst, decodeBuiltin(op.Op1), op.Op2, regName(op.Op3))
	case ir.OpCJump:
		return fmt.Sprintf("%-10s %-7s cond=r%d target=op%d", opcodeName, dst, op.Op1, op.Op2)
	case ir.OpJump:
		return fmt.Sprintf("%-10s %-7s target=op%d", opcodeName, dst, op.Op1)
	case ir.OpReturn:
		return fmt.Sprintf("%-10s %-7s val=%s", opcodeName, dst, regName(op.Op1))
	case ir.OpKwArg:
		return fmt.Sprintf("%-10s %-7s key=%-18s val=r%d", opcodeName, dst, decodeKwArg(op.Op1), op.Op2)
	case ir.OpDeferFn:
		return fmt.Sprintf("%-10s %-7s lambda_idx=%d", opcodeName, dst, op.Op1)
	}
	return fmt.Sprintf("%-10s %s", opcodeName, dst)
}

func regName(r int16) string {
	if r < 0 {
		return "_"
	}
	return fmt.Sprintf("r%d", r)
}

func decodeBuiltin(tok int16) string {
	if name, ok := engine.ReverseLookup("builtin", tok); ok {
		return fmt.Sprintf("%s(%d)", name, tok)
	}
	return fmt.Sprintf("tok=%d", tok)
}

func decodeKwArg(tok int16) string {
	if name, ok := engine.ReverseLookup("kwarg", tok); ok {
		return fmt.Sprintf("%s(%d)", name, tok)
	}
	return fmt.Sprintf("tok=%d", tok)
}

func decodeAddr(kind, id int16) string {
	switch kind {
	case 1:
		if name, ok := engine.ReverseLookup("ctx_field", id); ok {
			return name
		}
	case 5:
		if name, ok := engine.ReverseLookup("enum", id); ok {
			return name
		}
	}
	return "?"
}
