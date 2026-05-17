package engine

// Observation layout constants + BuildStaticObs (counter meta +
// char-skill refs + hook tokens, computed once per episode).
// BuildDynamicObs and grouping helpers live in observation_dynamic.go.

// Slot size constants — derived from theoretical max × 1.5
const (
	ObsMaxChars         = 6   // max chars per player
	ObsCharSlots        = 128 // per char: (30 Self + 54 PerChar) × 1.5
	ObsMaxSkillsPerChar = 10  // per char: up to 10 native on_skill_use refs
	ObsPlayerSlots      = 140 // per player: 92 PerPlayer × 1.5
	ObsGlobalSlots      = 16  // global counters
	ObsMaxCardTypes     = 80  // card types × 1.5
	ObsMaxHooks         = 900 // (6 chars × 6 skills + 30 cards) × 9 hooks/file × 1.5
	ObsMaxTokensPerHook = 120 // 80 max observed × 1.5
	ObsMetaSize         = 3   // phase, round, is_my_turn

	// ADR-0019 §B.3c — RL obs typed damage + prepare-skill 段。
	// 修 P0-3 黑盒(reaction kind / shield absorbed / element transition 进 obs)
	// + P0-γ / P1-8(prepare-skill obs typed encode 不暴露 global skillID)。
	//
	// ObsRecentDamageEvents: ring buffer 上界 K=8 events (engine MaxRecentDamageEvents);
	// 每 event 编码 11 typed fields:
	//   actor_player / actor_char / target_player / target_char / element /
	//   raw_value / final_value / absorbed / is_piercing / is_hit / reaction_kind
	ObsRecentDamageEvents     = 8
	ObsRecentDamageFieldCount = 11
	ObsRecentDamageSlots      = ObsRecentDamageEvents * ObsRecentDamageFieldCount // 88

	// ObsPrepareSkillSlots: 2 玩家 × (char_idx, skill_slot) = 4 slots
	// (-1, -1) 表无 prepare;否则 (active_char ∈ [0, ObsMaxChars), skill_slot ∈ [0,4))
	ObsPrepareSkillSlots = 2 * 2 // 4

	// ADR-0019 §B.2 — typed Modifier log obs encoding。
	// 每 RecentDamageEvent 对应一段 K_mod 个 modifier 槽 × 5 typed fields:
	//   kind / value_before / value_after / element_before / element_after
	// K_mod=4 对应当前 stage-level (Boost/Reaction/Reduce/AfterDamage 4 stage);
	// 后续 per-hook 细分 (Type/Add/Mul + ReduceBuff/Shield/Immunity) 可
	// 提升 K_mod 不需重排其它段;对超过 K_mod 的 modifier sequence 截断。
	// 与 RecentDamage 段并排 (同 K=8 索引),让网络可关联 event ↔ modifier
	// sequence。无 modifier 的槽 padding 0。
	ObsModifierLogKMod       = 4
	ObsModifierLogFieldCount = 5
	ObsModifierLogSlots      = ObsRecentDamageEvents * ObsModifierLogKMod * ObsModifierLogFieldCount // 160
)

// ObsCharElementSlots: per (player, char_slot) one int32 holding the
// Element enum value for that char (ElemNone..ElemPhysical, 0..8). The
// network uses these as integer IDs into a shared element embedding
// table so char element, dice color, skill damage element, card effect
// element, and attach element can all use the same learned vectors.
// Phantom (unbound) slots store -1; network handles as "no char".
const ObsCharElementSlots = 2 * ObsMaxChars // 12

// Counter slots total (same layout for static and dynamic)
func obsCounterSlots() int {
	return 2*ObsMaxChars*ObsCharSlots + 2*ObsPlayerSlots + ObsGlobalSlots
}

// StaticObsSize: counter metadata + char-skill refs + hook tokens +
// char element IDs (computed once per episode).
func StaticObsSize() int {
	counterMeta := obsCounterSlots() * 3 // (min, max, sid) per slot
	charSkillRefs := 2 * ObsMaxChars * ObsMaxSkillsPerChar
	hookTokens := ObsMaxHooks * ObsMaxTokensPerHook * 2
	return counterMeta + charSkillRefs + hookTokens + ObsCharElementSlots
}

// DynamicObsSize: counter values + hand cards + meta + recent damage +
// prepare-skill + modifier log (computed each step). ADR-0019 §B.3c +
// §B.2 加 typed damage / prepare / modifier-log 段。
func DynamicObsSize() int {
	counterValues := obsCounterSlots() // 1 value per slot
	handBlock := 4*ObsMaxCardTypes + 2
	return ObsMetaSize + counterValues + handBlock +
		ObsRecentDamageSlots + ObsPrepareSkillSlots + ObsModifierLogSlots
}

// ActiveCounterSlotLabels returns one label per observation counter slot,
// in the same order BuildStaticObs/BuildDynamicObs writes them:
//
//   P0 chars 0..5 × ObsCharSlots,
//   P1 chars 0..5 × ObsCharSlots,
//   P0 player  × ObsPlayerSlots,
//   P1 player  × ObsPlayerSlots,
//   global     × ObsGlobalSlots.
//
// Active counters (those grouped into that slot by groupCounters) get a
// semantic label like "P0:c0:赤蝶:生命"; padding slots get an empty string.
// The visualizer uses this to translate slot indices back into counter
// semantics ("HP", "energy", "蝶火_active", …) rather than just the group.

// Label helpers for obs slots (names + readable hook descriptions)
// live in obs_labels.go.

func (g *Game) BuildStaticObs() []int32 {
	obs := make([]int32, StaticObsSize())
	offset := 0

	reversePerm := g.buildReversePerm()

	writeCounterMeta := func(ids []int, maxSlots int) {
		n := len(ids)
		if n > maxSlots {
			n = maxSlots
		}
		for i := 0; i < n; i++ {
			c := &g.Counters[ids[i]]
			obs[offset] = int32(c.Min)
			obs[offset+1] = int32(c.Max)
			obs[offset+2] = int32(reversePerm[ids[i]])
			offset += 3
		}
		offset += (maxSlots - n) * 3
	}

	// Group by char/player/global (perspective 0 = canonical ordering)
	charCounters, playerCounters, globalCounters := g.groupCounters(0)

	for ci := 0; ci < ObsMaxChars; ci++ {
		writeCounterMeta(charCounters[0][ci], ObsCharSlots)
	}
	for ci := 0; ci < ObsMaxChars; ci++ {
		writeCounterMeta(charCounters[1][ci], ObsCharSlots)
	}
	writeCounterMeta(playerCounters[0], ObsPlayerSlots)
	writeCounterMeta(playerCounters[1], ObsPlayerSlots)
	writeCounterMeta(globalCounters, ObsGlobalSlots)

	// Char skill refs: per (player, char, skill_slot) the canonical
	// on_skill_use hook's active hook index (post-filter), or -1 if empty.
	// Position (p, c) encodes owner explicitly. Within (p, c), the
	// physical skill slot s is mapped to a logical SkillIDs index via
	// SkillSlotPerm[p][c][s] — independent shuffle per (p, c) to prevent
	// the network from memorizing "slot 0 = 普攻" across games. Gather
	// target is the same canonical hook the pointer-net policy head uses
	// for action embedding (GameGetActionRefs), so on-policy and
	// off-policy embeddings align.
	if g.Obs.IncludeCharSkillRefs {
		rawToActive := g.BuildRawToActiveHookIdx()
		for pi := 0; pi < 2; pi++ {
			for ci := 0; ci < ObsMaxChars; ci++ {
				var skills []int
				if ci < len(g.Players[pi].Chars) {
					skills = g.Players[pi].Chars[ci].Skills
				}
				for si := 0; si < ObsMaxSkillsPerChar; si++ {
					logicalIdx := si
					if g.SkillSlotPerm != nil {
						logicalIdx = g.SkillSlotPerm[pi][ci][si]
					}
					v := int32(-1)
					if logicalIdx < len(skills) {
						skillID := skills[logicalIdx]
						if rawID, ok := g.CanonicalSkillHooks[[3]int{pi, ci, skillID}]; ok {
							if ai, ok2 := rawToActive[rawID]; ok2 {
								v = int32(ai)
							}
						}
					}
					obs[offset] = v
					offset++
				}
			}
		}
	} else {
		// Region still reserved (so StaticObsSize stays stable) — fill
		// with -1 so the network sees "no skill info" uniformly.
		n := 2 * ObsMaxChars * ObsMaxSkillsPerChar
		for i := 0; i < n; i++ {
			obs[offset] = -1
			offset++
		}
	}

	// Hook tokens
	allHooks := g.Hooks.AllHooks()
	for hi := 0; hi < ObsMaxHooks; hi++ {
		src := hi
		if g.HookPerm != nil && hi < len(g.HookPerm) {
			src = g.HookPerm[hi]
		}
		if src < len(allHooks) {
			hook := allHooks[src]
			if hook.Tokens != nil {
				nTok := len(hook.Tokens)
				if nTok > ObsMaxTokensPerHook {
					nTok = ObsMaxTokensPerHook
				}
				for ti := 0; ti < nTok; ti++ {
					obs[offset+ti*2] = int32(hook.Tokens[ti].Type)
					obs[offset+ti*2+1] = int32(hook.Tokens[ti].Value)
				}
			}
		}
		offset += ObsMaxTokensPerHook * 2
	}

	// Char element IDs: per (player, char slot) the Element enum value
	// (ElemNone..ElemPhysical, 0..8), or -1 for unbound phantom slots.
	// Iteration order (P0 c0..c5, P1 c0..c5) matches the counter-meta
	// per-char block order so a network consumer can pair element ID
	// with counter/skill info by char index without a separate lookup.
	// Position is NOT permuted — char slots themselves are the owner
	// identity already visible to the policy head (GameGetActionRefs
	// returns char_idx for switches), so hiding the slot order here
	// would only obfuscate info the agent already has.
	for pi := 0; pi < 2; pi++ {
		for ci := 0; ci < ObsMaxChars; ci++ {
			v := int32(-1)
			if ci < len(g.Players[pi].Chars) {
				v = int32(g.Players[pi].Chars[ci].Element)
			}
			obs[offset] = v
			offset++
		}
	}

	return obs
}
