// paradigm.go — DMC Paradigm impl(adapter.go Paradigm interface 实现)。
//
// Configure 接 JSON cfg(game spec + opp 配置 + max_actions / max_episode_steps),Run
// 跑真 episode loop:
//   - 每 episode 调 factory.NewGame(gameSpec) 构造 engine instance(native Go,~ms 级 init)
//   - 计算 static_hash(每 episode 一次,跨 turn 不变)
//   - 主循环:
//     · acting player == me: BuildInferRequest → InferenceClient.Request → 解码 chosen
//       action idx → engine.Step → push transition
//     · acting player == opp: GreedyPlayer.SelectAction(F1-D2/D4)→ engine.Step
//     · engine.Phase == GameOver: push final transition + break
//   - episode 完结 → new engine instance + 继续(每 episode new engine,P3 优化 reuse)

package dmc

import (
	"context"
	"encoding/json"
	"fmt"
	"math/rand"
	"os"
	"sync"

	"gicg_mono/gicg_actor"
	"gicg_mono/gicg_engine/factory"
)

// DMCConfig — Configure() JSON schema(Python side ParadigmConfigJSON 必须符合)。
//
// GameSpec 走 factory.GameConfig 同 wire 格式(JSON 子树,Configure 把它再 unmarshal 一次到
// factory.GameConfig)— 这样 Python 单一 source of truth 是 ScenarioCfg → factory.GameConfig
// JSON,Go 透传 GameSpec 子树即可,无需第二份 schema。
//
// MyPlayerStrategy 决定 me 在每 episode 是固定 0 / 固定 1 / 随机轮换(`alternate`),
// production 默认 `alternate` 防 position bias。
//
// OpponentMix — per-episode 按权重抽对手类型(mirror cfg [paradigm.dmc.opponent_mix])。
// 权重不必和为 1 — sampleOpponentKind 归一化。 historical 在 Go 路径走当前 net 推理
// (cost-faithful 代理;真 historical-net ring 是 follow-up,见 paradigm.go opp dispatch)。
type OpponentMix struct {
	Random     float64 `json:"random"`
	F1D2       float64 `json:"f1d2"`
	F1D4       float64 `json:"f1d4"`
	Historical float64 `json:"historical"`
	// MinimaxNodeBudget — F1-D4 GreedyPlayer scoreBestResponse 递归 DeepCopy 总数上限
	// (per SelectAction call 共享)。 0 (default) = 无 cap (production 历史行为, D4 完整跑)。
	// > 0 = 超出后停止展开 + 当前节点降级评分 (典型 4000 → D4 capped 到 ~D2.7)。
	// C2 (2026-05-25) cfg-driven 替代 const minimaxNodeBudget=4000 硬码,与 Python
	// `OpponentMixCfg.minimax_node_budget` 共用 wire 字段 (cross-language fair bench
	// parity, R6.3 unfair-bench finding 后续 fix)。
	MinimaxNodeBudget int `json:"minimax_node_budget"`
}

type DMCConfig struct {
	gicg_actor.BaseActorConfig

	// 对手 — 每 episode 按 OpponentMix 权重抽 random / f1d2 / f1d4 / historical。
	OpponentMix OpponentMix `json:"opponent_mix"`

	MyPlayerStrategy string  `json:"my_player_strategy"` // "alternate" | "fixed_0" | "fixed_1"
	Epsilon          float32 `json:"epsilon"`            // ε-greedy explore prob(DMC ~0.05)
}

// DMCParadigm implements gicg_actor.Paradigm。
type DMCParadigm struct {
	cfg     DMCConfig
	gameCfg factory.GameConfig // pre-parsed from cfg.GameSpec for fast-path episode start
}

func (p *DMCParadigm) Name() string {
	return "dmc"
}

// Configure 反序列化 DMCConfig + 预解 GameSpec → factory.GameConfig,fail-loud 任何
// schema / 字段错误。 必须在 actor goroutine spawn 之前调一次。
func (p *DMCParadigm) Configure(jsonCfg string) error {
	if jsonCfg == "" {
		return fmt.Errorf("DMCParadigm.Configure: empty JSON config")
	}
	var c DMCConfig
	if err := json.Unmarshal([]byte(jsonCfg), &c); err != nil {
		return fmt.Errorf("DMCParadigm.Configure: unmarshal DMCConfig: %w", err)
	}
	if err := c.Validate(); err != nil {
		return fmt.Errorf("DMCParadigm.Configure: %w", err)
	}
	if c.OpponentMix.Random+c.OpponentMix.F1D2+c.OpponentMix.F1D4+c.OpponentMix.Historical <= 0 {
		return fmt.Errorf("DMCParadigm.Configure: opponent_mix weights sum must be > 0")
	}
	switch c.MyPlayerStrategy {
	case "alternate", "fixed_0", "fixed_1":
	case "":
		c.MyPlayerStrategy = "alternate"
	default:
		return fmt.Errorf("DMCParadigm.Configure: unknown my_player_strategy=%q", c.MyPlayerStrategy)
	}
	var gameCfg factory.GameConfig
	if err := json.Unmarshal(c.GameSpec, &gameCfg); err != nil {
		return fmt.Errorf("DMCParadigm.Configure: unmarshal game_spec: %w", err)
	}
	p.cfg = c
	p.gameCfg = gameCfg
	return nil
}

// Run — actor goroutine 主循环。 每 episode 算独立 game,直到 ctx.Done() 才退出 outer loop。
//
// infCli 是 InferenceRequester (TCP localhost socket;I29 R7.1 删 SHM inference path)。
// sink 是 TransitionSink (I29 redesign 2026-05-25 interface),TCP path 传 *TransitionWriterTCP
// SHM path 传 *TransitionWriterShm — paradigm 端 encode wire frame 后 sink.Push 透传。
//
// 内存优化 (2026-05-27 Phase 1 — Win N=16 长跑 Go heap 增长 fix):
// `factory.NewGame()` 只调一次,生成 *GameHandle (lua interp + DSL load + char registry +
// IR compile) 跨 episode 复用;每 episode 改调 `rt.ResetDynamicWithSeeds(seed, [seed,seed])`
// 重置 mutable 状态 (counter values, hands, decks, phase, RNG)。 BuildStaticObs +
// ComputeStaticHash 也只算一次 (scenario-static layout 跨 episode 不变)。 GreedyPlayer
// 同 — D2/D4 各一只跨 episode 复用 (已是)。
//
// 适用边界: team_size=1 下 ResetDynamic 行为与 NewGame 等价 (post-reset PhaseAction +
// char 0 = sole choice)。 team_size>=2 时 ResetDynamic auto-select char 0 跳过
// PhaseSelectActive — Stage 4+ 多 char scenario 需先决策保留 SelectActive (注释 capi/
// initGame 同 path,production 验过)。
func (p *DMCParadigm) Run(ctx context.Context, actorID int, infCli gicg_actor.InferenceRequester, sink gicg_actor.TransitionSink) error {
	// Per-actor seed (derived) — 决定 opp tie-break + my-player alternation + ε-greedy explore
	rng := rand.New(rand.NewSource(p.cfg.BaseSeed + int64(actorID)*1009))
	// 对手按 OpponentMix 每 episode 抽 — f1d2 / f1d4 用 GreedyPlayer(F1 features),各
	// depth 建一次跨 episode 复用;random / historical 不需 GreedyPlayer。
	// C2 (2026-05-25): MinimaxNodeBudget cfg-driven (replaces const 4000)。 0 = 无 cap
	// (production 默认 = Python production 同行为);bench cfg 显式设值才 cap。
	budget := p.cfg.OpponentMix.MinimaxNodeBudget
	gpD2, err := NewGreedyPlayer("F1", 2, p.cfg.BaseSeed+int64(actorID)*7919, budget)
	if err != nil {
		return fmt.Errorf("actor=%d: build greedy player D2: %w", actorID, err)
	}
	gpD4, err := NewGreedyPlayer("F1", 4, p.cfg.BaseSeed+int64(actorID)*7919+1, budget)
	if err != nil {
		return fmt.Errorf("actor=%d: build greedy player D4: %w", actorID, err)
	}

	// Engine reuse: 一次构造 GameHandle + 缓存 static obs。 后续每 episode 在 runEpisode
	// 内调 rt.ResetDynamicWithSeeds(seed, [seed,seed]) 复用同 GameHandle。 NewGame 内部:
	// lua Runtime 创建 + DSL load + char declare/bind + system files exec + IR compile +
	// pool resolve — 这些都是 scenario-static, episode 间不变。
	gameCfg := p.gameCfg
	gameCfg.Seed = p.cfg.BaseSeed + int64(actorID)*1_000_003
	h, err := factory.NewGame(gameCfg)
	if err != nil {
		return fmt.Errorf("actor=%d: factory.NewGame: %w", actorID, err)
	}
	// 静态 obs (counter perm / hook perm / scenario layout) — scenario-static, 一次算。
	staticInt32 := h.Game.BuildStaticObs()
	staticHash := ComputeStaticHash(staticInt32)

	clientID := uint32(actorID)
	var episodeID uint32

	// Backpressure stats source — sink 是 SHM impl 时支持 Stats()(TransitionWriterShm)。
	// stderr emit 周期:每 N=50 episode 报一次累计,master 端 Python 解析进 metrics.jsonl
	// "backpressure" kind(go_subprocess._drain_stderr 内联 regex parse)。
	type backpressureSource interface {
		Stats() (pushTotal uint64, pushWaitTotalNs int64, pushDropTimeout uint64)
	}
	bpSrc, _ := sink.(backpressureSource)
	const backpressureEmitEvery = 50

	for {
		select {
		case <-ctx.Done():
			return nil
		default:
		}
		episodeID++
		mePlayer := pickMePlayer(p.cfg.MyPlayerStrategy, int(episodeID))
		opp := sampleOpponentKind(p.cfg.OpponentMix, rng)
		epSpan := gicg_actor.Span("dmc.episode")
		err := p.runEpisode(ctx, h, staticInt32, staticHash, opp, gpD2, gpD4, rng, infCli, sink, clientID, episodeID, mePlayer)
		epSpan.End()
		if err != nil {
			// ctx cancel mid-episode 不算 fatal — outer loop 重新检查 ctx.Done()
			if ctx.Err() != nil {
				return nil
			}
			return fmt.Errorf("actor=%d ep=%d: %w", actorID, episodeID, err)
		}
		// Backpressure metric emit — 每 50 episode 一次,actor 0 也 emit 让 master 早期 see
		// (cold start 后第 1 个 50 ep 的 wait pattern 是 spawn-phase noise,稳态 ≥ ep 50 之后 robust)。
		if bpSrc != nil && episodeID%backpressureEmitEvery == 0 {
			pTotal, pWaitNs, pDrops := bpSrc.Stats()
			fmt.Fprintf(os.Stderr,
				"[gicg_actor backpressure] actor=%d ep=%d push_total=%d push_wait_ms=%.1f push_drops=%d\n",
				actorID, episodeID, pTotal, float64(pWaitNs)/1e6, pDrops)
		}
	}
}

// pickActionEpsilonGreedy — DMC policy: ε prob uniform random over legal, else argmax over
// legal logits。 logits 长度应是 MaxActions(由 InfServer 端 batch padding 决定);只前 nLegal
// 个是合法 action,后面 pad 行 mask 掉。
func pickActionEpsilonGreedy(logits []float32, nLegal int, epsilon float32, rng *rand.Rand) int {
	if nLegal <= 0 {
		return -1
	}
	// nLegal > len(logits) = 网络 action 容量 < 合法动作数(max_actions 配置错)。
	// 旧逻辑静默截断 limit=len(logits) → argmax 只在前 len(logits) 个里选,静默缩小
	// 动作空间。 fail-loud panic —— 这是 systematic 配置 bug,必须立即暴露(I29 T-RR.6)。
	// 校验在 ε 分支**之前** —— 否则 ε-explore 路径(rng.Intn(nLegal))会绕过校验,
	// 同一配置 bug 下 ~95% step 崩、~5% 静默过,fail-loud 变非确定性(review fix)。
	if nLegal > len(logits) {
		panic(fmt.Sprintf("pickActionEpsilonGreedy: nLegal=%d > len(logits)=%d — "+
			"network action capacity < legal action count (max_actions misconfigured)", nLegal, len(logits)))
	}
	if epsilon > 0 && rng.Float32() < epsilon {
		return rng.Intn(nLegal)
	}
	bestIdx := 0
	bestVal := float32(-1e30)
	for i := 0; i < nLegal; i++ {
		if logits[i] > bestVal {
			bestVal = logits[i]
			bestIdx = i
		}
	}
	return bestIdx
}

func pickMePlayer(strategy string, episodeID int) int {
	switch strategy {
	case "fixed_0":
		return 0
	case "fixed_1":
		return 1
	default: // "alternate" — episode parity
		return episodeID & 1
	}
}

// oppKind — 本 episode 的对手类型(由 OpponentMix 权重抽样)。
type oppKind int

const (
	oppRandom     oppKind = iota // 均匀随机合法动作
	oppF1D2                      // GreedyPlayer F1 depth-2 minimax
	oppF1D4                      // GreedyPlayer F1 depth-4 minimax
	oppHistorical                // 走当前 net 推理(cost-faithful 代理;真 historical ring 是 follow-up)
)

// sampleOpponentKind — 按 OpponentMix 权重抽对手。 权重自动归一化(不必和为 1)。
func sampleOpponentKind(mix OpponentMix, rng *rand.Rand) oppKind {
	total := mix.Random + mix.F1D2 + mix.F1D4 + mix.Historical
	r := rng.Float64() * total
	if r < mix.Random {
		return oppRandom
	}
	r -= mix.Random
	if r < mix.F1D2 {
		return oppF1D2
	}
	r -= mix.F1D2
	if r < mix.F1D4 {
		return oppF1D4
	}
	return oppHistorical
}

// runEpisode 跑一个完整 episode。 me 决定 actor (network) 的 player_idx,opp 是另一边。
//
// h: 跨 episode 复用的 GameHandle (Run 内一次 factory.NewGame, runEpisode 每 episode 调
// rt.ResetDynamicWithSeeds 重置 mutable state)。 staticInt32 / staticHash: scenario-static,
// 由 Run 一次算出传入。

// 一次性 register(package init 触发)+ mutex 防 重复 import 时 race。 Real-world 单 process
// 单一 init() 调用,但 test helper 可能多次 Reset → 重新 register。
var (
	registerOnce sync.Once
)

func init() {
	registerOnce.Do(func() {
		gicg_actor.RegisterParadigm("dmc", &DMCParadigm{})
	})
}
