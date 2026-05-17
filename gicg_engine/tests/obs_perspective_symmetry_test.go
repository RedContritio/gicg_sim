package tests

// TestObsPerspectiveSymmetry — Round-5 review S4。
//
// 验证 ADR-0019 §B.2/§B.3c typed obs 段的 perspective 转换对称性:
//   - 同一 game state, BuildDynamicObs(perspective=0) vs (perspective=1)
//     的 typed 段必须做相应 player_id swap (0 = self, 1 = enemy)
//   - prepare_skill[0] 始终是 own player 的 prepare,prepare_skill[1]
//     是 enemy 的;P0 / P1 视角下两个 slot 索引到的 absolute player
//     刚好相反
//
// Round 1-4 review 全部错过 perspective 不对称问题(Round-5 M1)的
// 根因是没有这种测试。把对称性变成显式 invariant。

import (
	"testing"

	engine "gicg_mono/gicg_engine"
)

func TestObsPerspectiveSymmetry_RecentDamage(t *testing.T) {
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	// 触发 1 个 P0 → P1 的 damage
	p1HpID := env.RT.Chars.BySlot[1][0].HPCounterID
	g.PushEvent(engine.EventFrame{Player: 0, Char: 0, ActionCtx: engine.ActUseSkill})
	g.DealDamage(p1HpID, engine.ElemPhysical, 2, engine.DamageOpts{
		ActorPlayer: 0, ActorChar: 0,
	})
	g.PopEvent()

	// 同 game state 取两个 perspective 的 obs
	obsP0 := g.BuildDynamicObs(0)
	obsP1 := g.BuildDynamicObs(1)

	// recent_damage 段 offset:dyn obs 末尾去掉 modifier_log + prepare_skill 的位置
	rdOffset := engine.DynamicObsSize() -
		engine.ObsModifierLogSlots -
		engine.ObsPrepareSkillSlots -
		engine.ObsRecentDamageSlots

	// event[0] 字段索引: 0=actor_player, 2=target_player
	// P0 视角:actor=P0=self(rel=0), target=P1=enemy(rel=1)
	if got := obsP0[rdOffset+0]; got != 0 {
		t.Errorf("P0 视角 actor_player should be 0 (self), got %d", got)
	}
	if got := obsP0[rdOffset+2]; got != 1 {
		t.Errorf("P0 视角 target_player should be 1 (enemy), got %d", got)
	}
	// P1 视角:actor=P0=enemy(rel=1), target=P1=self(rel=0)
	if got := obsP1[rdOffset+0]; got != 1 {
		t.Errorf("P1 视角 actor_player should be 1 (enemy of P1), got %d", got)
	}
	if got := obsP1[rdOffset+2]; got != 0 {
		t.Errorf("P1 视角 target_player should be 0 (self of P1), got %d", got)
	}

	// char_idx (字段 1, 3) 是 player-内部索引,无 perspective 概念;P0/P1
	// 视角下保持原值。
	if obsP0[rdOffset+1] != obsP1[rdOffset+1] {
		t.Errorf("actor_char should be perspective-invariant: P0=%d P1=%d",
			obsP0[rdOffset+1], obsP1[rdOffset+1])
	}
	if obsP0[rdOffset+3] != obsP1[rdOffset+3] {
		t.Errorf("target_char should be perspective-invariant: P0=%d P1=%d",
			obsP0[rdOffset+3], obsP1[rdOffset+3])
	}

	// scalar 字段(5..9)对 perspective 不变(raw / final / absorbed / is_*)。
	for fi := 5; fi <= 9; fi++ {
		if obsP0[rdOffset+fi] != obsP1[rdOffset+fi] {
			t.Errorf("recent_damage scalar field %d should be perspective-invariant: P0=%d P1=%d",
				fi, obsP0[rdOffset+fi], obsP1[rdOffset+fi])
		}
	}
}

func TestObsPerspectiveSymmetry_PrepareSkill(t *testing.T) {
	env := NewGameWithDeck(t, []string{"歼灭机关"}, []string{"歼灭机关"})
	g := env.G

	// 找一个 skillID,只 set Preparing[0],不 set Preparing[1]
	var skillID int
	for id, sk := range env.RT.Skills.ByID {
		if sk.Name == "高频旋击" {
			skillID = id
			break
		}
	}
	if skillID == 0 {
		t.Skip("高频旋击 skill not loaded")
	}
	g.Preparing[0] = skillID
	g.Preparing[1] = 0 // P1 没 prepare

	obsP0 := g.BuildDynamicObs(0)
	obsP1 := g.BuildDynamicObs(1)

	psOffset := engine.DynamicObsSize() -
		engine.ObsModifierLogSlots -
		engine.ObsPrepareSkillSlots

	// prepare_skill[0] = own (perspective), prepare_skill[1] = enemy
	// P0 视角:own = P0(在 prepare),enemy = P1(无 prepare)
	if obsP0[psOffset+0] < 0 || obsP0[psOffset+1] < 0 {
		t.Errorf("P0 视角 prepare_skill[own] 应是 P0 的 prepare(non-negative char/slot), got (%d, %d)",
			obsP0[psOffset+0], obsP0[psOffset+1])
	}
	if obsP0[psOffset+2] != -1 || obsP0[psOffset+3] != -1 {
		t.Errorf("P0 视角 prepare_skill[enemy] 应是 (-1, -1) (P1 无 prepare), got (%d, %d)",
			obsP0[psOffset+2], obsP0[psOffset+3])
	}
	// P1 视角:own = P1(无 prepare),enemy = P0(在 prepare)
	if obsP1[psOffset+0] != -1 || obsP1[psOffset+1] != -1 {
		t.Errorf("P1 视角 prepare_skill[own] 应是 (-1, -1) (P1 无 prepare), got (%d, %d)",
			obsP1[psOffset+0], obsP1[psOffset+1])
	}
	if obsP1[psOffset+2] < 0 || obsP1[psOffset+3] < 0 {
		t.Errorf("P1 视角 prepare_skill[enemy] 应是 P0 的 prepare(non-negative), got (%d, %d)",
			obsP1[psOffset+2], obsP1[psOffset+3])
	}

	// 镜像对称性:P0 视角的 own == P1 视角的 enemy(同一 prepare 真值)
	if obsP0[psOffset+0] != obsP1[psOffset+2] {
		t.Errorf("perspective swap: P0_own_char(%d) != P1_enemy_char(%d)",
			obsP0[psOffset+0], obsP1[psOffset+2])
	}
	if obsP0[psOffset+1] != obsP1[psOffset+3] {
		t.Errorf("perspective swap: P0_own_slot(%d) != P1_enemy_slot(%d)",
			obsP0[psOffset+1], obsP1[psOffset+3])
	}
}

func TestObsPerspectiveSymmetry_PaddingUnchanged(t *testing.T) {
	// 无 damage / 无 prepare 时,两个视角的 typed 段全 padding,字段值
	// 应完全相同(padding sentinel 不依赖 perspective)。
	env := NewGameWithDeck(t, []string{"赤蝶"}, []string{"墨客"})
	g := env.G

	obsP0 := g.BuildDynamicObs(0)
	obsP1 := g.BuildDynamicObs(1)

	// recent_damage + modifier_log padding 段
	rdOffset := engine.DynamicObsSize() -
		engine.ObsModifierLogSlots -
		engine.ObsPrepareSkillSlots -
		engine.ObsRecentDamageSlots
	rdEnd := rdOffset + engine.ObsRecentDamageSlots
	for i := rdOffset; i < rdEnd; i++ {
		if obsP0[i] != obsP1[i] {
			t.Errorf("recent_damage padding[%d]: P0=%d P1=%d (should be perspective-invariant when all events are padding)",
				i-rdOffset, obsP0[i], obsP1[i])
			return
		}
	}
	mlOffset := engine.DynamicObsSize() - engine.ObsModifierLogSlots
	for i := mlOffset; i < engine.DynamicObsSize(); i++ {
		if obsP0[i] != obsP1[i] {
			t.Errorf("modifier_log padding[%d]: P0=%d P1=%d", i-mlOffset, obsP0[i], obsP1[i])
			return
		}
	}
}
