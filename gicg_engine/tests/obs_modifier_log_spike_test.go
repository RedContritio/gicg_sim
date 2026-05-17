package tests

// TestObsModifierLogSpike — ADR-0019 §B.2 obs encoder for typed Modifier
// log per RecentDamageEvent。
//
// 验证:
//   1. DynamicObsSize 含 modifier_log 段 (160 slots = K=8 × K_mod=4 × 5)
//   2. 触发 1 damage 后 modifier_log[0] 至少 1 stage modifier (Boost stage
//      对应 type/add/mul aggregate),5 fields 正确编码:
//      kind / value_before / value_after / element_before / element_after
//   3. 段位置在 DynamicObsSize 末尾 (recent_damage → prepare → modifier_log)
//   4. 无 event 槽 padding 0

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestObsModifierLogSpike(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	// Test 1: DynamicObsSize 含新段
	if engine.ObsModifierLogSlots != 8*4*5 {
		t.Errorf("ObsModifierLogSlots = %d, want 160 (K=8 × K_mod=4 × 5)",
			engine.ObsModifierLogSlots)
	}
	obs := g.BuildDynamicObs(0)
	if len(obs) != engine.DynamicObsSize() {
		t.Fatalf("obs len = %d, want %d", len(obs), engine.DynamicObsSize())
	}

	// modifier_log 段位置:dyn obs 末尾(recent_damage → prepare → modifier_log)
	modLogOffset := engine.DynamicObsSize() - engine.ObsModifierLogSlots

	// 初始(无 damage event)— Round-2 review M1 修复后:padding 字段
	// categorical (kind=0 / element_before=3 / element_after=4) = -1,
	// scalar (value_before=1 / value_after=2) = 0
	const fields = engine.ObsModifierLogFieldCount
	const kMod = engine.ObsModifierLogKMod
	for i := 0; i < engine.ObsRecentDamageEvents; i++ {
		for j := 0; j < kMod; j++ {
			base := modLogOffset + (i*kMod+j)*fields
			// categorical: kind / elem_before / elem_after = -2 (Round-3 M3 sentinel)
			for _, fi := range []int{0, 3, 4} {
				if obs[base+fi] != -2 {
					t.Errorf("initial obs modifier_log[event=%d,mod=%d,field=%d] = %d, want -2 (padding sentinel)",
						i, j, fi, obs[base+fi])
				}
			}
			// scalar: value_before / value_after = 0
			for _, fi := range []int{1, 2} {
				if obs[base+fi] != 0 {
					t.Errorf("initial obs modifier_log[event=%d,mod=%d,field=%d] = %d, want 0 (scalar padding)",
						i, j, fi, obs[base+fi])
				}
			}
		}
	}

	// Test 2: 触发 1 damage,验证 modifier_log 段
	p1HpID := env.RT.Chars.BySlot[1][0].HPCounterID
	g.PushEvent(engine.EventFrame{Player: 0, Char: 0, ActionCtx: engine.ActUseSkill})
	g.DealDamage(p1HpID, engine.ElemPhysical, 2, engine.DamageOpts{
		ActorPlayer: 0, ActorChar: 0,
	})
	g.PopEvent()

	obs = g.BuildDynamicObs(0)

	// event[0] 至少有 ModBoost stage record (damage.go 在 DealDamage 内调
	// recordStageModifier(ModBoost, ...) — 即使 hook 无修改,record 仍发生)。
	// modifier[0] 在 event[0] 的 base = modLogOffset + 0 * (K_mod * 5) = modLogOffset
	stage0Base := modLogOffset // event 0, modifier 0

	// kind == ModBoost (=0)
	gotKind := obs[stage0Base+0]
	if gotKind != int32(engine.ModBoost) {
		t.Errorf("event[0].mod[0].kind = %d, want ModBoost (%d)", gotKind, engine.ModBoost)
	}
	// value_before == 2 (raw damage)
	gotValBefore := obs[stage0Base+1]
	if gotValBefore != 2 {
		t.Errorf("event[0].mod[0].value_before = %d, want 2", gotValBefore)
	}
	// value_after == 2 (no boost hook fired)
	gotValAfter := obs[stage0Base+2]
	if gotValAfter != 2 {
		t.Errorf("event[0].mod[0].value_after = %d, want 2", gotValAfter)
	}
	// element_before/after == Physical (=8) (no element-changing hook)
	gotElemBefore := obs[stage0Base+3]
	gotElemAfter := obs[stage0Base+4]
	if gotElemBefore != int32(engine.ElemPhysical) {
		t.Errorf("event[0].mod[0].element_before = %d, want Physical", gotElemBefore)
	}
	if gotElemAfter != int32(engine.ElemPhysical) {
		t.Errorf("event[0].mod[0].element_after = %d, want Physical", gotElemAfter)
	}

	// modifier[1] / [2] / [3] 是 ModReaction / ModReduce / ModAfterDamage
	// (按 stage record 顺序)。Reaction stage 应记 ValueBefore=2 / ValueAfter=2
	// (Physical 不触发反应)。
	stage1Base := modLogOffset + fields // event 0, modifier 1
	gotKind1 := obs[stage1Base+0]
	if gotKind1 != int32(engine.ModReaction) {
		t.Errorf("event[0].mod[1].kind = %d, want ModReaction (%d)", gotKind1, engine.ModReaction)
	}

	// Test 3: event[1] 段(无第二个 damage)— padding sentinel 模式
	event1Base := modLogOffset + kMod*fields // 第二个 event 起点
	for j := 0; j < kMod; j++ {
		base := event1Base + j*fields
		for _, fi := range []int{0, 3, 4} {
			if obs[base+fi] != -2 {
				t.Errorf("event[1].mod[%d].field[%d] = %d, want -2 (padding)", j, fi, obs[base+fi])
			}
		}
		for _, fi := range []int{1, 2} {
			if obs[base+fi] != 0 {
				t.Errorf("event[1].mod[%d].field[%d] = %d, want 0 (scalar padding)", j, fi, obs[base+fi])
			}
		}
	}
}
