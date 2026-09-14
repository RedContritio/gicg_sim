package tests

import (
	engine "gicg_mono/gicg_engine"
	"reflect"
	"strings"
	"testing"
)

func TestBuffObservationLiveOrderAndEnemyMark(t *testing.T) {
	e := currentCardGame(t, 0)
	auditPlay(t, e, 0, "乘胜追击")
	auditPlay(t, e, 0, "速速茶点")
	auditPlay(t, e, 0, "蝶鳞")
	auditSkill(t, e, 0, "枪")
	obs := e.G.BuildDynamicObs(0)
	tail := obs[len(obs)-engine.ObsBuffSlots:]
	slots := e.G.BuildRawToActiveHookIdx()
	marked, progress, count := false, false, 0
	for offset := 0; offset < len(tail); offset += engine.ObsBuffFields {
		row := tail[offset : offset+engine.ObsBuffFields]
		if row[0] == 0 || row[12] != engine.EntityBuff {
			continue
		}
		count++
		found := false
		for _, h := range e.G.Hooks.AllHooks() {
			slot, ok := slots[h.ID]
			if !ok || slot != int(row[7]) {
				continue
			}
			found = true
			if strings.HasPrefix(h.Source, "蝶鳞#") && row[1] == 1 && row[2] == 0 && row[10] == 1 {
				marked = true
			}
			if strings.HasPrefix(h.Source, "乘胜追击#") && row[5] > 0 {
				progress = true
			}
		}
		if !found {
			t.Fatalf("missing hook for buff row %v", row)
		}
	}
	if count == 0 || !marked || !progress {
		t.Fatalf("buff visibility: rows=%d mark=%v progress=%v", count, marked, progress)
	}
	snap := e.G.SnapshotPooled()
	defer engine.ReleaseSnap(snap)
	for i, j := 0, len(e.G.Buffs)-1; i < j; i, j = i+1, j-1 {
		e.G.Buffs[i], e.G.Buffs[j] = e.G.Buffs[j], e.G.Buffs[i]
	}
	changed := e.G.BuildDynamicObs(0)
	if reflect.DeepEqual(obs, changed) {
		t.Fatal("creation order invisible")
	}
	e.G.RestoreFromSnap(snap)
	if !reflect.DeepEqual(obs, e.G.BuildDynamicObs(0)) {
		t.Fatal("restore lost buff observation")
	}
}

func TestBuffObservationCurrentPoolCapacity(t *testing.T) {
	e := currentCardGame(t, 0)
	count := 0
	slots := e.G.BuildRawToActiveHookIdx()
	for _, def := range e.G.BuffDefinitions {
		for _, h := range e.G.Hooks.AllHooks() {
			if _, ok := slots[h.ID]; !ok {
				continue
			}
			for _, source := range def.RuleSources {
				if strings.HasPrefix(h.Source, source+"#") {
					count++
					break
				}
			}
		}
	}
	if count > engine.ObsBuffRows {
		t.Fatalf("all registered instances need %d rows, capacity %d", count, engine.ObsBuffRows)
	}
}
