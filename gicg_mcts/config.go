package mcts

// Config mirrors training/mcts.py::MCTSConfig. Received as JSON string
// from Python via the cgo entry point and unmarshaled here.
//
// Field names (JSON tags) must match the Python dataclass attribute
// names so the Python-side `json.dumps(cfg.__dict__)` round-trips.
type Config struct {
	NRollouts             int     `json:"n_rollouts"`
	CPuct                 float32 `json:"c_puct"`
	DirichletAlpha        float32 `json:"dirichlet_alpha"` // unused on Go side (Python adds noise)
	DirichletEps          float32 `json:"dirichlet_eps"`   // unused on Go side
	Temperature           float32 `json:"temperature"`     // unused on Go side (visit sampling in Python)
	TemperatureSwitchStep int     `json:"temperature_switch_step"`
	MaxRolloutDepth       int     `json:"max_rollout_depth"`

	// Parallel rollouts — number of goroutines tugging at the shared tree.
	ParallelRollouts int `json:"parallel_rollouts"`

	// AlphaGo-mode leaf mixing (value = λ·V_net + (1-λ)·z_rollout).
	// If LambdaAnnealGames > 0, overrides the static values below at
	// compute_lambda() time based on GameIdx.
	ValueMixLambda    float32 `json:"value_mix_lambda"`
	PriorMixLambda    float32 `json:"prior_mix_lambda"`
	LambdaAnnealGames int     `json:"lambda_anneal_games"`
	LambdaStart       float32 `json:"lambda_start"`
	LambdaEnd         float32 `json:"lambda_end"`

	// Current self-play game index (0..n_games-1), used by lambda
	// anneal. Python sets this per-search before calling.
	GameIdx int `json:"game_idx"`

	// If true, Go side records a full MCTSProfile and returns it as
	// JSON. Overhead ~1μs per timed point, negligible.
	Profile bool `json:"profile"`

	// Virtual loss magnitude, in integer visits. Python is effectively
	// 1 (child.N_virtual += 1). Configurable here for ablation.
	VirtualLoss int32 `json:"virtual_loss"`
}

// EffectiveLambdas returns the (value, prior) λ for this search based
// on anneal schedule if active. Mirrors compute_annealed_lambda in
// training/mcts.py.
func (c *Config) EffectiveLambdas() (valueLambda, priorLambda float32) {
	if c.LambdaAnnealGames <= 0 {
		return c.ValueMixLambda, c.PriorMixLambda
	}
	t := float32(c.GameIdx) / float32(c.LambdaAnnealGames)
	if t > 1.0 {
		t = 1.0
	}
	annealed := c.LambdaStart + t*(c.LambdaEnd-c.LambdaStart)
	return annealed, annealed
}
