package tests

// 契约测试:事件栈空时解析 actor 视角 = 编程错误,MustCurrentEvent 必须
// panic(fail-loud)而非静默返回零值帧(Player=0)。零值帧的历史后果是
// run-150 回合末友伤 bug 类:无帧 dispatch 站点(on_before_turn_flip /
// on_action_check 等)的 DSL 若误调伤害类 builtin,效果全部以 P0 视角
// 结算。本文件锁 6 个消费点(DealDamage / Heal / GainEnergy /
// ConsumeEnergy / resolveTargetHP / invoke_skill)的空栈 panic 契约 +
// 2 条真环境 e2e(无帧 hook 内调 builtin → 显式崩溃)。
//
// 正向路径(有帧一切照旧)由现有 spike 测试 + round_end_actor_test.go
// + e2e 全量回归锁定,不在此重复。

import (
	"fmt"
	"strings"
	"testing"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// mustPanicContains 执行 fn,断言其 panic 且 panic 消息含 want。
func mustPanicContains(t *testing.T, want string, fn func()) {
	t.Helper()
	defer func() {
		t.Helper()
		r := recover()
		if r == nil {
			t.Fatalf("expected panic containing %q, got normal return", want)
		}
		msg := fmt.Sprint(r)
		if !strings.Contains(msg, want) {
			t.Errorf("panic message %q does not contain %q", msg, want)
		}
	}()
	fn()
}

// --- helper 本体契约 ---

func TestMustCurrentEvent_EmptyStack_Panics(t *testing.T) {
	g := &engine.Game{}
	mustPanicContains(t, "probe_site", func() {
		g.MustCurrentEvent("probe_site")
	})
}

func TestMustCurrentEvent_Framed_ReturnsTop(t *testing.T) {
	g := &engine.Game{}
	g.PushEvent(engine.EventFrame{Player: 1, Char: 2, ActionCtx: engine.ActUseSkill})
	defer g.PopEvent()
	frame := g.MustCurrentEvent("probe_site")
	if frame.Player != 1 || frame.Char != 2 || frame.ActionCtx != engine.ActUseSkill {
		t.Errorf("frame = %+v, want Player=1 Char=2 ActionCtx=ActUseSkill", frame)
	}
}

// --- 引擎管道消费点(空栈直接调用) ---

func TestDealDamage_EmptyStack_Panics(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	hpID := env.RT.Chars.BySlot[1][0].HPCounterID
	mustPanicContains(t, "DealDamage", func() {
		env.G.DealDamage(hpID, engine.ElemPhysical, 1, engine.DamageOpts{
			ActorPlayer: -1, ActorChar: -1,
		})
	})
}

// opts 全量指定 actor + source 仍 panic:覆盖语义作用于已存在的帧之上,
// 不豁免压帧契约。
func TestDealDamage_EmptyStack_ExplicitOpts_StillPanics(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	hpID := env.RT.Chars.BySlot[1][0].HPCounterID
	mustPanicContains(t, "DealDamage", func() {
		env.G.DealDamage(hpID, engine.ElemPhysical, 1, engine.DamageOpts{
			Source: engine.SrcSkill, ActorPlayer: 0, ActorChar: 0,
		})
	})
}

func TestHeal_EmptyStack_Panics(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	hpID := env.RT.Chars.BySlot[0][0].HPCounterID
	mustPanicContains(t, "Heal", func() {
		env.G.Heal(hpID, 1)
	})
}

func TestGainEnergy_EmptyStack_Panics(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	energyID := env.RT.Chars.BySlot[0][0].EnergyCounterID
	mustPanicContains(t, "GainEnergy", func() {
		env.G.GainEnergy(energyID, 1)
	})
}

func TestConsumeEnergy_EmptyStack_Panics(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})
	energyID := env.RT.Chars.BySlot[0][0].EnergyCounterID
	mustPanicContains(t, "ConsumeEnergy", func() {
		env.G.ConsumeEnergy(energyID, 1)
	})
}

// --- 真环境 e2e:无帧 dispatch 站点内误调 builtin ---

// on_before_turn_flip 在 PopEvent 之后 fire(action_execute.go),栈空。
// DSL 在其中调 deal_damage 是 bug 类:修复前静默以 P0 视角结算(友伤),
// 修复后在 resolveTargetHP 消费端显式 panic。
func TestFramelessHook_DealDamage_Panics(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})

	src := `
on_before_turn_flip(function(ctx)
  deal_damage(Target.EnemyActive, Element.Physical, 1)
end)
`
	lenv := interp.NewEnv(env.RT.Interp.Global)
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src), lenv); err != nil {
		t.Fatalf("register before_turn_flip hook: %v", err)
	}

	// P0 用技能(battle action;end_turn 不触发 flip hook)
	env.SetDice(0, map[int]int{int(engine.DiceColorFire): 8})
	mustPanicContains(t, "resolveTargetHP", func() {
		if !env.StepSkill("枪") {
			t.Fatal("枪 not offered")
		}
	})
}

// 同上,invoke_skill 路径:invokeSkillCommon 取 CurrentEvent 种子新帧,
// 空栈必须 panic 而非以 P0/char0 视角发动技能。
func TestFramelessHook_InvokeSkill_Panics(t *testing.T) {
	env := NewGame(t, []string{"赤蝶"}, []string{"墨客"})

	src := `
on_before_turn_flip(function(ctx)
  invoke_skill(0)
end)
`
	lenv := interp.NewEnv(env.RT.Interp.Global)
	if err := env.RT.Interp.ExecFile(env.RT, []byte(src), lenv); err != nil {
		t.Fatalf("register before_turn_flip hook: %v", err)
	}

	env.SetDice(0, map[int]int{int(engine.DiceColorFire): 8})
	mustPanicContains(t, "invoke_skill", func() {
		if !env.StepSkill("枪") {
			t.Fatal("枪 not offered")
		}
	})
}
