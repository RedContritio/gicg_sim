package engine

import "fmt"

// DynamicEntityKind distinguishes quantities/effects from typed references.
const (
	EntityBuff = iota
	EntitySupport
	EntitySpecialty
	EntitySkillReference
	EntityCardReference
	EntityExecutionFrame
	EntityExecutionBinding
)

// ObservationReferenceKinds returns only schema information, never hidden values.
// Values are interpreted by the engine from the current branch's counters.
type ObservationReferenceResolver interface {
	ObservationReferenceKinds() map[int]int // raw counter ID -> 1 skill, 2 card
}

func (g *Game) observationReferenceKinds() map[int]int {
	if resolver, ok := g.Extra.(ObservationReferenceResolver); ok {
		return resolver.ObservationReferenceKinds()
	}
	return nil
}

func referencePresence(value int) int32 {
	if value >= 0 {
		return 1
	}
	return 0
}

// Skill references identify definitions, not actor instances. A shared skill
// must not invent an actor; use the lowest canonical hook as a stable rule
// representative and expose an actor only for a uniquely bound definition.
func (g *Game) skillReferenceHook(id int) (int, int, int) {
	hook, targetP, targetC, count := -1, -1, -1, 0
	for key, candidate := range g.CanonicalSkillHooks {
		if key[2] != id {
			continue
		}
		count++
		if hook < 0 || candidate < hook {
			hook, targetP, targetC = candidate, key[0], key[1]
		}
	}
	if count == 0 {
		panic(fmt.Sprintf("unresolved skill reference %d", id))
	}
	if count > 1 {
		targetP, targetC = -1, -1
	}
	return hook, targetP, targetC
}

// Entity rows share the variable-length transport with buffs. Appended fields:
// kind, source counter SID (-1 absent), referenced player/character (-1 absent).
// No raw card/skill ID or absolute lifecycle serial is emitted.
func (g *Game) writeEntityObs(out []int32, perspective, row int, kinds map[int]int) {
	hooks := g.BuildRawToActiveHookIdx()
	appendRow := func(kind, p, c, value, age, position, sid, rawHook, targetP, targetC int) {
		if row >= ObsBuffRows {
			panic("entity observation capacity exceeded")
		}
		hook := -1
		if rawHook >= 0 {
			var ok bool
			hook, ok = hooks[rawHook]
			if !ok {
				panic("entity references a missing rule hook")
			}
		}
		values := []int32{1, relativePlayer(p, perspective), int32(c), int32(value), int32(age), 0,
			int32(position), int32(hook), 0, 0, 0, 0, int32(kind), int32(sid),
			relativePlayer(targetP, perspective), int32(targetC)}
		copy(out[row*ObsBuffFields:], values)
		row++
	}
	cardHook := func(ref int) int {
		h, ok := g.CanonicalCardHooks[ref]
		if !ok {
			panic(fmt.Sprintf("unresolved card reference %d", ref))
		}
		return h
	}
	for _, p := range []int{perspective, 1 - perspective} {
		for slot, support := range g.Players[p].Supports {
			value, progress := 1, 0
			if support.BuffID != 0 {
				buff := g.buffByID(support.BuffID)
				if buff == nil {
					panic("support references a missing effect instance")
				}
				value, _, progress = g.BuffValues(*buff)
			}
			appendRow(EntitySupport, p, -1, value, g.Round-support.ActivatedAt, slot, -1, cardHook(support.Ref), -1, -1)
			out[(row-1)*ObsBuffFields+5] = int32(progress)
		}
		for c, character := range g.Players[p].Chars {
			if character.SpecialtyCardRef >= 0 {
				appendRow(EntitySpecialty, p, c, 1, -1, c, -1, cardHook(character.SpecialtyCardRef), -1, -1)
			}
		}
	}
	row = g.writeSuspensionObs(out, perspective, row)
	// CounterPerm order is shared with static counter metadata, independent of raw IDs.
	reverse := g.buildReversePerm()
	order := g.CounterPerm
	if len(order) == 0 {
		order = make([]int, len(g.Counters))
		for id := range order {
			order[id] = id
		}
	}
	for _, id := range order {
		kind := kinds[id]
		if kind == 0 {
			continue
		}
		if kind != 1 && kind != 2 {
			panic("unknown counter reference kind")
		}
		owner := g.GetCounterChar(id)
		value := g.Counters[id].Value
		rawHook, targetP, targetC := -1, -1, -1
		if value >= 0 {
			if kind == 1 {
				rawHook, targetP, targetC = g.skillReferenceHook(value)
			} else if kind == 2 {
				rawHook = cardHook(value)
			} else {
				panic("unknown counter reference kind")
			}
		}
		appendRow(EntitySkillReference+kind-1, owner[0], owner[1], int(referencePresence(value)), -1, 0,
			reverse[id], rawHook, targetP, targetC)
	}
}
