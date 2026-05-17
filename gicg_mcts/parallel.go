package mcts

import (
	"fmt"
	"runtime/debug"
	"sync"
)

// RolloutFunc runs one MCTS rollout end-to-end. Implementations handle:
//
//  1. Restore engine state to root snapshot
//  2. Apply fresh determinization (opp hand/deck/dice)
//  3. Descend tree via PUCT (adding virtual loss)
//  4. Expand leaf (eval callback)
//  5. Rollout to terminal (λ mixing if configured)
//  6. Backup + revert virtual loss
//
// The function owns its own RNG (seeded per-rollout so parallelism
// doesn't break determinism at the rng level). rolloutIdx is the
// global [0, n_rollouts) index for seed derivation.
//
// Panics inside RolloutFunc are recovered by the coordinator; the
// rollout's virtual-loss contributions must be left untouched
// (caller's defer-based recovery walks the path).
type RolloutFunc func(rolloutIdx int) error

// RunRollouts coordinates n_rollouts concurrent rollouts across
// `parallel` goroutines. Each goroutine pulls rollout indices from
// a shared channel until exhausted. Panics in any rollout are logged
// to the returned error list but don't abort siblings.
//
// Guarantees on return:
//   - All goroutines have exited
//   - Tree mutations are consistent (rolloutFunc handled its own
//     atomic backup + VL revert via defer)
func RunRollouts(nRollouts, parallel int, rolloutFunc RolloutFunc) []error {
	if nRollouts <= 0 {
		return nil
	}
	if parallel <= 0 {
		parallel = 1
	}
	if parallel > nRollouts {
		parallel = nRollouts
	}

	workCh := make(chan int, parallel*2)
	errs := make([]error, 0)
	var errsMu sync.Mutex

	var wg sync.WaitGroup
	for g := 0; g < parallel; g++ {
		wg.Add(1)
		go func(goroutineID int) {
			defer wg.Done()
			for rolloutIdx := range workCh {
				func() {
					defer func() {
						if r := recover(); r != nil {
							errsMu.Lock()
							errs = append(errs, fmt.Errorf(
								"rollout %d panic: %v\n%s",
								rolloutIdx, r, debug.Stack(),
							))
							errsMu.Unlock()
						}
					}()
					if err := rolloutFunc(rolloutIdx); err != nil {
						errsMu.Lock()
						errs = append(errs, fmt.Errorf("rollout %d: %w", rolloutIdx, err))
						errsMu.Unlock()
					}
				}()
			}
		}(g)
	}

	// Feed work then close
	for i := 0; i < nRollouts; i++ {
		workCh <- i
	}
	close(workCh)

	wg.Wait()
	return errs
}

// DeriveRolloutSeed derives a per-rollout seed from (master seed,
// rollout index). Uses golden-ratio mixing to avoid lattice patterns
// when rollout_idx is sequential. Same (master, idx) always produces
// the same seed → determinism test hooks.
func DeriveRolloutSeed(master uint64, rolloutIdx int) uint64 {
	const goldenRatio = 0x9E3779B97F4A7C15
	return master ^ (uint64(rolloutIdx) * goldenRatio)
}
