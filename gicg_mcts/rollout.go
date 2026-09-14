package mcts

import (
	"fmt"
	"math/rand"

	engine "gicg_mono/gicg_engine"
	"gicg_mono/gicg_engine/interp"
)

// inFlightRollout bundles one rollout's state between "started" and
// "committed". Matches training/mcts.py::_InFlightRollout.
type inFlightRollout struct {
	rolloutIdx int

	path     []int32
	leafIdx  int32
	leafTurn int8 // perspective of this rollout's evaluation, never shared on Node
	legalIds []ActionId

	terminal    bool
	leafValueP0 float32

	hasRolloutValue bool
	rolloutValueP0  float32

	req  EvalRequest
	resp EvalResponse

	// job is the handle sent to the dispatcher for async eval. The
	// rollout goroutine blocks on <-job.done after startRollout2
	// returns (unless terminal).
	job *evalJob
}

func terminalZ(winner int) float32 {
	switch winner {
	case 0:
		return 1
	case 1:
		return -1
	case 2:
		return 0
	}
	panic(fmt.Sprintf("mcts: terminalZ called with winner=%d", winner))
}

// startRollout2 is the Phase D variant: runs fully in the caller
// goroutine (one of N rollout workers), sends the leaf eval request
// via sendCh, and returns. Caller blocks on fl.job.done outside.
//
// Terminal leaves skip the send and set fl.terminal=true.
//
// IS-MCTS D1 new-action reeval is handled inline: the reeval also
// goes through sendCh (own job), and this goroutine waits on its
// own reeval job.done before continuing descent. Because each
// rollout goroutine has its own Runtime + Game, concurrent reevals
// across goroutines don't interfere on engine state.
func startRollout2(
	pool *Pool, rootIdx int32,
	input *SearchInput, cfg *Config,
	rt *interp.Runtime, game *engine.Game, rng *rand.Rand,
	sendCh chan<- *evalJob,
	fl *inFlightRollout, prof *Profile,
) (err error) {
	defer recoverRolloutFailure(&err)
	// --- 1. Restore + reset runtime scratch ---
	t0 := timeIfProf(prof)
	game.RestoreFrom(input.Snap)
	// Chance sampling belongs to the rollout, never to restoring the shared
	// root snapshot. Index-based seeds are independent of worker scheduling.
	game.SetSimulationSeed(int64(input.Seed + uint64(fl.rolloutIdx)*0x9e3779b97f4a7c15))
	rt.CurrentOwnerPlayer = -1
	rt.CurrentOwnerChar = -1
	rt.CurrentContextPlayer = int(game.Turn)
	rt.DeferredFns = nil
	addNS(prof, prof_restoreNS, t0)
	if prof != nil {
		prof.NRestore.Add(1)
	}

	// --- 2. Determinize ---
	t0 = timeIfProf(prof)
	if fl.rolloutIdx < len(input.Determinizations) {
		applyDeterminization(rt, &input.Determinizations[fl.rolloutIdx])
	}
	addNS(prof, prof_determNS, t0)
	if prof != nil {
		prof.NDeterminize.Add(1)
	}

	// --- 3. Descend with VL ---
	descendStart := timeIfProf(prof)
	fl.path = []int32{rootIdx}
	AddVirtualLoss(pool, fl.path)

	depth := 0
	for {
		nodeIdx := fl.path[len(fl.path)-1]
		node := pool.Get(nodeIdx)

		if game.Phase == engine.PhaseGameOver {
			fl.leafIdx = nodeIdx
			fl.terminal = true
			fl.leafValueP0 = terminalZ(game.Winner)
			addNS(prof, prof_descendNS, descendStart)
			return nil
		}

		qt0 := timeIfProf(prof)
		legalIds := LegalActionIds(game)
		addNS(prof, prof_envQueryNS, qt0)
		if prof != nil {
			prof.NEnvQuery.Add(1)
		}
		if len(legalIds) == 0 {
			return fmt.Errorf(
				"rollout %d: non-terminal env has 0 legal actions "+
					"at depth %d — engine deadlock", fl.rolloutIdx, depth)
		}

		if !node.Expanded.Load() {
			// Leaf. Record legal ids + build eval request, optionally
			// random rollout, queue an eval job.
			fl.leafIdx = nodeIdx
			fl.leafTurn = int8(game.Turn)
			fl.legalIds = legalIds
			fl.req = buildEvalRequest(game, input, legalIds)
			fl.resp.Prior = make([]float32, len(legalIds))

			addNS(prof, prof_descendNS, descendStart)

			valueLambda, _ := cfg.EffectiveLambdas()
			if valueLambda < 1.0 {
				rt0 := timeIfProf(prof)
				seed := rng.Uint64()
				remaining := cfg.MaxRolloutDepth - depth
				if remaining < 0 {
					remaining = 0
				}
				winner, steps := randomRollout(rt, seed, remaining)
				addNS(prof, prof_rolloutExtraNS, rt0)
				if prof != nil {
					prof.NRollout.Add(1)
					prof.NRolloutSteps.Add(int64(steps))
				}
				if winner >= 0 {
					fl.rolloutValueP0 = terminalZ(winner)
				} else {
					fl.rolloutValueP0 = 0
				}
				fl.hasRolloutValue = true
			}

			// Queue the leaf eval job and return — caller waits on
			// fl.job.done and then calls commitRollout.
			fl.job = &evalJob{
				req:  &fl.req,
				resp: &fl.resp,
				done: make(chan struct{}),
			}
			if prof != nil {
				prof.NEval.Add(1)
				if prof.evalTracker != nil {
					prof.evalTracker.Observe(fl.req.DynObs, fl.req.Refs, fl.req.Pay)
				}
			}
			sendCh <- fl.job
			return nil
		}

		// Expanded: IS-MCTS D1 — add children for newly-legal
		// actions with uniform placeholder prior (1/n_legal). This
		// matches Python's async production path: its
		// _descend_with_vl appends D1 children with the same
		// uniform placeholder and _commit_parallel_rollout only
		// overwrites priors on the CURRENT leaf's children, never
		// on D1-added ancestors. So this is correctness-equivalent
		// to Python async (training/mcts.py::mcts_search_parallel),
		// which is what production selfplay runs.
		//
		// Earlier Go versions either (a) called the network to get
		// a "real" prior — strictly MORE than Python async does —
		// or (b) tried to aggregate concurrent D1 requests into
		// one RPC. Both lost the race against Python because D1
		// RPCs are a 40% inflation over Python async's RPC count
		// (which is zero). See docs/2_decisions/adr-0004-is_mcts_migration.md.
		if hasNewActions(node, legalIds) {
			added := addNewActionsUniform(pool, node, legalIds)
			if prof != nil && added > 0 {
				prof.ND1Trigger.Add(1)
				prof.ND1NewActions.Add(int64(added))
			}
		}

		// Select + step.
		chosenChildIdx, chosenAction, stepIdx, selErr := selectAndMap(
			pool, node, legalIds, cfg.CPuct, int8(game.Turn))
		if selErr != nil {
			return fmt.Errorf("rollout %d: %w", fl.rolloutIdx, selErr)
		}
		_ = chosenAction

		if game.PendingCardTarget != nil {
			return fmt.Errorf(
				"rollout %d: hit PendingCardTarget — legacy path "+
					"unsupported by MCTS tree", fl.rolloutIdx)
		}

		st0 := timeIfProf(prof)
		rt.CurrentContextPlayer = int(game.Turn)
		game.Step(stepIdx)
		addNS(prof, prof_envStepNS, st0)
		if prof != nil {
			prof.NEnvStep.Add(1)
		}

		fl.path = append(fl.path, chosenChildIdx)
		AddVirtualLoss(pool, []int32{chosenChildIdx})

		if game.Phase == engine.PhaseGameOver {
			z := terminalZ(game.Winner)
			// A terminal outcome belongs to this sampled hidden state, not
			// every determinization sharing this action-history node.
			fl.leafIdx = chosenChildIdx
			fl.terminal = true
			fl.leafValueP0 = z
			addNS(prof, prof_descendNS, descendStart)
			return nil
		}

		depth++
		if depth > cfg.MaxRolloutDepth {
			return fmt.Errorf(
				"rollout %d: exceeded max_rollout_depth=%d",
				fl.rolloutIdx, cfg.MaxRolloutDepth)
		}
	}
}

// commitRollout expands the leaf (if non-terminal) with the eval
// response and backs up the value along the path. Called after the
// eval job's done channel fires (or immediately for terminal leaves).
func commitRollout(
	pool *Pool, fl *inFlightRollout, cfg *Config, prof *Profile,
) {
	ct0 := timeIfProf(prof)

	leaf := pool.Get(fl.leafIdx)
	var leafValueP0 float32
	if fl.terminal {
		leafValueP0 = fl.leafValueP0
	} else {
		vNetActing := fl.resp.Value
		var vNetP0 float32
		if fl.leafTurn == 0 {
			vNetP0 = vNetActing
		} else {
			vNetP0 = -vNetActing
		}

		valueLambda, priorLambda := cfg.EffectiveLambdas()
		if fl.hasRolloutValue && valueLambda < 1.0 {
			leafValueP0 = valueLambda*vNetP0 + (1-valueLambda)*fl.rolloutValueP0
		} else {
			leafValueP0 = vNetP0
		}

		n := len(fl.legalIds)
		children := make([]int32, n)
		actionsCopy := make([]ActionId, n)
		uniform := float32(1) / float32(n)
		for i, lid := range fl.legalIds {
			p := fl.resp.Prior[i]
			if priorLambda < 1.0 {
				p = priorLambda*p + (1-priorLambda)*uniform
			}
			idx, child := pool.Alloc()
			child.Prior = p
			child.Turn = -1
			children[i] = idx
			actionsCopy[i] = lid
		}
		leaf.InstallExpansion(children, actionsCopy, leafValueP0)
	}

	Backup(pool, fl.path, leafValueP0)
	addNS(prof, prof_commitNS, ct0)
	if prof != nil {
		prof.NCommit.Add(1)
	}
}

// Determinize apply, child-set helpers (hasNewActions / selectAndMap /
// addNewActionsUniform), random rollout, buildEvalRequest, profile
// timing helpers, and detRNG live in rollout_helpers.go.
