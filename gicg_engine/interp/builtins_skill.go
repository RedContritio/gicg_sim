package interp

import (
	"fmt"

	engine "gicg_mono/gicg_engine"
)

// Skill-family builtins: declare_skill, get_skill, invoke_skill.
// registerSkillHooks lives in the same file so the skill declaration
// closure and the engine-side canonical hook share one edit context.

func (rt *Runtime) builtinDeclareSkill(args []Value) (Value, error) {
	charProxy, _ := args[0].(*CharProxy)
	skillName, _ := args[1].(string)

	// New signature: declare_skill(char, name, cost_table, opts?)
	// cost_table = { dices = { fire = N, match = M, any = K, ... }, energy = N }
	// opts = { normal_attack = bool, ... } (forward-compat, unused today)
	var cost engine.Cost
	if len(args) > 2 && args[2] != nil {
		if t, ok := args[2].(*Table); ok {
			cost = parseCost(t)
		}
	}

	// Resolve the canonical template by name. charProxy.Entry can be either
	// the template (when called from a char file before any binding) or a
	// per-slot CharEntry (when called via per-binding skill file loading);
	// the template is what stores the global skill ID dictionary.
	charName := charProxy.Entry.Name
	template := rt.Chars.ByName[charName]
	if template == nil {
		return nil, fmt.Errorf("declare_skill: char %q not declared", charName)
	}

	// Get or create the global skill ID. Skill IDs are shared across
	// bindings of the same char — same name = same ID = same effect.
	var skillID int
	if id, ok := template.Skills[skillName]; ok {
		skillID = id
	} else {
		skillID = rt.Skills.NextID
		rt.Skills.NextID++
		ref := &SkillRef{
			ID:       skillID,
			Name:     skillName,
			CharName: charName,
			Cost:     cost,
		}
		rt.Skills.ByID[skillID] = ref
		template.Skills[skillName] = skillID
		template.SkillIDs = append(template.SkillIDs, skillID)
		// Identify "normal attack" by the any > 0 cost pattern. In
		// GI TCG, normal attacks cost 1 element + 2 any; elemental
		// skills and bursts are pure specific. First skill matching
		// wins; subsequent same-pattern skills are ignored.
		if template.NormalAttackID < 0 && cost.Dices.Any > 0 {
			template.NormalAttackID = skillID
		}
		if rt.Game.SkillNames == nil {
			rt.Game.SkillNames = make(map[int]string)
		}
		rt.Game.SkillNames[skillID] = skillName
	}

	// Per-slot attachment: when loaded under a binding context, attach the
	// skill to that specific slot (so GetLegalActions includes it for that
	// player) and register player-filtered energy hooks for it. Slots keep
	// their own Skills map so re-loads under a different owner ctx produce
	// a fresh registration without double-registering for the same slot.
	pi := rt.CurrentOwnerPlayer
	ci := rt.CurrentOwnerChar
	if pi >= 0 && ci >= 0 {
		slot := rt.Chars.BySlot[pi][ci]
		if slot != nil && slot.Name == charName {
			if _, alreadyOnSlot := slot.Skills[skillName]; !alreadyOnSlot {
				slot.Skills[skillName] = skillID
				slot.SkillIDs = append(slot.SkillIDs, skillID)
				// Same any > 0 heuristic as template — first skill
				// whose cost has an any slot is this slot's normal
				// attack. Slot entry is initialized with -1 because
				// bind_char runs before per-binding skill loading,
				// so we set it here on first match.
				if slot.NormalAttackID < 0 && cost.Dices.Any > 0 {
					slot.NormalAttackID = skillID
				}
				rt.Game.AddSkill(pi, ci, skillID)
				rt.registerSkillHooks(skillID, cost, slot)
			}
		}
	}

	return rt.Skills.ByID[skillID], nil
}

func (rt *Runtime) builtinGetSkill(args []Value) (Value, error) {
	skillName, _ := args[1].(string)
	switch cp := args[0].(type) {
	case *CharProxy:
		id, ok := cp.Entry.Skills[skillName]
		if !ok {
			return nil, fmt.Errorf("unresolved_dependency:%s", skillName)
		}
		return rt.Skills.ByID[id], nil
	case *LazyCharProxy:
		// Shared-load talent: resolve lazily at each use via
		// (CurrentContextPlayer, CharName, SkillName).
		return &LazySkillRef{CharName: cp.Name, SkillName: skillName}, nil
	}
	return nil, fmt.Errorf("get_skill: invalid char arg %T", args[0])
}

func (rt *Runtime) builtinInvokeSkill(args []Value) (Value, error) {
	return rt.invokeSkillCommon(args, false)
}

// invoke_skill_silent: 同 invoke_skill,但 ctx.SkipSkillHooks=true。DSL
// 写"使用技能后"类 hook(如增伤 buff)应当 “if ctx.SkipSkillHooks
// then return end“ filter,以避免被 prepare-skill 自动 resolve 或特技
// 自动调用触发。skill 本身的 effect(“if ctx.skill_index == X“)不
// 受影响。见 ADR-0012。
func (rt *Runtime) builtinInvokeSkillSilent(args []Value) (Value, error) {
	return rt.invokeSkillCommon(args, true)
}

func (rt *Runtime) invokeSkillCommon(args []Value, silent bool) (Value, error) {
	var skillID int
	switch v := args[0].(type) {
	case *SkillRef:
		skillID = v.ID
	case *LazySkillRef:
		resolved := v.Resolve(rt)
		if resolved == nil {
			return nil, fmt.Errorf("invoke_skill: lazy skill %s.%s not resolvable in current context (player=%d)", v.CharName, v.SkillName, rt.CurrentContextPlayer)
		}
		skillID = resolved.ID
	case int:
		skillID = v
	}
	g := rt.Game
	cur := g.CurrentEvent()
	inheritedSource := cur.Source
	if inheritedSource == engine.SrcNone {
		inheritedSource = engine.SrcSkill
	}
	g.PushEvent(engine.EventFrame{
		ActionCtx:  engine.ActUseSkill,
		Source:     inheritedSource,
		Player:     cur.Player,
		Char:       cur.Char,
		SkillIndex: skillID,
		CardRef:    cur.CardRef,
	})
	ctx := &engine.EventContext{
		ActionCtx:      engine.ActUseSkill,
		Source:         inheritedSource,
		ActorPlayer:    cur.Player,
		ActorChar:      cur.Char,
		SkillIndex:     skillID,
		Paid:           true,
		SkipSkillHooks: silent,
		IsSpecialty:    silent,
	}
	g.FireEventHooks(engine.HookSkillUse, ctx)
	g.PopEvent()
	return nil, nil
}

// --- Card Builtins ---

func (rt *Runtime) registerSkillHooks(skillID int, cost engine.Cost, charEntry *CharEntry) {
	// Capture the slot's player so each per-slot registration only fires
	// for its own player. Without this, mirror matches would double-write
	// energy counters because both slot registrations would fire on every
	// skill use.
	slotPlayer := charEntry.PlayerIdx
	slotChar := charEntry.CharIdx
	energyID := charEntry.EnergyCounterID
	energyCost := cost.Energy

	// action_check: verify energy if needed
	if energyCost > 0 {
		rt.registerHook(engine.Hook{
			Type: engine.HookActionCheck,
			Fn: func(g *engine.Game, ctx *engine.EventContext) {
				if ctx.ActorPlayer != slotPlayer || ctx.ActorChar != slotChar {
					return
				}
				if ctx.ActionKind != engine.ActionSkill || ctx.SkillIndex != skillID {
					return
				}
				energy := g.Counters[energyID].Value
				if energy < energyCost {
					ctx.Playable = false
				}
			},
		})
	}

	// action_prepare: mark as battle action + expose energy cost
	rt.registerHook(engine.Hook{
		Type: engine.HookActionPrepare,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			if ctx.ActorPlayer != slotPlayer || ctx.ActorChar != slotChar {
				return
			}
			if ctx.ActionKind != engine.ActionSkill || ctx.SkillIndex != skillID {
				return
			}
			ctx.EnergyCost = energyCost
			ctx.BattleAction = true
		},
	})

	// skill_use: consume energy (ults) or gain energy (normal/E).
	// This engine-native hook also serves as the *canonical* on_skill_use
	// hook for this (slot, skill) pair — the pointer-net policy head uses
	// its index in the active hook list to fetch a semantic embedding
	// for the action. Synthetic Tokens are attached so the hook encoder
	// sees it as non-empty (skillID as value makes the embedding unique
	// per skill).
	canonicalTokens := []engine.TokenPair{
		{Type: int16(engine.TokOnSkillUse), Value: int16(skillID)},
		{Type: int16(engine.TokDealDamage), Value: int16(cost.TotalDice())},
		{Type: int16(engine.TokGainEnergy), Value: int16(energyCost)},
	}
	hookID := rt.registerHook(engine.Hook{
		Type:        engine.HookSkillUse,
		Priority:    1000, // high priority, runs before DSL hooks
		OwnerPlayer: slotPlayer,
		OwnerChar:   slotChar,
		Tokens:      canonicalTokens,
		Fn: func(g *engine.Game, ctx *engine.EventContext) {
			if ctx.ActorPlayer != slotPlayer || ctx.ActorChar != slotChar {
				return
			}
			if ctx.SkillIndex != skillID {
				return
			}
			// Paid flag (set by invoke_skill) skips energy deduction
			if !ctx.Paid {
				if energyCost > 0 {
					// Ultimate: consume energy
					g.WriteCounter(energyID, engine.OpSub, energyCost)
				}
			}
			// Energy gain: normal skills always gain 1 energy (even when
			// invoked via card)
			if energyCost == 0 {
				g.WriteCounter(energyID, engine.OpAdd, 1)
			}
		},
	})
	if rt.Game.CanonicalSkillHooks == nil {
		rt.Game.CanonicalSkillHooks = make(map[[3]int]int)
	}
	rt.Game.CanonicalSkillHooks[[3]int{slotPlayer, slotChar, skillID}] = hookID
}
