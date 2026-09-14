# Verification

The implemented lifecycle and reproduced-fault repair scope is verified.
Passing these tests does not certify the formal card pool or every DSL mechanism.

## Current acceptance status (2026-09-11)

- Final combined engine/MCTS/actor race verification passed
  (`/private/tmp/gicg-final-native-race.log`).
- Rebuilt native library: environment and four MCTS integration modules passed
  177 tests (`/private/tmp/gicg-final-native-python.log`).
- The subsequent GameClone error-code correction passed both rule-error tests,
  including an independent raw ctypes call returning -1 on failure
  (`/private/tmp/gicg-clone-abi-after.log`).
- Build, formatting, whitespace and OpenSpec index checks passed as recorded below.
- Full Python regression session 21856 exited successfully: 1208 passed,
  6 skipped, 22 warnings in 3417.11 seconds
  (`/private/tmp/gicg-final-training.log`). Its loaded library predates later
  native changes, which have the separate focused evidence above.
- The longest test was TestMinimaxBudget.test_budget_uncapped_equals_old_const
  (3380.13 seconds); the next longest took 12.06 seconds. The long wait was a
  completed uncapped minimax comparison, not a stuck worker.
- All 22 warnings concern PyTorch JIT deprecation under Python 3.14.
  Six skip conditions are three unavailable historical r009-checkpoint tests,
  unavailable nvidia-smi, a Windows-only load-average fallback, and CPU affinity
  unsupported on macOS. These do not certify the unavailable platforms/artifact.
- Formal card-pool certification and independent rule-oracle comparison remain
  follow-up scope. Pending-input portable checkpoints are unsupported; in-process
  snapshots and managed continuation are covered by this change.

The following sections retain chronological evidence. Statements that a check
was still required describe that revision; the current status above takes precedence.

## Completion audit

| Requirement | Implementation and exercised evidence |
| --- | --- |
| Field ownership and complete snapshots | game_clone/game_snap; lifecycle_inventory and runtime_inventory; lifecycle_regression and game_snap_pool tests |
| Equipment isolation and reset | Per-game SpecialtyCardRef; actual-card clone/restore/reset and reset/new equality tests |
| Exact random restore and explicit search sampling | random.go and MCTS determinization; random_lifecycle, Python snapshot trajectories and MCTS integration tests |
| Deferred effects and input continuation | continuation.go/effect.go; deferred_lifecycle, deferred_input_resume, continuation_branch, native_effect and actual-DSL Python tests |
| Exact replay and atomic rejection | checkpoint and record modules; checkpoint, replay_inputs, continuation_replay, strict parsing and legacy_target tests |
| Shared DSL definitions remain immutable | env_immutable; direct/table/alias mutation rejection and writable hook-local regressions |
| Visible errors across engine/search/native/Python | rule_error and search_failure; recursion, search_error and raw ctypes/Python rule-error tests |
| Complete model rule input | IR lambda boundaries, 128-op capacity and strict layout validation; IR/factory/layout tests and full training regression |
| Integration and repository gates | Combined Go race suite, native build, 177 Python integration tests, 1208-test full suite, formatting/index/whitespace checks |

Skip audit repeated the three relevant modules with `-rs`: 18 passed, 6 skipped
(`/private/tmp/gicg-final-skips.log`). The first sandboxed audit could not read
process metadata via sysctl; the permission-matched rerun passed. No production
code or test assertions were changed to accommodate the sandbox.

## Earlier evidence (2026-09-11)

- `GOCACHE=/private/tmp/gicg-review-go-cache go test ./gicg_engine/... ./gicg_mcts/...`
  passed after replay input and active-slot repairs (`/private/tmp/gicg-lifecycle-go8.log`).
- Earlier lifecycle revision passed `go test -race` over engine, MCTS and actor.
  Replay changes made afterward still require final race verification.
- Rebuilt the C shared library after active-slot repairs. Python environment
  suite and four MCTS integration modules passed 174 tests
  (`/private/tmp/gicg-lifecycle-python3.log`).
- New replay regression exercises seeds 7, 42 and 1337 against a receiver
  initialized with seed 999, checks every recorded input and resulting counters
  and payment totals within the first round.

## Repaired replay faults

Exports now record the random protocol, base seed, fixed dice and round limit.
Unsupported protocols are rejected. Legacy records lacking this metadata remain
readable but cannot be asserted to reproduce the original random stream.

Action records include exact dice payment, duplicate-card hand slot, joint
target, forced-switch flag and tune source color. Tuning is included in the
action count. Raw DSL active counters are preserved separately from engine
active-character slots. Draw winners parse as player index 2, not 0.

## Correctness work and intermediate verification

- New round-start records now carry full gameplay checkpoints, including all
  counters, supports, preparing, equipment, card-instance metadata, reward
  bookkeeping and all three random states. Legacy projections remain incomplete.
- Checkpoint import validates format/protocol, registry layout and ordered,
  slot-bound DSL source digest. Engine build pinning remains caller-owned.
- Load validates on a private runtime clone before committing; failure is atomic
  for both checkpoint and legacy paths. New tests reject corrupted checkpoints
  and unknown legacy cards without changing the receiver.
- A complete multi-round game is replayed at every non-pause action prefix in
  reverse order against a differently seeded receiver. Canonical full checkpoint
  bytes match, including after restoring from terminal to earlier live states.
  All engine/MCTS packages passed after these changes (`gicg-lifecycle-go11.log`).
- Rebuilt C library and repeated the environment + four MCTS modules: 174 tests
  passed (`gicg-lifecycle-python4.log`). Python snapshot trajectory test now
  compares every observable after every action of two complete restored games,
  replacing the obsolete independent-RNG-on-restore assumption.
- Legacy StepTarget and deferred-input recording/resumption now have dedicated
  regressions. Native compound effects use ExecuteEffect; unmanaged input fails
  explicitly (details below).
- Replay/config/checkpoint JSON now rejects missing fields, duplicate keys,
  case aliases, null scalar values, wrong fixed-array lengths, unknown fields
  and trailing data. Parsing is atomic. Action payment/target/hand/tune fields
  are validated; unknown actions/round sections, duplicate sections and broken
  round numbering fail instead of being skipped.
- Legacy state literals now reject malformed brackets, duplicate keys/characters
  and nonnumeric counter values. New checkpoints are cross-checked against their
  human-readable state projection before committing a load. Regression tests
  cover both rejection and unchanged receiver state; full engine/MCTS packages
  pass (`gicg-strict-replay6.log`).
- IR export now includes lambda bodies with boundaries and refuses overflow.
  Existing system rules required 66 and 76 ops, exceeding the prior 64-op slot;
  capacity and production configs are now 128. Factory rejects every compile
  failure, including rates below the former 2% threshold. Go engine/MCTS packages
  and dedicated lambda/overflow regressions passed; environment/MCTS Python
  integration passed 174 tests (`gicg-ir-python.log`).
- Full training regression encountered sandbox-denied shared memory; a specific
  failing CFR test confirmed `shm_open` PermissionError. That run was interrupted;
  a fresh four-worker suite is running with approved shared-memory/local-port
  permissions (`gicg-training-unrestricted.log`).
- DSL runtime failures now propagate as typed RuleError across Go and C/Python;
  failed games reject further observation/action/snapshot consumption until
  reset. Native C return-code and Python exception/reset tests both pass.
- Strict execution exposed two previously swallowed card errors: preparing
  歼灭机关 referenced nonexistent `energy`; 铁枪 stored a SkillRef in an integer
  counter. Both are repaired and exact energy/damage regressions pass.
- Search error tests cover rule failure and send/receive callback failure with
  more queued work than channel capacity. Failures return without deadlock and
  preserve the live game. A race run exposed retained empty event-stack backing
  storage shared by clones and mutable shared Node.Turn; both are repaired.
  Engine + MCTS race tests pass (`gicg-rule-race2.log`). Actor race tests passed
  in the preceding run; final all-component verification is still required.
- Rebuilt the C shared library after these repairs; environment and four MCTS
  integration modules pass 176 tests (`gicg-rule-python5.log`).
- Managed deferred-input continuation, native entry-point audit and strict replay
  validation are implemented; final full-training verification remains running.
- Update snapshot/search contracts and CFR randomness assumptions; finish
  Python/search integration, formatting and final verification.

## Continuation audit follow-up

- Counter-write and damage recursion previously returned normally when exceeding
  MaxDepth, silently discarding effects. Both now abort with sticky RuleError;
  counter and damage recursion regressions verify typed failure, stack-depth
  unwinding and explicit reset recovery. Engine/MCTS packages passed after this
  repair (`gicg-recursion-after.log`, before adding the following known failures).
- New `TestDeferredInput_*` regressions initially failed: a lethal skill continued the later hook and
  flipped the turn while a replacement was pending (marker=1, turn=1). A round-end
  pending choice advanced into round-pause checkpoint export and panicked because
  pending-input checkpoints are unsupported (`gicg-deferred-input-before.log`).
- The required fix must preserve the whole continuation, including caller
  effects and phase transitions, across target selection and repeated snapshot
  restoration. Retaining only the deferred queue cannot satisfy these tests.
  Reexecuting the preceding action from a root snapshot also needs a separate
  hidden-state/search audit: resampling a waiting branch must not be overwritten
  by restoring an older hidden state.
- Managed decision operations now reconstruct their suspended call stack and
  restore each branch's current state at the matching input boundary. Skill and
  round-end suspension regressions pass. Repeated-input tests cover independently
  changed RNGs, hands and decks at two successive choices, repeated restores,
  concurrent runtime clones and nonduplicated action/damage logs.
- Full engine/MCTS packages passed (`gicg-continuation-all.log`); engine/MCTS
  race packages passed (`gicg-continuation-race.log`). Actor race tests needed
  loopback-listener permission and passed separately with that permission
  (`gicg-continuation-actor-race.log`). New-round action-query repetition then
  passed the focused continuation suite (`gicg-continuation-roundstart.log`).
- Rebuilt the C library: environment + four MCTS modules passed 176 tests
  (`gicg-continuation-python.log`). A new actual-DSL Python continuation test
  passes clone, repeated restore and invalid-target checks
  (`gicg-continuation-dsl2.log`). It also exposed a missing `request_switch` IR
  token; the builtin now has a distinct stable token (311), so its rule remains
  visible to the model.
- Environment + four MCTS modules repeated with the new DSL continuation test:
  177 passed (`gicg-continuation-python2.log`).
- The earlier full-training process completed successfully: 1073 passed, 6 skipped
  in 3139.75 seconds (`gicg-training-unrestricted.log`). It predates continuation
  changes and proves the earlier observation-capacity migration, not this revision.
- The final full environment/training regression ran as session 21856 with
  local IPC permission and one math-library thread per worker, and passed
  1208 tests (`gicg-final-training.log`). The loaded C library includes legacy-target
  repairs but predates the subsequently added shared-definition write protection.
- Legacy card target selection now preserves AppliedMods in execution, target
  checks and deep snapshots. Step and StepTarget resolve the same already-paid
  card. Incomplete new records remain waiting instead of inventing target 0.
  Exact checkpoint replay tests and round-end non-default forced-switch prefix
  tests pass (`gicg-target-replay.log`).
- Loaded DSL lexical bindings and tables are now protected against mutation.
  Regressions reject direct, indexed, aliased and enum-table writes without
  poisoning the source game; hook-local captured variables remain writable.
  Three diagnostic test helpers now use private lexical scopes rather than
  writing temporary variables into shared definitions. Full engine/MCTS race
  tests pass (`gicg-definitions-race.log`).
- Rebuilt the C library with shared-definition protection; environment and four
  MCTS integration modules pass 177 tests (`gicg-definitions-python.log`).
- CFR ES was audited: it restores exact engine chance state for sibling actions;
  the policy RNG is separate, and the serial collector supplies a fresh seeded
  environment per traversal. The code now documents that choice; no implicit
  RNG-advancing restore is assumed. This is an interface audit, not an algorithm
  convergence claim.

## Final entry-point audit

- Source search found no direct DealDamage/Heal/WriteCounter/PushEvent/
  FireEventHooks/DeferAction/DrainDeferred callers in gicg_actor, gicg_mcts or
  gicg_engine/capi. Training/search already enter through managed decisions.
- ExecuteEffect(frame, fn) now supplies the same continuation guarantee to native
  compound effects. Tests resume those effects through independent runtime clones.
  Unmanaged required input raises sticky RuleError before subsequent work;
  requests with no legal replacement fail explicitly, and terminal games do not
  ask for queued input. The active-death low-level fixture now uses ExecuteEffect.
- Full engine/MCTS packages pass (`gicg-native-effects2.log`). The combined final
  engine/MCTS/actor race command passes with local-listener permission
  (`gicg-final-native-race.log`). Rebuilt C library and repeated environment plus
  four MCTS integration modules: 177 passed (`gicg-final-native-python.log`).
- Changed/new Go files are gofmt-clean, Python files are ruff-format-clean after
  fixing one edited fixture, OpenSpec indexes and git diff whitespace checks pass.
  The line-limit audit reports eight modified files already over their limits at
  HEAD; no new file or newly crossing file exceeds its limit. These retain the
  repository's documented existing-file exception.
- `GOCACHE=/private/tmp/gicg-review-go-cache go build ./...` passes
  (`gicg-final-build.log`).
- Final native ABI audit reproduced GameClone returning default handle 0 after
  a RuleError. It now uses the integer error recovery path and returns -1.
  An independent ctypes.CDLL regression (without Python errcheck) failed before
  the fix and passes afterward; both rule-error tests pass
  (`gicg-clone-abi-before.log`, `gicg-clone-abi-after.log`).
- Full Python regression session 21856 completed without restart or interruption.
  Earlier native sampling showed engine observation/action calls and Go GC
  (`gicg-pytest-stack.txt`); the final duration report identifies the uncapped
  minimax comparison as the source of the long wait.
