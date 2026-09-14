package engine

import "fmt"

// A suspended operation owns immutable reconstruction data, never live Go/DSL
// stack frames. Reconstructing its stack uses the original random state. At
// each recorded input boundary we install that branch's state before executing
// its choice. Thus hidden-state sampling and RNG changes made while waiting
// remain effective; reconstruction cannot roll them back.
type continuation struct {
	root    *GameSnap
	op      boundaryOperation
	choices []boundaryChoice
	log     logBoundary
	public  publicCause // value-only public origin; never DSL locals or root data
}

type boundaryChoice struct {
	state  *GameSnap
	action Action
}

type boundaryOperation struct {
	kind  boundaryKind
	index int
	frame EventFrame
	fn    func(*Game)
}

type boundaryKind uint8

const (
	boundaryStep boundaryKind = iota
	boundaryTarget
	boundaryNewRound
	boundaryEndPhase
	boundaryPreparing
	boundaryEffect
)

type execution struct {
	continuation
	next int
}

type inputSuspension struct{}

type logBoundary struct {
	log                   *EventLog
	entries, rounds, step int
}

func (g *Game) captureLogBoundary() logBoundary {
	if g.Log == nil {
		return logBoundary{}
	}
	return logBoundary{g.Log, len(g.Log.Entries), len(g.Log.RoundStartSnaps), g.Log.step}
}

func (b logBoundary) rewind(g *Game) {
	if g.Log == nil || g.Log != b.log {
		return // clones/search deliberately have independent diagnostic attachments
	}
	if len(g.Log.Entries) < b.entries || len(g.Log.RoundStartSnaps) < b.rounds {
		g.FailRule(fmt.Errorf("continuation log prefix was removed"), -1)
	}
	g.Log.Entries = g.Log.Entries[:b.entries]
	g.Log.RoundStartSnaps = g.Log.RoundStartSnaps[:b.rounds]
	g.Log.step = b.step
}

func (op boundaryOperation) invoke(g *Game) StepResult {
	switch op.kind {
	case boundaryStep:
		return g.step(op.index)
	case boundaryTarget:
		return g.stepTarget(op.index)
	case boundaryNewRound:
		g.newRound()
	case boundaryEndPhase:
		g.endPhase()
	case boundaryPreparing:
		g.resolvePreparing()
	case boundaryEffect:
		g.PushEvent(op.frame)
		defer g.PopEvent()
		op.fn(g)
		g.DrainDeferred()
	default:
		panic("unknown boundary operation")
	}
	if g.Phase == PhaseGameOver {
		return StepGameOver
	}
	return StepContinue
}

func (g *Game) runBoundary(op boundaryOperation) StepResult {
	g.RequireHealthy()
	if g.executing != nil {
		return op.invoke(g)
	}
	if g.resume != nil {
		return StepNeedTarget
	}
	root := g.SnapshotPooled()
	x := &execution{continuation: continuation{root: root, op: op, log: g.captureLogBoundary()}}
	result := g.runExecution(x)
	if g.resume == nil {
		ReleaseSnap(root)
	}
	// On suspension root leaves the pool and is GC-owned, immutable, and shared
	// by waiting snapshots. It must never be returned to the pool afterward.
	return result
}

func (g *Game) runExecution(x *execution) (result StepResult) {
	g.executing = x
	g.resume = nil
	defer func() {
		g.executing = nil
		if err := recover(); err != nil {
			if _, ok := err.(inputSuspension); !ok {
				panic(err)
			}
			// Synchronous callers have unwound; no closures or scratch arrays
			// from that stack may be retained by the visible waiting state.
			g.eventStack = nil
			g.damageLogStack = nil
			g.depth = 0
			state := x.continuation
			g.resume = &state
			result = StepNeedTarget
		}
	}()
	result = x.op.invoke(g)
	if x.next != len(x.choices) {
		g.FailRule(fmt.Errorf("continuation did not reach its recorded input boundary"), -1)
	}
	return result
}

func (g *Game) resumeTarget(index int) StepResult {
	if g.PendingDice == nil && (g.PendingAction == nil || g.PendingAction.Kind != ActionSwitch) {
		g.FailRule(fmt.Errorf("unsupported continuation input"), -1)
	}
	actions := g.GetLegalActions()
	if index < 0 || index >= len(actions) {
		return StepContinue // invalid selection is read-only
	}
	c := g.resume
	state := g.SnapshotPooled()
	state.resume = nil // retain the branch state, not a recursive history chain
	choices := append([]boundaryChoice(nil), c.choices...)
	choices = append(choices, boundaryChoice{state: state, action: actions[index]})
	x := &execution{continuation: continuation{root: c.root, op: c.op, choices: choices, log: c.log}}
	g.RestoreFromSnap(c.root)
	c.log.rewind(g)
	return g.runExecution(x)
}

func (g *Game) requestDeferredInput(action *Action) {
	if action == nil || action.Kind != ActionSwitch || !action.Forced || action.PlayerIdx < 0 || action.PlayerIdx > 1 {
		g.FailRule(fmt.Errorf("invalid deferred switch request"), -1)
	}
	if len(g.forcedSwitchActions(action.PlayerIdx)) == 0 {
		g.FailRule(fmt.Errorf("deferred switch has no legal replacement"), -1)
	}
	g.PendingAction = copyAction(action)
	x := g.executing
	if x == nil {
		g.FailRule(fmt.Errorf("required input outside a managed operation; use Step, StepTarget or ExecuteEffect"), -1)
	}
	if x.next == len(x.choices) {
		panic(inputSuspension{})
	}
	choice := x.choices[x.next]
	x.next++
	if action.Kind != ActionSwitch || action.PlayerIdx != choice.action.PlayerIdx || action.Forced != choice.action.Forced {
		g.FailRule(fmt.Errorf("continuation input identity changed"), -1)
	}
	// Restore gameplay only. Current event/DSL locals belong to the rebuilt
	// stack, and its dynamic scratch must remain in place until it completes.
	g.restoreGameplay(choice.state)
	g.resume = nil
	g.PendingAction = nil
	g.logAction(choice.action)
	actCtx := ActSwitch
	if choice.action.Forced {
		actCtx = ActForcedDeath
	}
	g.executeSwitch(choice.action, actCtx)
}
