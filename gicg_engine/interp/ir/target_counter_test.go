package ir

import (
	engine "gicg_mono/gicg_engine"
	"testing"
)

func TestDamageTargetCounterPreservedInIR(t *testing.T) {
	body := parseBody(t, `deal_damage(Target.EnemyAll, Element.Fire, 1, {source=Source.Status, target_counter=mark})`)
	compiled, err := CompileHookIR(body, map[string]TypedBinding{"mark": {Kind: BindingCounter, ID: 17}})
	if err != nil {
		t.Fatal(err)
	}
	selectorReg := int16(-1)
	for _, op := range compiled.MainOps {
		if op.Opcode == OpLoadAddr && op.Op1 == AddrLocalVar && op.Op2 == 17 {
			selectorReg = op.Dst
		}
		if op.Opcode == OpKwArg && op.Op1 == int16(engine.TokKwTargetCounter) {
			if selectorReg < 0 || op.Op2 != selectorReg {
				t.Fatal("target selector lost its counter binding")
			}
			return
		}
	}
	t.Fatal("target_counter is missing from compiled rule observation")
}

func TestDamageActorPreservedInIR(t *testing.T) {
	compiled, err := CompileHookIR(parseBody(t, `deal_damage(Target.EnemyActive, Element.Fire, 1, {source=Source.Support, actor=owner})`), map[string]TypedBinding{"owner": {Kind: BindingChar, ID: 19}})
	if err != nil {
		t.Fatal(err)
	}
	for _, op := range compiled.MainOps {
		if op.Opcode == OpKwArg && op.Op1 == int16(engine.TokKwActor) {
			return
		}
	}
	t.Fatal("actor override omitted from rule IR")
}

func TestIndependentBuffPrimitivesPreservedInIR(t *testing.T) {
	compiled, err := CompileHookIR(parseBody(t, `spawn_buff(b, 2, 3)
 set_buff_duration(buff_duration() - 1)`), map[string]TypedBinding{"b": {Kind: BindingCounter, ID: 17}})
	if err != nil {
		t.Fatal(err)
	}
	seen := map[int16]bool{}
	for _, op := range compiled.MainOps {
		if op.Opcode == OpCall {
			seen[op.Op1] = true
		}
	}
	for _, token := range []int16{int16(engine.TokSpawnBuff), int16(engine.TokBuffDuration), int16(engine.TokSetBuffDuration)} {
		if !seen[token] {
			t.Fatalf("missing primitive %d", token)
		}
	}
}
