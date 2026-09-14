package engine

// encodeRecentDamageEvents — ADR-0019 §B.3c 写 K=8 event × 11 typed fields。
// 不足 K event 时尾部 padding 写 -2 sentinel for categorical fields
// (player / char / element / reaction_kind);scalar 字段保 0
// (raw / final / absorbed / is_piercing / is_hit)。
//
// Round-5 M1 修复:player_id 字段(0=actor_player, 2=target_player)写
// perspective-relative 值(0=self, 1=enemy),与 obs 其它段(counter
// /hand/meta)的 perspective 转换一致。char_idx 字段(1/3)是 player-
// 内部 slot 索引,无 perspective 概念,直接写 e.ActorChar/TargetChar。
//
// Round-3 review M3+M4 修复(回顾):-2 padding sentinel + DSL 真值 -1
// "no-actor" 由 encoder _safe_*(idx+2) 区分到不同 vocab slot。
//
// 字段顺序对齐 BuildDynamicObs 注释。
func (g *Game) encodeRecentDamageEvents(obs []int32, offset, perspective int) {
	const fields = ObsRecentDamageFieldCount
	// 先把整段 categorical 槽刷 -2(scalar 槽留 0,zero-init 自动满足)
	for i := 0; i < ObsRecentDamageEvents; i++ {
		base := offset + i*fields
		obs[base+0] = -2  // actor_player (padding sentinel; -1 = real no-actor)
		obs[base+1] = -2  // actor_char
		obs[base+2] = -2  // target_player
		obs[base+3] = -2  // target_char
		obs[base+4] = -2  // element (Element 真值 0..9;-1 unused 但 vocab 留位)
		obs[base+10] = -2 // reaction_kind (真值 0..N;-1 unused)
		// scalar 字段(5/6/7/8/9)保 0
	}
	for i, e := range g.RecentDamageEvents {
		if i >= ObsRecentDamageEvents {
			break
		}
		base := offset + i*fields
		// Round-5 M1: perspective-relative player IDs
		obs[base+0] = relativePlayer(e.ActorPlayer, perspective)
		obs[base+1] = int32(e.ActorChar)
		obs[base+2] = relativePlayer(e.TargetPlayer, perspective)
		obs[base+3] = int32(e.TargetChar)
		obs[base+4] = int32(e.Element)
		obs[base+5] = int32(e.RawValue)
		obs[base+6] = int32(e.FinalValue)
		obs[base+7] = int32(e.Absorbed)
		obs[base+8] = boolToInt32(e.IsPiercing)
		obs[base+9] = boolToInt32(e.IsHit)
		obs[base+10] = int32(e.ReactionKind)
	}
}

// encodePrepareSkill — ADR-0019 §B.3c 写每方 (char_idx, skill_slot) typed pair。
// 通过 game.Extra (interp.Runtime).SkillIdentityOf 反查 Game.Preparing[player]
// 得 typed pair;未 prepare 或反查失败时写 (-1, -1)。
//
// Round-5 M1 修复:输出按 perspective-relative 顺序排列 — slot 0 始终
// 是 own player(perspective)的 prepare,slot 1 是 enemy。之前按绝对
// player 索引(P0 永远在 slot 0)在 P1 视角样本下让网络看到"我的
// prepare 在 slot 1"语义混乱。
//
// game.Extra 是 any 类型,通过接口 method 调用避免循环 import。Game 不直接
// 知道 Runtime,Runtime 实现 SkillIdentityResolver 接口供 obs encoder 调。
func (g *Game) encodePrepareSkill(obs []int32, offset, perspective int) {
	resolver, _ := g.Extra.(SkillIdentityResolver)
	enemy := 1 - perspective
	playerOrder := [2]int{perspective, enemy}
	for relIdx, absPlayer := range playerOrder {
		base := offset + relIdx*2
		obs[base+0] = -1
		obs[base+1] = -1
		skillID := g.Preparing[absPlayer]
		if skillID == 0 || resolver == nil {
			continue
		}
		if charIdx, slot, ok := resolver.SkillIdentityOf(absPlayer, skillID); ok {
			obs[base+0] = int32(charIdx)
			obs[base+1] = int32(slot)
		}
	}
}

// encodeModifierLog — ADR-0019 §B.2 写每 RecentDamageEvent 的 modifier
// snapshot,K=8 events × K_mod=4 stages × 5 fields。每 modifier 的 5 fields:
// kind / value_before / value_after / element_before / element_after。
//
// 与 RecentDamageEvent 同步索引(同 K=8 顺序),让网络可关联 event[i]
// ↔ modifier_log[i]。modifier 数超 K_mod 时截断 (per-stage 实施只 emit
// 4 个,不会超);不足时 padding 用 -2 sentinel for categorical (kind /
// element_before / element_after),scalar 字段(value_before/after)保 0。
//
// Round-3 review M3 修复:同 encodeRecentDamageEvents,-2 sentinel 跟真
// 值 0 (ModBoost / ElemNone) 不撞车;encoder 用 +2 offset 区分 padding
// (vocab idx 0) vs 真值 (vocab idx 2..)。
//
// Round-5 M1: modifier 字段无 player_id,perspective 仅控 event 顺序
// 跟 recent_damage 对齐(参见 encodeRecentDamageEvents);本函数不需
// 转换 payload,但收 perspective 保 future-proof + signature 一致。
func (g *Game) encodeModifierLog(obs []int32, offset, perspective int) {
	_ = perspective // event 顺序已由 RecentDamageEvents 决定;modifier payload 无 player_id
	const fields = ObsModifierLogFieldCount
	const kMod = ObsModifierLogKMod
	// 先刷 -2 sentinel for categorical(kind / element_before / element_after);
	// scalar(value_before / value_after)保 0。
	for i := 0; i < ObsRecentDamageEvents; i++ {
		eventBase := offset + i*kMod*fields
		for j := 0; j < kMod; j++ {
			base := eventBase + j*fields
			obs[base+0] = -2 // kind (padding; 真值 ModBoost..ModAfterDamage = 0..3)
			obs[base+3] = -2 // element_before
			obs[base+4] = -2 // element_after
			// value_before(1) / value_after(2) 保 0
		}
	}
	for i, e := range g.RecentDamageEvents {
		if i >= ObsRecentDamageEvents {
			break
		}
		eventBase := offset + i*kMod*fields
		for j, m := range e.Modifiers {
			if j >= kMod {
				break
			}
			base := eventBase + j*fields
			obs[base+0] = int32(m.Kind)
			obs[base+1] = int32(m.ValueBefore)
			obs[base+2] = int32(m.ValueAfter)
			obs[base+3] = int32(m.ElementBefore)
			obs[base+4] = int32(m.ElementAfter)
		}
	}
}
