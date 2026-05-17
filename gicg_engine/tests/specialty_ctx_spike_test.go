package tests

// TestIsSpecialtyCtxSpike — ADR-0019 §A.1 spike。
// 验证 invoke_skill_silent 调用时 ctx.IsSpecialty=true,
// invoke_skill 调用时 ctx.IsSpecialty=false,且 DSL 通过
// ctx.is_specialty 字段能读到该值。
//
// 见 dsl_gaps.md §C.3:invokeSkillCommon silent=true 自动设
// IsSpecialty=true (DSL 显式 invoke_skill_silent 即"这是特技");
// engine 内部 prepare-skill resolve 路径走 ResolvePreparing,
// 不通过 invokeSkillCommon,IsSpecialty 默认 false。

import (
	"fmt"
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestIsSpecialtyCtxSpike(t *testing.T) {
	// 歼灭机关 已知 skill 全 declare(prepare_skill_spike 实证)
	env := NewGameWithDeck(t, []string{"歼灭机关"}, []string{"歼灭机关"})
	g := env.G

	// 找"高频旋击"作为目标 skill
	var skillID int
	for id, sk := range env.RT.Skills.ByID {
		if sk.Name == "高频旋击" {
			skillID = id
			break
		}
	}
	if skillID == 0 {
		t.Fatalf("高频旋击 not loaded; skills=%d", len(env.RT.Skills.ByID))
	}

	// Go-level hook 捕获 ctx.IsSpecialty
	type capture struct {
		isSpecialty bool
	}
	var captures []capture
	g.Hooks.Register(engine.Hook{
		Type:     engine.HookSkillUse,
		Priority: 1000,
		Fn: func(_ *engine.Game, ctx *engine.EventContext) {
			captures = append(captures, capture{isSpecialty: ctx.IsSpecialty})
		},
	})

	// invokeSkillCommon 内部用 g.CurrentEvent() 继承 actor;push 一帧。
	g.PushEvent(engine.EventFrame{
		ActionCtx: engine.ActUseSkill,
		Player:    0,
		Char:      0,
	})
	defer g.PopEvent()

	env_lua := env.RT.Interp.Global

	// Test 1: invoke_skill_silent → IsSpecialty=true
	src1 := fmt.Sprintf("invoke_skill_silent(%d)", skillID)
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src1), env_lua); err != nil {
		t.Fatalf("invoke_skill_silent exec: %v", err)
	}

	// Test 2: invoke_skill → IsSpecialty=false
	src2 := fmt.Sprintf("invoke_skill(%d)", skillID)
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src2), env_lua); err != nil {
		t.Fatalf("invoke_skill exec: %v", err)
	}

	if len(captures) < 2 {
		t.Fatalf("expected ≥2 hook fires, got %d: %+v", len(captures), captures)
	}

	silentCap := captures[0]
	normalCap := captures[len(captures)-1]

	if !silentCap.isSpecialty {
		t.Errorf("invoke_skill_silent: ctx.IsSpecialty=false, want true")
	}
	if normalCap.isSpecialty {
		t.Errorf("invoke_skill: ctx.IsSpecialty=true, want false")
	}
}
