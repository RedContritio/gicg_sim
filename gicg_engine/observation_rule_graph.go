package engine

import (
	"fmt"
	"sort"
	"strings"
)

// ObservationRuleGraph contains public schema links, never live counter values
// or hidden hands/decks. Slot/hook indices use the current observation layout.
type ObservationRuleGraph struct {
	Version       int      `json:"version"`
	CounterOwners [][2]int `json:"counter_owners"`
	// counter observation slot, active hook, local binding ordinal, method token.
	CounterLinks [][4]int `json:"counter_links"`
	// shuffled card slot, active hook belonging to that card's rule file.
	CardLinks [][2]int `json:"card_links"`
	// canonical skill active hook, active hook referring to that definition.
	SkillLinks    [][2]int `json:"skill_links"`
	CardHookLinks [][2]int `json:"card_hook_links"` // canonical card hook -> rule hook
}

func (g *Game) BuildObservationRuleGraph() ObservationRuleGraph {
	g.RequireHealthy()
	graph := ObservationRuleGraph{Version: 2, CounterOwners: make([][2]int, obsCounterSlots()),
		CounterLinks: make([][4]int, 0), CardLinks: make([][2]int, 0), SkillLinks: make([][2]int, 0),
		CardHookLinks: make([][2]int, 0)}
	for i := range graph.CounterOwners {
		graph.CounterOwners[i] = [2]int{-1, -1}
	}
	positions := map[int]int{}
	chars, players, globals := g.groupCounters(0)
	offset := 0
	add := func(ids []int, capacity, player, char int) {
		if len(ids) > capacity {
			panic("rule graph counter capacity exceeded")
		}
		for i, id := range ids {
			positions[id] = offset + i
			graph.CounterOwners[offset+i] = [2]int{player, char}
		}
		offset += capacity
	}
	for p := 0; p < 2; p++ {
		for c := 0; c < ObsMaxChars; c++ {
			add(chars[p][c], ObsCharSlots, p, c)
		}
	}
	for p := 0; p < 2; p++ {
		add(players[p], ObsPlayerSlots, p, -1)
	}
	add(globals, ObsGlobalSlots, -1, -1)
	hooks := g.Hooks.AllHooks()
	active := g.BuildRawToActiveHookIdx()
	for _, hook := range hooks {
		hi, ok := active[hook.ID]
		if !ok {
			continue
		}
		bindings := map[string]int{}
		seen := map[[4]int]bool{}
		link := func(id, binding, method int) {
			if id < 0 {
				return // unallocated lazy target, not an observation slot
			}
			pos, ok := positions[id]
			if !ok {
				panic(fmt.Sprintf("rule graph missing counter %d", id))
			}
			row := [4]int{pos, hi, binding, method}
			if !seen[row] {
				graph.CounterLinks = append(graph.CounterLinks, row)
				seen[row] = true
			}
		}
		for _, access := range hook.CounterAccess {
			binding, ok := bindings[access.Symbol]
			if !ok {
				binding = len(bindings)
				bindings[access.Symbol] = binding
			}
			method, ok := LookupMethod(access.Method)
			if !ok {
				panic(fmt.Sprintf("rule graph unknown counter method %q", access.Method))
			}
			for _, id := range access.CounterIDs {
				link(id, binding, int(method))
			}
		}
		if hook.Type == HookBeforeWrite || hook.Type == HookAfterWrite {
			link(hook.CounterID, -1, 0) // explicit write-trigger binding
		}
		for _, skill := range hook.SkillReferences {
			// A reference to the owner's own skill binds that instance. A
			// foreign/shared definition has no statically proven actor: retain
			// all instances rather than infer a target from the callback owner.
			_, own := g.CanonicalSkillHooks[[3]int{hook.OwnerPlayer, hook.OwnerChar, skill}]
			for key, raw := range g.CanonicalSkillHooks {
				if key[2] != skill || (own && (hook.OwnerPlayer != key[0] || hook.OwnerChar != key[1])) {
					continue
				}
				canonical, exists := active[raw]
				if !exists {
					panic("skill reference missing canonical observation hook")
				}
				graph.SkillLinks = append(graph.SkillLinks, [2]int{canonical, hi})
			}
		}
	}
	sort.Slice(graph.SkillLinks, func(i, j int) bool {
		a, b := graph.SkillLinks[i], graph.SkillLinks[j]
		return a[0] < b[0] || (a[0] == b[0] && a[1] < b[1])
	})
	reverseCards := g.buildReverseCardPerm()
	for ref := 1; ref <= ObsMaxCardTypes; ref++ {
		raw, exists := g.CanonicalCardHooks[ref]
		if !exists {
			continue
		}
		source := strings.SplitN(hooks[raw].Source, "#", 2)[0]
		for _, hook := range hooks {
			hi, ok := active[hook.ID]
			if !ok {
				continue
			}
			if hook.ID == raw || (source != "" && strings.SplitN(hook.Source, "#", 2)[0] == source) {
				graph.CardLinks = append(graph.CardLinks, [2]int{reverseCards[ref-1], hi})
				canonical, ok := active[raw]
				if !ok {
					panic("card reference missing canonical observation hook")
				}
				if hi != canonical {
					graph.CardHookLinks = append(graph.CardHookLinks, [2]int{canonical, hi})
				}
			}
		}
	}
	return graph
}
