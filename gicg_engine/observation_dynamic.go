package engine

import (
	"fmt"
	"sort"
)

// BuildDynamicObs + counter grouping / perm helpers. The static obs
// (counter meta + hook tokens + skill refs) lives in observation.go.

// BuildDynamicObs creates the dynamic observation (each step).
// Layout: [Meta(3)][CounterValues: 1 per slot][HandCards]
func (g *Game) BuildDynamicObs(perspective int) []int32 {
	obs := make([]int32, DynamicObsSize())
	enemy := 1 - perspective
	offset := 0

	// Meta
	obs[0] = int32(g.Phase)
	obs[1] = int32(g.Round)
	if g.Turn == perspective {
		obs[2] = 1
	}
	offset = ObsMetaSize

	charCounters, playerCounters, globalCounters := g.groupCounters(perspective)

	writeValues := func(ids []int, maxSlots int) {
		n := len(ids)
		if n > maxSlots {
			n = maxSlots
		}
		for i := 0; i < n; i++ {
			obs[offset+i] = int32(g.Counters[ids[i]].Value)
		}
		offset += maxSlots
	}

	// Own chars
	for ci := 0; ci < ObsMaxChars; ci++ {
		writeValues(charCounters[perspective][ci], ObsCharSlots)
	}
	// Enemy chars
	for ci := 0; ci < ObsMaxChars; ci++ {
		writeValues(charCounters[enemy][ci], ObsCharSlots)
	}
	// Own player
	writeValues(playerCounters[perspective], ObsPlayerSlots)
	// Enemy player
	writeValues(playerCounters[enemy], ObsPlayerSlots)
	// Global
	writeValues(globalCounters, ObsGlobalSlots)

	// Hand cards — positions within each bucket are permuted by CardPerm
	// (reverseCardPerm maps raw card_ref → shuffled obs slot) so the
	// network can't memorize positional semantics the way it does with
	// CounterPerm/HookPerm.
	N := ObsMaxCardTypes
	ownP := &g.Players[perspective]
	enemyP := &g.Players[enemy]

	reverseCardPerm := g.buildReverseCardPerm()
	slotFor := func(ref int) int {
		if ref <= 0 || ref > N {
			return -1
		}
		return reverseCardPerm[ref-1]
	}

	for _, card := range ownP.Hand {
		if slot := slotFor(card.Ref); slot >= 0 {
			obs[offset+slot]++
		}
	}
	offset += N
	for _, card := range ownP.Deck {
		if slot := slotFor(card.Ref); slot >= 0 {
			obs[offset+slot]++
		}
	}
	offset += N
	for _, card := range ownP.Discard {
		if slot := slotFor(card.Ref); slot >= 0 {
			obs[offset+slot]++
		}
	}
	offset += N
	for _, card := range enemyP.Discard {
		if slot := slotFor(card.Ref); slot >= 0 {
			obs[offset+slot]++
		}
	}
	offset += N
	obs[offset] = int32(len(enemyP.Hand))
	obs[offset+1] = int32(len(enemyP.Deck))
	offset += 2

	// ADR-0019 §B.3c — typed damage event ring (K=8) + prepare-skill 编码。
	// Round-5 M1 修复:三个 encode 函数现在收 perspective,player_id 字段
	// 写 perspective-relative 值(0=self, 1=enemy, -1=no-actor real,
	// -2=padding),跟 obs 其它段(counter/hand/meta)的 perspective 转换
	// 一致。之前 typed 段写绝对 player_id,player_emb 在 P0/P1 视角训练
	// 样本下收到矛盾梯度。
	// recent_damage 段 (K × 11 fields):
	g.encodeRecentDamageEvents(obs, offset, perspective)
	offset += ObsRecentDamageSlots

	// prepare-skill 段 (2 player × (char_idx, skill_slot)):
	g.encodePrepareSkill(obs, offset, perspective)
	offset += ObsPrepareSkillSlots

	// ADR-0019 §B.2 — modifier log per-event 段 (K × K_mod × 5 fields):
	// modifier 字段不含 player_id,perspective 仅控 event 顺序的对齐(与
	// recent_damage 同序);modifier_log 内部 payload 不需要 perspective
	// 转换,但函数签名收 perspective 保 future-proof。
	g.encodeModifierLog(obs, offset, perspective)
	offset += ObsModifierLogSlots

	return obs
}

// relativePlayer — Round-5 M1: convert absolute player ID to perspective-
// relative ID. -2 = padding (caller fills before; this never converts);
// -1 = real "no actor" (DSL summon / 反射 path) preserved; 0/1 swapped
// to 0=self / 1=enemy when perspective=1.
//
// Round-6 S-4: panic on absPlayer ∉ {-1, 0, 1} per CLAUDE.md "意外输入
// 必须抛异常";原 silent-fall-through-to-1 是 dead defensive。
func relativePlayer(absPlayer, perspective int) int32 {
	if absPlayer == -1 {
		return -1
	}
	if absPlayer == 0 || absPlayer == 1 {
		if absPlayer == perspective {
			return 0
		}
		return 1
	}
	panic(fmt.Sprintf("relativePlayer: absPlayer=%d out of range {-1, 0, 1}", absPlayer))
}

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

func boolToInt32(b bool) int32 {
	if b {
		return 1
	}
	return 0
}

// buildReverseCardPerm inverts g.CardPerm so the observation writer can
// look up "what slot should I write card_ref R into" in O(1). When
// CardPerm is nil (e.g. tests that skip InitShuffle), it returns the
// identity map.
func (g *Game) buildReverseCardPerm() []int {
	rev := make([]int, ObsMaxCardTypes)
	for i := range rev {
		rev[i] = i
	}
	if g.CardPerm == nil {
		return rev
	}
	for shuffled, raw := range g.CardPerm {
		if raw >= 0 && raw < ObsMaxCardTypes {
			rev[raw] = shuffled
		}
	}
	return rev
}

func (g *Game) buildReversePerm() []int {
	n := len(g.Counters)
	rev := make([]int, n)
	for i := range rev {
		rev[i] = i
	}
	if g.CounterPerm != nil {
		for shuffled, raw := range g.CounterPerm {
			if raw < n {
				rev[raw] = shuffled
			}
		}
	}
	return rev
}

func (g *Game) groupCounters(perspective int) (
	charCounters [2][ObsMaxChars][]int,
	playerCounters [2][]int,
	globalCounters []int,
) {
	enemy := 1 - perspective

	for i := range g.Counters {
		id := i
		if g.counterCharMap != nil {
			if pair, ok := g.counterCharMap[id]; ok {
				p := pair[0]
				c := pair[1]
				if c >= 0 && c < ObsMaxChars {
					charCounters[p][c] = append(charCounters[p][c], id)
				} else if c == -1 {
					playerCounters[p] = append(playerCounters[p], id)
				} else {
					globalCounters = append(globalCounters, id)
				}
				continue
			}
		}
		globalCounters = append(globalCounters, id)
	}

	// Sort each bucket by shuffled sid (= position in CounterPerm).
	// With StructuralSids pinned to sids 0..K-1, this puts structural
	// counters (HP/energy/alive/active/dice/alive_count) at the FRONT
	// of each bucket — obs position 0 of bucket (p, c) is always the
	// HP slot for that char.
	rev := g.buildReversePerm()
	bySid := func(ids []int) {
		sort.SliceStable(ids, func(i, j int) bool {
			var si, sj int
			if ids[i] < len(rev) {
				si = rev[ids[i]]
			}
			if ids[j] < len(rev) {
				sj = rev[ids[j]]
			}
			return si < sj
		})
	}
	for p := 0; p < 2; p++ {
		for c := 0; c < ObsMaxChars; c++ {
			bySid(charCounters[p][c])
		}
		bySid(playerCounters[p])
	}
	bySid(globalCounters)

	_ = enemy
	return
}
