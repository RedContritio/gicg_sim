package engine

import "fmt"

func (g *Game) RemoveBuff(id uint64) {
	for i, b := range g.Buffs {
		if b.ID == id {
			g.Buffs = append(g.Buffs[:i], g.Buffs[i+1:]...)
			return
		}
	}
}

// Independent instances share a definition, not charges or expiry counters.
// Existing aggregate effects retain their counter-backed representation.
func (g *Game) SpawnBuff(definition, value, duration int) (uint64, error) {
	if definition < 0 || definition >= len(g.BuffDefinitions) {
		return 0, fmt.Errorf("unknown buff definition")
	}
	def := g.BuffDefinitions[definition]
	if !def.Independent || value <= 0 || value > g.Counters[def.CounterID].Max || duration == 0 || duration < -1 {
		return 0, fmt.Errorf("invalid independent buff parameters")
	}
	b := g.newBuffInstance(definition)
	b.Independent, b.Duration = true, duration
	g.Buffs = append(g.Buffs, b)
	frame := g.currentEvent()
	frame.BuffID, frame.BuffCounterID = b.ID, def.CounterID
	g.PushEvent(frame)
	defer g.PopEvent()
	g.WriteCounter(def.CounterID, OpAdd, value)
	g.DrainDeferred()
	if live := g.buffByID(b.ID); live != nil && live.Value == 0 {
		g.RemoveBuff(b.ID)
	}
	return b.ID, nil
}

func (g *Game) readIndependentCounter(id int) (int, bool) {
	index := g.Counters[id].BuffIndex
	if index < 0 || !g.BuffDefinitions[index].Independent {
		return 0, false
	}
	frame := g.currentEvent()
	if frame.BuffID != 0 && frame.BuffCounterID == id {
		if b := g.buffByID(frame.BuffID); b != nil {
			return b.Value, true
		}
		return 0, true
	}
	sum := 0
	for _, b := range g.Buffs {
		if b.Definition == index {
			sum += b.Value
		}
	}
	return sum, true
}

func (g *Game) writeIndependentCounter(id int, op Op, value int) bool {
	index := g.Counters[id].BuffIndex
	if index < 0 || !g.BuffDefinitions[index].Independent {
		return false
	}
	frame := g.currentEvent()
	if frame.BuffID != 0 && frame.BuffCounterID == id {
		b := g.buffByID(frame.BuffID)
		if b == nil {
			return true
		}
		switch op {
		case OpSet:
			b.Value = value
		case OpAdd:
			b.Value += value
		case OpSub:
			b.Value -= value
		}
		if b.Value > g.Counters[id].Max {
			b.Value = g.Counters[id].Max
		}
		if b.Value <= 0 {
			g.RemoveBuff(b.ID)
		}
		return true
	}
	if op != OpSet || value != 0 {
		panic("independent buff writes need an instance; use spawn_buff")
	}
	for _, b := range append([]BuffInstance(nil), g.Buffs...) {
		if b.Definition == index {
			g.RemoveBuff(b.ID)
		}
	}
	return true
}

func (g *Game) BuffValues(b BuffInstance) (value, duration, progress int) {
	if b.Independent {
		return b.Value, b.Duration, b.Progress
	}
	d := g.BuffDefinitions[b.Definition]
	value, duration = g.Counters[d.CounterID].Value, -1
	if d.ExpiresRoundEnd {
		duration = 1
	}
	if d.DurationID >= 0 {
		duration = g.Counters[d.DurationID].Value
	}
	if d.ProgressID >= 0 {
		progress = g.Counters[d.ProgressID].Value
	}
	return
}

func (g *Game) BuffRemaining(id uint64) int {
	if b := g.buffByID(id); b != nil {
		_, duration, _ := g.BuffValues(*b)
		return duration
	}
	return 0
}

func (g *Game) SetBuffRemaining(id uint64, duration int) error {
	b := g.buffByID(id)
	if b == nil {
		return nil
	}
	if !b.Independent || duration < -1 {
		return fmt.Errorf("set_buff_duration requires independent instance and duration >= -1")
	}
	if duration == 0 {
		g.RemoveBuff(id)
	} else {
		b.Duration = duration
	}
	return nil
}

// BuffOwner gives bound DSL counter operations the instance's viewpoint, even
// when the triggering damage/heal was initiated by the other player.
func (g *Game) BuffOwner(id uint64) [2]int {
	if b := g.buffByID(id); b != nil {
		return g.GetCounterChar(g.BuffDefinitions[b.Definition].CounterID)
	}
	return [2]int{-1, -1}
}

func (g *Game) BuffProgress(id uint64) (int, error) {
	if b := g.buffByID(id); b != nil && b.Independent {
		return b.Progress, nil
	}
	return 0, fmt.Errorf("buff_progress requires a live independent instance")
}

func (g *Game) SetBuffProgress(id uint64, value int) error {
	b := g.buffByID(id)
	if b == nil || !b.Independent || value < 0 || value > 2147483647 {
		return fmt.Errorf("set_buff_progress requires independent instance and nonnegative int32")
	}
	b.Progress = value
	return nil
}
