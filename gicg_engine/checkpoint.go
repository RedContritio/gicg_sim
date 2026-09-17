package engine

import (
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"gicg_mono/gicg_engine/internal/strictjson"
	"reflect"
)

var ErrCheckpointIncompatible = errors.New("incompatible checkpoint version, random protocol or registry layout")

// Checkpoints preserve gameplay state across processes with identical registry
// layouts and DSL sources. Callers must also pin their engine build for archival
// replay: the wire version does not identify changes to compiled Go behavior.
type checkpoint struct {
	Version        int
	RandomProtocol string
	LayoutHash     string
	RulesDigest    string
	State          *GameSnap
	MaxRounds      int
	FixDice        []int
}

func (g *Game) checkpointLayout() string {
	type charDef struct {
		Name         string
		Player, Slot int
		Skills       []int
		Element      Element
	}
	var chars []charDef
	for pi, p := range g.Players {
		for ci, c := range p.Chars {
			chars = append(chars, charDef{g.CharNames[[2]int{pi, ci}], pi, ci, c.Skills, c.Element})
		}
	}
	defs := append([]Counter(nil), g.Counters...)
	for i := range defs {
		defs[i].Value = 0
	}
	// json.Marshal sorts integer map keys, making this process-independent.
	data, err := json.Marshal(struct {
		Counters                            []Counter
		BuffDefinitions                     []BuffDefinition
		CounterNames, CardNames, SkillNames map[int]string
		Chars                               []charDef
	}{defs, g.BuffDefinitions, g.CounterNames, g.CardNames, g.SkillNames, chars})
	if err != nil {
		panic(err)
	}
	return fmt.Sprintf("%x", sha256.Sum256(data))
}

func (g *Game) ExportCheckpoint() ([]byte, error) {
	if !g.IsQuiescent() {
		return nil, fmt.Errorf("checkpoint requires a quiescent boundary")
	}
	if g.PendingAction != nil || g.PendingDice != nil || g.resume != nil {
		return nil, fmt.Errorf("pending-input checkpoint export is not supported for replay continuations")
	}
	if err := g.validateTargetCheckpoint(g.PendingCardTarget, g.Phase); err != nil {
		return nil, err
	}
	s := g.SnapshotPooled()
	defer ReleaseSnap(s)
	if len(s.Buffs) == 0 {
		s.Buffs = nil
	}
	// Pool allocation history must not affect the checkpoint bytes. Empty
	// zones have one wire representation, regardless of retained capacity.
	for pi := range s.Players {
		p := &s.Players[pi]
		if len(p.Hand) == 0 {
			p.Hand = nil
		}
		if len(p.Deck) == 0 {
			p.Deck = nil
		}
		if len(p.Discard) == 0 {
			p.Discard = nil
		}
		if len(p.Supports) == 0 {
			p.Supports = nil
		}
		if len(p.InitDeck) == 0 {
			p.InitDeck = nil
		}
	}
	return json.Marshal(checkpoint{2, RandomProtocol, g.checkpointLayout(), g.RulesDigest, s, g.MaxRounds, g.FixDice})
}

// RestoreCheckpoint validates in temporary memory before changing the receiver.
// Logs, runtime bindings and immutable observation layout remain attached.
func (g *Game) RestoreCheckpoint(data []byte) error {
	if !g.IsQuiescent() {
		return fmt.Errorf("restore requires a quiescent boundary")
	}
	var c checkpoint
	if err := strictjson.Decode(data, &c); err != nil {
		return fmt.Errorf("checkpoint: %w", err)
	}
	if c.Version != 2 || c.RandomProtocol != RandomProtocol || c.LayoutHash != g.checkpointLayout() || c.RulesDigest != g.RulesDigest {
		return ErrCheckpointIncompatible
	}
	if err := g.validateCheckpoint(&c); err != nil {
		return err
	}
	c.State.hooks = g.Hooks
	g.RestoreFromSnap(c.State)
	g.MaxRounds = c.MaxRounds
	g.FixDice = append([]int(nil), c.FixDice...)
	return nil
}

func (g *Game) validateCheckpoint(c *checkpoint) error {
	s := c.State
	if s == nil || len(s.Counters) != len(g.Counters) || s.Rng == nil {
		return fmt.Errorf("incomplete checkpoint state")
	}
	if s.Phase < PhaseSelectActive || s.Phase > PhaseGameOver || s.Round < 0 || s.Turn < 0 || s.Turn > 1 || s.FirstEnd < -1 || s.FirstEnd > 1 || s.Winner < -1 || s.Winner > 2 {
		return fmt.Errorf("invalid checkpoint phase/turn/round/winner")
	}
	if c.MaxRounds < 0 || (len(c.FixDice) != 0 && len(c.FixDice) != DiceColorCount) {
		return fmt.Errorf("invalid checkpoint configuration")
	}
	for _, n := range c.FixDice {
		if n < 0 {
			return fmt.Errorf("negative dice count")
		}
	}
	for i, v := range s.Counters {
		def := g.Counters[i]
		if v.BuffIndex != def.BuffIndex || v.Init != def.Init || v.Min != def.Min || v.Max != def.Max || v.Value < v.Min || v.Value > v.Max {
			return fmt.Errorf("invalid checkpoint counter %d", i)
		}
	}
	if err := g.validateBuffState(s); err != nil {
		return err
	}
	validRef := func(ref int) bool { _, ok := g.CardNames[ref]; return ok }
	boundSupports := map[uint64]bool{}
	supportIDs := map[uint64]bool{}
	for pi, p := range s.Players {
		if len(p.Chars) != len(g.Players[pi].Chars) || p.ActiveChar < -1 || p.ActiveChar >= len(p.Chars) || len(p.Supports) > MaxSupportSlots || s.DeckRngs[pi] == nil {
			return fmt.Errorf("invalid checkpoint player %d", pi)
		}
		for ci, ch := range p.Chars {
			def := g.Players[pi].Chars[ci]
			if ch.PlayerIdx != def.PlayerIdx || ch.CharIdx != def.CharIdx || ch.Element != def.Element || !reflect.DeepEqual(ch.Skills, def.Skills) {
				return fmt.Errorf("incompatible character definition")
			}
			if ch.SpecialtyCardRef != -1 && !validRef(ch.SpecialtyCardRef) {
				return fmt.Errorf("unknown equipment")
			}
		}
		for _, zone := range [][]CardInst{p.Hand, p.Deck, p.Discard, p.InitDeck} {
			for _, card := range zone {
				if !validRef(card.Ref) || card.DrawnAtRound < 0 {
					return fmt.Errorf("invalid card instance")
				}
			}
		}
		for _, support := range p.Supports {
			if support.ID != 0 {
				if support.ID > s.BuffSerial || supportIDs[support.ID] {
					return fmt.Errorf("invalid support identity")
				}
				for _, buff := range s.Buffs {
					if buff.ID == support.ID {
						return fmt.Errorf("support and buff share identity")
					}
				}
				supportIDs[support.ID] = true
			} else if support.BuffID != 0 {
				return fmt.Errorf("bound support has no identity")
			}
			if !validRef(support.Ref) || support.ActivatedAt < 0 {
				return fmt.Errorf("invalid support instance")
			}
			if support.BuffID != 0 {
				found := false
				for _, buff := range s.Buffs {
					if buff.ID == support.BuffID && buff.Independent &&
						g.GetCounterChar(g.BuffDefinitions[buff.Definition].CounterID)[0] == pi {
						found = true
					}
				}
				if !found || boundSupports[support.BuffID] {
					return fmt.Errorf("invalid or duplicate support effect binding")
				}
				boundSupports[support.BuffID] = true
			}
		}
	}
	if s.PendingAction != nil || s.PendingDice != nil {
		return fmt.Errorf("pending-input checkpoint import is not supported for replay continuations")
	}
	return g.validateTargetCheckpoint(s.PendingCardTarget, s.Phase)
}
