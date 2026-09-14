# Design

## State ownership

Ruleset / Hook definitions and declaration metadata are immutable. Dynamic
card occupancy belongs to Game, alongside characters and zones. Loaded lexical
environments and their tables are read-only from DSL assignments. Runtime
mutation of shared definitions fails with RuleError; hook-local scopes remain
writable, including locals captured by a deferred closure. Action
copies must clone AppliedMods, not only the containing struct.

DeepCopy and pooled snapshots capture the same dynamic state. Restore validates
ruleset identity and shapes before mutation; incompatible restores fail loudly.
Snapshots are supported only at quiescent decision boundaries. Diagnostic
event logs are deliberately outside rollback state (callers suspend logs during
search); that exception does not permit gameplay fields to be omitted.

## Randomness

Owned, cloneable RNG state replaces implicit Int63-based forking. Snapshot
creation is read-only; restoring the same snapshot produces the same future
random events. Search obtains independent randomness explicitly after restore.
Changing the random protocol invalidates seed-only comparisons to older builds;
reproducibility records must include the engine revision/random protocol.

## Deferred effects

Drain after after-damage handlers and before closing action frames. Reacquire
the queue by stack index after callbacks: nested PushEvent can reallocate the
stack and invalidate a saved pointer. Tests exercise appended callbacks and
nested damage, not only a boolean callback in isolation.

Managed Step, StepTarget, NewRound, EndPhase, ResolvePreparing and ExecuteEffect operations now
have an input continuation driver. On required input it unwinds synchronous
engine/interpreter calls into a quiescent waiting state. Immutable reconstruction
data contains the pre-operation snapshot and the state/choice at each later
input boundary. Resumption rebuilds the original call stack deterministically,
then installs the recorded branch state at each input boundary before applying
the choice. This preserves hidden-state determinization, RNG reseeding and
per-step reward resets performed by a caller while waiting. It does not replace
the branch with the original operation's hidden state.

Waiting snapshots share immutable history, not callbacks or stack frames. Each
execution owns its cursor and rebuilt scratch; cloned runtimes rebind their DSL
callbacks normally. Source log prefixes are rewound before reconstruction so
effects/choices appear exactly once. Hooks must keep mutable gameplay in Game,
not external side effects or shared lexical definitions; reconstruction cannot
undo external I/O. Portable checkpoints still reject pending input. Native
compound effects use ExecuteEffect(frame, fn), whose body resolves mutable state
through its Game argument. A manually pushed frame alone cannot suspend its
caller's Go stack: required input outside the driver fails with RuleError.
Unanswerable switch requests also fail explicitly. Terminal games discard
remaining deferred work without requesting new choices.

## Validation

DSL hook execution failures abort with a typed RuleError carrying round, player,
hook ID and source. Failure stays on the game until reset; legal actions,
observations, rewards and snapshots cannot be consumed from a failed game.
The C boundary catches only RuleError (not programming panics), exposes
GameGetRuleError, and returns -1 from step/count/rollout failure paths. Python
raises RuntimeError immediately and allows explicit reset/free afterward.

Search failures discard the search result and drain worker/dispatcher queues so
an early failure cannot leave a producer blocked. Failed speculative runtimes
do not poison the live game. Search turn perspective and terminal value belong
to each sampled rollout, not shared action-history nodes.

Rule observation export includes MainOps and every deferred lambda. An
observation-only OpLambda (14) delimiter records lambda index and body length;
branch coordinates remain local to each body. The per-hook capacity is 128 ops
(previously 64, which truncated existing 66/76-op system rules). Export rejects
overflow before writing. Factory construction rejects any compilation failure,
with source/hook diagnostics; no percentage of missing rules is tolerated.

Production shape defaults and TOML configs use 128. Static observation consumers
validate their exact configured stride before slicing. Existing 64-op model
checkpoints are incompatible with the expanded input; they must not silently
reinterpret two halves of one hook as two different rules.

Tests derive expected state and event order independently from production
calculations. Exercise direct Game APIs, actual DSL card actions and the Python
binding. Standard test success does not certify unimplemented formal cards.
