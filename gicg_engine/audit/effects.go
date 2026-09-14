// Package audit checks effect wiring; it does not certify card semantics.
package audit

import (
	"fmt"
	engine "gicg_mono/gicg_engine"
	"sort"
)

type Effect struct {
	CounterID                                    int
	Name                                         string
	Owner                                        [2]int
	Independent, DeathBound, RoundExpiry, Summon bool
	Duration, Progress                           string
	Hooks, Reads, Writes, Expiry                 []string
}
type Report struct {
	PublicState []StatePolicy
	Limitations []string
	Effects     []Effect
	Issues      []string
}

func contains(ids []int, id int) bool {
	for _, x := range ids {
		if x == id {
			return true
		}
	}
	return false
}
func write(method string) bool {
	switch method {
	case "set", "set_at", "add", "add_at", "sub", "sub_at", "fill_all", "decay_all":
		return true
	}
	return false
}
func structural(h *engine.Hook) bool {
	kind := h.Type
	// Card/skill creation, eligibility gates, and elemental reactions are fixed
	// pipeline programs. Stateful follow-up effects must explicitly bind order.
	return kind == engine.HookCardPlay || kind == engine.HookActionCheck || (kind == engine.HookReactionDamage && h.SystemRule)
}

func Effects(g *engine.Game) Report {
	r := Report{Issues: untracked(g)}
	var policyIssues []string
	r.PublicState, policyIssues = PublicState()
	r.Issues = append(r.Issues, policyIssues...)
	r.Limitations = []string{
		"AST access inventory resolves captured counter proxies; computed receivers and callback arguments need separate behavioral tests",
		"Lifecycle wiring is checked, but reading/writing a counter does not prove its gameplay semantics",
		"General suspended programs, support-slot identity and specialty-slot identity are not fully encoded; current cards use joint targets and counter-backed support/talent effects",
		"Typed card/skill reference counters still use legacy values; this is not a guarantee of ID-independent generalization",
	}
	hooks := g.Hooks.AllHooks()
	for _, d := range g.BuffDefinitions {
		e := Effect{CounterID: d.CounterID, Name: g.CounterNames[d.CounterID], Owner: g.GetCounterChar(d.CounterID), Independent: d.Independent, DeathBound: d.RemoveOnDeath, RoundExpiry: d.ExpiresRoundEnd, Summon: d.Summon}
		if d.DurationID >= 0 {
			e.Duration = g.CounterNames[d.DurationID]
		}
		if d.ProgressID >= 0 {
			e.Progress = g.CounterNames[d.ProgressID]
		}
		if len(d.HookIDs) == 0 {
			r.Issues = append(r.Issues, fmt.Sprintf("no effect hooks: %s owner=%v", e.Name, e.Owner))
		}
		for _, hid := range d.HookIDs {
			valid := false
			for _, h := range hooks {
				if h.ID == hid && h.OrderCounter != nil && contains(h.OrderIDs, d.CounterID) {
					valid = true
					break
				}
			}
			if !valid {
				r.Issues = append(r.Issues, fmt.Sprintf("stale effect binding: %s / hook %d", e.Name, hid))
			}
		}
		for _, h := range hooks {
			bound := contains(h.OrderIDs, d.CounterID)
			if bound {
				e.Hooks = append(e.Hooks, h.Source)
				if !contains(d.HookIDs, h.ID) || h.Repr == nil || h.Repr.IsEmpty() {
					r.Issues = append(r.Issues, "missing observable hook: "+h.Source+" / "+e.Name)
				}
				if h.Type == engine.HookRoundEndDecay || h.Type == engine.HookRoundEnd {
					e.Expiry = append(e.Expiry, h.Source)
				}
			}
			for _, a := range h.CounterAccess {
				if !contains(a.CounterIDs, d.CounterID) {
					continue
				}
				site := fmt.Sprintf("%s:%d %s:%s", h.Source, a.Line, a.Symbol, a.Method)
				if write(a.Method) {
					e.Writes = append(e.Writes, site)
				} else {
					e.Reads = append(e.Reads, site)
					if a.Method == "get" || a.Method == "get_at" {
						if !bound && h.OrderCounter == nil && !structural(h) {
							r.Issues = append(r.Issues, "unbound effect read: "+site+" / "+e.Name)
						}
					}
				}
			}
		}
		if (d.ExpiresRoundEnd || d.DurationID >= 0) && len(e.Expiry) == 0 {
			r.Issues = append(r.Issues, "missing expiry hook: "+e.Name)
		}
		r.Effects = append(r.Effects, e)
	}
	sort.Strings(r.Issues)
	unique := r.Issues[:0]
	for _, issue := range r.Issues {
		if len(unique) == 0 || unique[len(unique)-1] != issue {
			unique = append(unique, issue)
		}
	}
	r.Issues = unique
	return r
}
