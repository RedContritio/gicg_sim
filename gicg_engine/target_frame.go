package engine

import "fmt"

// TargetFrame is a data-only continuation at the paid-card input boundary.
// It resumes a known engine program, not an arbitrary captured Go closure.
// The zero PC is deliberately the only externally resumable instruction.
type TargetFrame struct {
	PC           TargetPC
	PlayerIdx    int
	CardRef      int
	BattleAction bool
	TargetMode   int // 1 own character, 2 enemy character
	AppliedMods  map[int]bool
}

type TargetPC uint8

const (
	TargetAwaitChoice TargetPC = iota
	TargetInvokeCard
	TargetConsumed
)

// PendingCard is retained as an API spelling; the executable representation is
// TargetFrame. Its map is deep-copied by copyPendingCard in every snapshot.
type PendingCard = TargetFrame

func (f *TargetFrame) validationError() error {
	if f == nil || f.PC != TargetAwaitChoice || f.PlayerIdx < 0 || f.PlayerIdx > 1 || f.CardRef < 0 ||
		(f.TargetMode != 1 && f.TargetMode != 2) {
		return fmt.Errorf("invalid target execution frame")
	}
	return nil
}

func (f *TargetFrame) validate(g *Game) {
	if err := f.validationError(); err != nil {
		g.FailRule(err, -1)
	}
}

func (f *TargetFrame) Resume(g *Game, targetIdx int) StepResult {
	if targetIdx < 0 {
		return StepContinue
	}
	f.validate(g)
	if g.PendingCardTarget != f {
		g.FailRule(fmt.Errorf("target frame is not the active continuation"), -1)
	}
	targets := g.cardTargetActions(f)
	if targetIdx < 0 || targetIdx >= len(targets) {
		return StepContinue // no mutation, payment or program advance
	}
	chosen := targets[targetIdx]
	// Consume the waiting frame before invoking the card. Any new nested
	// suspension belongs to that invocation, not to this already-paid input.
	g.PendingCardTarget = nil
	f.PC = TargetInvokeCard
	defer func() { f.PC = TargetConsumed }()
	if g.Log != nil {
		for i := len(g.Log.Entries) - 1; i >= 0; i-- {
			if g.Log.Entries[i].Type == "action_card" {
				g.Log.Entries[i].Fields["target_player"] = chosen.PlayerIdx
				g.Log.Entries[i].Fields["target_char"] = chosen.Index
				break
			}
		}
	}
	return g.resolveCardWithMods(f.PlayerIdx, f.CardRef, f.BattleAction, chosen.PlayerIdx, chosen.Index, f.AppliedMods)
}

// SuspendedProgramKind is a stable vocabulary, not a raw card/skill identity.
type SuspendedProgramKind int

const (
	ProgramCardTarget SuspendedProgramKind = iota
	ProgramSwitchTarget
	ProgramReplayBridge // remaining Go/DSL stack is not yet representable
)

// SuspensionKind reports the actual backend at a decision boundary. In
// particular a nested forced switch MUST NOT masquerade as a complete frame.
func (g *Game) SuspensionKind() (SuspendedProgramKind, bool) {
	if g.resume != nil {
		return ProgramReplayBridge, true
	}
	if g.PendingCardTarget != nil {
		return ProgramCardTarget, true
	}
	if g.PendingAction != nil {
		if g.PendingAction.Kind != ActionSwitch {
			return ProgramReplayBridge, true
		}
		return ProgramSwitchTarget, true
	}
	return 0, false
}
