package engine

// RewardEvents is a per-player accumulator of "what happened" signals
// produced during play. It is NOT reward shaping — the engine stays
// ignorant of any scoring formula per the engine-ignorance rule. The
// struct only records raw occurrences; any consumer (Python RL /
// GreedyPlayer / diagnostics) maps these to a scalar score on its own
// terms.
//
// Lifecycle:
//   - Zeroed by ResetDynamicState (new episode starts fresh).
//   - DeepCopy and RestoreFrom carry RewardAccum so speculative
//     rollouts measure their own deltas correctly — critical for
//     GreedyPlayer depth>=2 correctness where a snapshot/restore
//     cycle brackets a simulated action.
//   - GameResetReward (capi) zeroes all 14 fields. Consumers wanting
//     a per-step delta should read → process → reset between steps.
//
// Field order here is load-bearing: the capi export writes them to an
// out buffer in index order (see GameGetRewardEvents). Both the Go
// tests and the Python wrapper read the same layout, so reordering
// fields is a breaking change.
type RewardEvents struct {
	DamageDealt        int // damage actually subtracted from an enemy HP counter
	DamageReceived     int // damage actually subtracted from an own HP counter
	HealDone           int // healing applied to one of my chars
	EnemyHealDone      int // healing applied to an enemy char (credited to the watcher)
	ShieldAbsorbed     int // damage absorbed by my shields (before reaching HP)
	DamageBlocked      int // damage I tried to deal that my opponent's shields absorbed
	Kills              int // enemy chars killed this episode so far (resets-safe via Reset)
	TotalKills         int // cumulative kills (alias of Kills within a single episode; not per-step)
	Deaths             int // own chars that died this episode so far
	TotalDeaths        int // cumulative deaths within the episode
	ReactionsTriggered int // elemental reactions I triggered on enemy targets
	ReactionsReceived  int // elemental reactions triggered on my chars
	APWasted           int // AP unused at round end (reserved slot — engine doesn't track AP)
	EnergyOverflow     int // energy gain that would have exceeded cap (reserved slot — engine auto-clamps silently)
}

// RewardEventsFieldCount is the number of int fields in RewardEvents,
// asserted by the capi exporter's out-buffer size contract. Exported
// as a named constant so Python-side buffer sizing stays in sync.
const RewardEventsFieldCount = 14
