package tests

import (
	"gicg_mono/gicg_engine/audit"
	"strings"
	"testing"
)

func TestCurrentEffectsAudit(t *testing.T) {
	e := currentCardGame(t, 0)
	report := audit.Effects(e.G)
	if len(report.Effects) == 0 || len(report.Issues) > 0 {
		t.Fatalf("effect audit: %+v", report.Issues)
	}
	for _, name := range []string{"玄冰_active", "乘胜追击_active", "泼墨", "蝶印", "饱腹", "冻结"} {
		found := false
		for _, effect := range report.Effects {
			if effect.Name == name {
				found = true
			}
		}
		if !found {
			t.Errorf("effect absent from inventory: %s", name)
		}
	}
}

func TestEffectAuditRejectsMissingOrderAndInvisibleRule(t *testing.T) {
	for _, damage := range []string{"order", "repr", "definition"} {
		t.Run(damage, func(t *testing.T) {
			e := currentCardGame(t, 0)
			for _, h := range e.G.Hooks.AllHooks() {
				if strings.HasPrefix(h.Source, "玄冰#") && h.OrderCounter != nil {
					switch damage {
					case "order":
						h.OrderCounter = nil
					case "repr":
						h.Repr = nil
					case "definition":
						e.G.BuffDefinitions[e.G.Counters[h.OrderIDs[0]].BuffIndex].HookIDs = nil
					}
					break
				}
			}
			if len(audit.Effects(e.G).Issues) == 0 {
				t.Fatal("audit accepted broken effect wiring")
			}
		})
	}
}

func TestEffectAuditDetectsCompletelyUnregisteredModifier(t *testing.T) {
	e := currentCardGame(t, 0)
	_, err := execDSL(e, `
 local forgotten=declare_counter("forgotten_guard",Scope.PerPlayer,0,{min=0,max=1})
 on_damage_add(function(ctx)
   if forgotten:get()>0 then ctx.value=ctx.value+1 end
 end)
 `)
	if err != nil {
		t.Fatal(err)
	}
	for _, issue := range audit.Effects(e.G).Issues {
		if strings.Contains(issue, "untracked modifier counter") && strings.Contains(issue, "forgotten_guard") {
			return
		}
	}
	t.Fatal("audit missed a modifier with neither registration nor order binding")
}
