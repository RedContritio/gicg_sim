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
	g.RequireHealthy()
	obs := make([]int32, DynamicObsSize())
	refKinds := g.observationReferenceKinds()
	enemy := 1 - perspective
	offset := 0

	g.writePublicMeta(obs, perspective)
	offset = ObsMetaSize

	charCounters, playerCounters, globalCounters := g.groupCounters(0)

	writeValues := func(ids []int, maxSlots int) {
		n := len(ids)
		if n > maxSlots {
			panic(fmt.Sprintf("counter observation capacity exceeded: %d > %d", n, maxSlots))
		}
		for i := 0; i < n; i++ {
			obs[offset+i] = int32(g.Counters[ids[i]].Value)
			if refKinds[ids[i]] != 0 {
				obs[offset+i] = referencePresence(g.Counters[ids[i]].Value)
			}
		}
		offset += maxSlots
	}

	// Counter slots always match the static P0/P1 layout, regardless of observer.
	// P0 chars
	for ci := 0; ci < ObsMaxChars; ci++ {
		writeValues(charCounters[0][ci], ObsCharSlots)
	}
	// P1 chars
	for ci := 0; ci < ObsMaxChars; ci++ {
		writeValues(charCounters[1][ci], ObsCharSlots)
	}
	// P0 player
	writeValues(playerCounters[0], ObsPlayerSlots)
	// P1 player
	writeValues(playerCounters[1], ObsPlayerSlots)
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
	row := g.writeBuffObs(obs[offset:offset+ObsBuffSlots], perspective)
	g.writeEntityObs(obs[offset:offset+ObsBuffSlots], perspective, row, refKinds)

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
