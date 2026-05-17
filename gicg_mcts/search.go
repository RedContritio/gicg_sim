package mcts

import (
	"math/rand"
	"sync"
	"sync/atomic"
	"time"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// Determinization carries one pre-sampled hidden-state assignment
// for the opponent. Python's CardPoolSpec samples these before
// entering Go. Go applies via SetPlayerHand/Deck/Dice at the
// start of each rollout.
type Determinization struct {
	Opponent int32
	Hand     []int32
	Deck     []int32
	Dice     []int32
}

// SearchInput bundles everything Python passes into a Go search call.
type SearchInput struct {
	// Runtime owning the live engine at the root state. Cloned once
	// per rollout goroutine so descent doesn't race on shared state.
	Runtime *interp.Runtime

	// Snapshot the per-goroutine clone's Game is restored to before
	// each rollout.
	Snap *engine.Game

	Config *Config

	// Root node setup — Python does eval + Dirichlet mix (A2/A3) and
	// passes the final prior. Go skips the root expand step.
	RootPrior   []float32
	RootValue   float32
	RootActions []ActionId

	Determinizations []Determinization

	// Async eval callback pair. Invoked from the Search-owned sender
	// and receiver dispatcher goroutines, NOT from the rollout
	// goroutines directly. SendEval pushes a request; RecvEval blocks
	// for the next response. FIFO across send order is preserved by
	// the dispatcher's pending channel.
	SendEval EvalSendFunc
	RecvEval EvalRecvFunc

	WorkerID int32
	GameID   int32
	Seed     uint64
}

// SearchResult is what Go returns to Python.
type SearchResult struct {
	Visits    []int32
	RootValue float32
	Profile   *Profile
}

// Profile collects per-phase time accounting for one search. Atomic
// counters so rollout goroutines can write concurrently.
type Profile struct {
	NRollouts     atomic.Int64
	NRestore      atomic.Int64
	NDeterminize  atomic.Int64
	NEval         atomic.Int64
	NRollout      atomic.Int64
	NDescend      atomic.Int64
	NCommit       atomic.Int64
	NEnvQuery     atomic.Int64
	NEnvStep      atomic.Int64
	NRolloutSteps atomic.Int64

	// ND1Trigger counts rollouts that hit an already-expanded node and
	// found at least one newly-legal action (hasNewActions=true), firing
	// addNewActionsUniform. ND1NewActions is the total count of actions
	// appended across all D1 triggers. Ratio ND1Trigger /
	// (N_expanded_visits) shows how often determinization produces
	// surprise legal actions; ND1NewActions / ND1Trigger is the avg
	// #actions added per D1 — useful baseline signal for future
	// IS-MCTS determinization investigations (s005 smoke found ~6,653/g
	// under scenario-typical training, quantifying D1 surface size).
	ND1Trigger    atomic.Int64
	ND1NewActions atomic.Int64

	RestoreNS     atomic.Int64
	DeterminizeNS atomic.Int64
	EvalNS        atomic.Int64
	RolloutNS     atomic.Int64
	DescendNS     atomic.Int64
	CommitNS      atomic.Int64
	EnvQueryNS    atomic.Int64
	EnvStepNS     atomic.Int64
	TotalNS       atomic.Int64

	// Eval-cache preflight: counts unique (dyn_obs, refs, pay)
	// tuples across all eval requests in this search. Ratio of
	// UniqueEvalKeys / NEval is the upper-bound hit rate for a
	// perfect per-search state cache. Only populated when cfg
	// has Profile=true (the hash + map op are cheap but non-zero
	// — <0.1% of eval wall time in smoke bench).
	UniqueEvalKeys atomic.Int64
	evalTracker    *evalUniqueTracker // nil if Profile=false
}

// evalJob is one in-flight eval request. Rollout goroutines enqueue
// into the sender, which then passes the job through the pending
// channel (FIFO) to the receiver. Receiver fills resp and closes
// done, unblocking the rollout goroutine.
type evalJob struct {
	req  *EvalRequest
	resp *EvalResponse
	done chan struct{}
}

// Search runs the full MCTS algorithm and returns visits at root.
//
// Execution model (Phase D async + concurrent):
//
//  1. N rollout goroutines drive descent, virtual loss, random
//     rollout, and backup in pure Go — no Python calls, no GIL.
//  2. Two dispatcher goroutines bridge to Python:
//     sender: for each job, queue to pending + SendEval
//     receiver: for each job pulled from pending, RecvEval + signal
//     Python's pipe IO releases the GIL while waiting, letting
//     sender and receiver truly interleave — multiple requests
//     stack on the inference_server pipe, enabling real batching.
//  3. Tree is shared lock-free; PUCT + VL handle concurrent descent.
func Search(input *SearchInput) (*SearchResult, error) {
	cfg := input.Config
	pool := NewPool(cfg.NRollouts*300 + 2048)
	defer pool.Reset()

	totalStart := time.Now()

	// --- Build root node with Python-supplied prior (A2/A3) ---
	_, root := pool.Alloc()
	root.Turn = int8(input.Runtime.Game.Turn)
	rootIdx := int32(0)

	rootChildren := make([]int32, len(input.RootActions))
	rootActionsCopy := make([]ActionId, len(input.RootActions))
	copy(rootActionsCopy, input.RootActions)
	for i := range input.RootActions {
		childIdx, child := pool.Alloc()
		child.Prior = input.RootPrior[i]
		child.Turn = -1
		rootChildren[i] = childIdx
	}
	root.InstallExpansion(rootChildren, rootActionsCopy, input.RootValue)

	par := cfg.ParallelRollouts
	if par <= 0 {
		par = 1
	}
	if par > cfg.NRollouts {
		par = cfg.NRollouts
	}

	var prof *Profile
	if cfg.Profile {
		prof = &Profile{}
		prof.evalTracker = &evalUniqueTracker{}
	}

	// --- Dispatcher channels ---
	// sendCh: rollout goroutines → sender (fan-in).
	// pending: sender → receiver (FIFO queue, bounded = parallel).
	// Cap sendCh at par too so back-pressure kicks in when the
	// dispatcher falls behind (should rarely happen at steady state).
	sendCh := make(chan *evalJob, par)
	pending := make(chan *evalJob, par)

	var dispatchErr atomic.Value
	setErr := func(err error) {
		dispatchErr.CompareAndSwap(nil, err)
	}

	// Sender dispatcher: one goroutine that owns SendEval calls.
	// Reading from sendCh is the signal a new job is ready.
	var dispatcherWG sync.WaitGroup
	dispatcherWG.Add(2)
	go func() {
		defer dispatcherWG.Done()
		for job := range sendCh {
			// Order matters: do the Python-side send first, THEN
			// publish to the pending channel. The receiver pops
			// from pending and immediately calls RecvEval, which
			// for mock (Agent) evaluators pops from a Python list
			// populated inside SendEval. If we published to pending
			// first, the receiver could race ahead of the Python
			// append and pop an empty list.
			//
			// For real InferenceClient (pipe-backed) this ordering
			// still works: SendEval writes to the pipe, then we
			// notify the receiver that a response is due; receiver
			// blocks on pipe.recv until the server replies.
			if err := input.SendEval(job.req); err != nil {
				setErr(err)
				close(job.done)
				return
			}
			pending <- job
		}
		close(pending)
	}()

	// Receiver dispatcher: pulls from pending (FIFO matches send
	// order), blocks on RecvEval, then signals the job's waiter.
	go func() {
		defer dispatcherWG.Done()
		for job := range pending {
			if err := input.RecvEval(job.resp); err != nil {
				setErr(err)
				close(job.done)
				return
			}
			close(job.done)
		}
	}()

	// --- Rollout goroutines ---
	workCh := make(chan int, par*2)
	var wg sync.WaitGroup
	for g := 0; g < par; g++ {
		wg.Add(1)
		go func(gID int) {
			defer wg.Done()
			// Each goroutine owns a Runtime clone + RNG. Runtime.Clone
			// deep-copies the Game so descent mutations don't race.
			rt := input.Runtime.Clone()
			game := rt.Game
			rng := rand.New(rand.NewSource(
				int64(input.Seed + uint64(gID)),
			))

			for rolloutIdx := range workCh {
				if dispatchErr.Load() != nil {
					return
				}
				fl := &inFlightRollout{rolloutIdx: rolloutIdx}
				if err := startRollout2(
					pool, rootIdx, input, cfg, rt, game, rng,
					sendCh, fl, prof,
				); err != nil {
					setErr(err)
					return
				}
				if fl.terminal {
					commitRollout(pool, fl, cfg, prof)
					continue
				}
				// Job was sent by startRollout2; wait for response.
				<-fl.job.done
				if dispatchErr.Load() != nil {
					return
				}
				commitRollout(pool, fl, cfg, prof)
			}
		}(g)
	}

	for i := 0; i < cfg.NRollouts; i++ {
		workCh <- i
	}
	close(workCh)
	wg.Wait()
	// All rollout goroutines done → no more eval jobs will be sent.
	close(sendCh)
	dispatcherWG.Wait()

	if err := dispatchErr.Load(); err != nil {
		return nil, err.(error)
	}

	visits := make([]int32, len(rootChildren))
	for i, childIdx := range rootChildren {
		visits[i] = int32(pool.Get(childIdx).N.Load())
	}

	rootQ := root.QP0()

	if prof != nil {
		prof.NRollouts.Store(int64(cfg.NRollouts))
		prof.TotalNS.Store(time.Since(totalStart).Nanoseconds())
		if prof.evalTracker != nil {
			prof.UniqueEvalKeys.Store(prof.evalTracker.UniqueCount())
		}
	}

	return &SearchResult{
		Visits:    visits,
		RootValue: rootQ,
		Profile:   prof,
	}, nil
}
