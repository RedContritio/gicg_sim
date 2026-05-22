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
	engine "gicg_mono/gicg_engine"
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
func (p *DMCParadigm) Run(ctx context.Context, actorID int, infCli *gicg_actor.InferenceClient, transWri *gicg_actor.TransitionWriter) error {
	// Per-actor seed (derived) — 决定 opp tie-break + my-player alternation + ε-greedy explore
	rng := rand.New(rand.NewSource(p.cfg.BaseSeed + int64(actorID)*1009))
	// 对手按 OpponentMix 每 episode 抽 — f1d2 / f1d4 用 GreedyPlayer(F1 features),各
	// depth 建一次跨 episode 复用;random / historical 不需 GreedyPlayer。
	gpD2, err := NewGreedyPlayer("F1", 2, p.cfg.BaseSeed+int64(actorID)*7919)
	if err != nil {
		return fmt.Errorf("actor=%d: build greedy player D2: %w", actorID, err)
	}
	gpD4, err := NewGreedyPlayer("F1", 4, p.cfg.BaseSeed+int64(actorID)*7919+1)
	if err != nil {
		return fmt.Errorf("actor=%d: build greedy player D4: %w", actorID, err)
	}

	clientID := uint32(actorID)
	var episodeID uint32

	for {
		select {
		case <-ctx.Done():
			return nil
		default:
		}
		episodeID++
		mePlayer := pickMePlayer(p.cfg.MyPlayerStrategy, int(episodeID))
		opp := sampleOpponentKind(p.cfg.OpponentMix, rng)
		if err := p.runEpisode(ctx, opp, gpD2, gpD4, rng, infCli, transWri, clientID, episodeID, mePlayer); err != nil {
			// ctx cancel mid-episode 不算 fatal — outer loop 重新检查 ctx.Done()
			if ctx.Err() != nil {
				return nil
			}
			return fmt.Errorf("actor=%d ep=%d: %w", actorID, episodeID, err)
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

// episodeStaticTracker 跟踪 episode 的 static_obs 是否已附带到某条已 push 的
// transition。 每 episode 第一条被 push 的 transition 携带 raw static int32,
// 后续 take 返 nil(NStatic=0,Python assembler 走 hash cache)。
//
// 不能用 episode step 判定 —— transition 只在 me 回合 push,对手先手时 step 0
// 不 push,static 会丢(assembler cache miss → 丢 episode,I29 T-R3 bug)。
type episodeStaticTracker struct{ sent bool }

// take 返回应附带到本条 transition 的 static obs:首次调用返回 static 本身并标记
// sent,之后返回 nil。
func (t *episodeStaticTracker) take(static []int32) []int32 {
	if t.sent {
		return nil
	}
	t.sent = true
	return static
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
func (p *DMCParadigm) runEpisode(
	ctx context.Context,
	opp oppKind,
	gpD2, gpD4 *GreedyPlayer,
	rng *rand.Rand,
	infCli *gicg_actor.InferenceClient,
	transWri *gicg_actor.TransitionWriter,
	clientID, episodeID uint32,
	me int,
) error {
	// Per-episode seed: derive from clientID + episodeID so multi-actor / multi-episode
	// 分布唯一(seed collision = duplicate game = wasted compute)
	gameCfg := p.gameCfg
	gameCfg.Seed = int64(clientID)*1_000_003 + int64(episodeID)*7919
	h, err := factory.NewGame(gameCfg)
	if err != nil {
		return fmt.Errorf("factory.NewGame: %w", err)
	}
	g := h.Game
	rt := h.RT

	// static_obs 缓存(整 episode 不变)+ hash 派生。 第一次 acting==me request 携带
	// raw static int32 数组喂 InfServer cache,后续 request Static=nil(server 走
	// hash lookup)。 InfServer 同 scenario 多 actor 共享 cache 命中率高,后续 N-1 个
	// request 节省 ~12 KB/req(static_obs 平均尺寸)。
	staticInt32 := g.BuildStaticObs()
	staticHash := ComputeStaticHash(staticInt32)
	staticSentThisEpisode := false
	// transition 侧 static:第一条被 push 的 transition 携带 static(详 episodeStaticTracker)。
	var staticTracker episodeStaticTracker

	var step uint32
	var reqID uint32
	var pushedAny bool
	for step = 0; step < uint32(p.cfg.MaxEpisodeSteps); step++ {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		if g.Phase == engine.PhaseGameOver {
			break
		}
		acting := g.ActingPlayer()
		var chosen int
		var pushTrans bool
		// preStep* 在 actor turn 时捕获 pre-step obs/refs/pay/n_legal,Step 之后 push
		// transition 用(Python DMC trainer 需 pre-step state + chosen action + post-step
		// reward 重建 DmcTransition)。 opp turn 时 nil — 不 push transition for opp。
		var preStepDyn []float32
		var preStepRefs []int64
		var preStepPay []float32
		var preStepNLegal int
		if acting == me {
			if infCli == nil {
				return fmt.Errorf("inference client nil on actor turn")
			}
			reqID++
			req := BuildInferRequest(g, staticHash, clientID, reqID, p.cfg.MaxActions)
			if !staticSentThisEpisode {
				req.Static = staticInt32
				staticSentThisEpisode = true
			}
			resp, err := infCli.Request(req)
			if err != nil {
				return fmt.Errorf("inference request step=%d: %w", step, err)
			}
			if resp.Status != gicg_actor.InferStatusOK {
				return fmt.Errorf("inference status err: %s", resp.ErrMsg)
			}
			actions := g.GetLegalActions()
			chosen = pickActionEpsilonGreedy(resp.Logits, len(actions), p.cfg.Epsilon, rng)
			if chosen < 0 || chosen >= len(actions) {
				return fmt.Errorf("action selection produced out-of-range idx=%d (n=%d)", chosen, len(actions))
			}
			// 捕获 pre-step state for transition push(BuildInferRequest 已算了 dyn/refs/pay,
			// 复用 req fields 而非二次算 — 跟 inference 用同一份 obs guarantee 一致)。
			preStepDyn = req.DynObs
			preStepRefs = req.Refs
			preStepPay = req.Pay
			preStepNLegal = len(actions)
			pushTrans = transWri != nil
		} else {
			oppActions := g.GetLegalActions()
			if len(oppActions) == 0 {
				return fmt.Errorf("opp step=%d: no legal actions", step)
			}
			switch opp {
			case oppRandom:
				chosen = rng.Intn(len(oppActions))
			case oppF1D2:
				c, err := gpD2.SelectAction(rt)
				if err != nil {
					return fmt.Errorf("opp f1d2 step=%d: %w", step, err)
				}
				chosen = c
			case oppF1D4:
				c, err := gpD4.SelectAction(rt)
				if err != nil {
					return fmt.Errorf("opp f1d4 step=%d: %w", step, err)
				}
				chosen = c
			case oppHistorical:
				// historical 对手走当前 net 推理(cost-faithful 代理;真 historical-net
				// ring 是 follow-up)。 opp 回合不 push transition。
				if infCli == nil {
					return fmt.Errorf("opp historical step=%d: inference client nil", step)
				}
				reqID++
				oppReq := BuildInferRequest(g, staticHash, clientID, reqID, p.cfg.MaxActions)
				if !staticSentThisEpisode {
					oppReq.Static = staticInt32
					staticSentThisEpisode = true
				}
				oppResp, err := infCli.Request(oppReq)
				if err != nil {
					return fmt.Errorf("opp historical inference step=%d: %w", step, err)
				}
				if oppResp.Status != gicg_actor.InferStatusOK {
					return fmt.Errorf("opp historical inference status: %s", oppResp.ErrMsg)
				}
				chosen = pickActionEpsilonGreedy(oppResp.Logits, len(oppActions), p.cfg.Epsilon, rng)
			}
		}

		g.Step(chosen)

		if pushTrans {
			// 所有 in-loop transition Done=false / reward=0 —— episode 终结由 loop 后的
			// terminal marker 统一表达(详下方 marker 注释)。
			// 第一条被 push 的 transition 携带 static_obs raw int32;后续 NStatic=0 由
			// Python 端 cache by static_hash 解。 用 staticTracker 而非 step==0 —— transition
			// 只在 me 回合 push,对手先手时 step 0 不 push(详 episodeStaticTracker)。
			staticForTrans := staticTracker.take(staticInt32)
			payload := EncodeDmcTransitionPayload(
				uint32(chosen), step, 0, preStepNLegal,
				preStepDyn, preStepRefs, preStepPay, staticForTrans, staticHash,
			)
			tx := &gicg_actor.Transition{
				ClientID:  clientID,
				EpisodeID: episodeID,
				Step:      step,
				Done:      false,
				Payload:   payload,
			}
			if err := transWri.Push(tx); err != nil {
				// Push 失败(socket 抖动 / consumer 慢到超 transitionWriteTimeout)——
				// 不致死 actor。 本 episode 中止:已 push 的 transition 成 orphan(无
				// terminal marker),Python assembler 在途上限会驱逐之。 TransitionWriter
				// .Push 内含 lazy 重连,下个 episode 首 Push 自动重拨。 actor 继续跑下个
				// episode(I29 T-RR.3 audit #5/#12:fire-and-forget 通道瞬时写失败不该
				// 把 actor 当 fatal 杀掉 → 不可逆减员)。
				fmt.Fprintf(os.Stderr, "[gicg_actor] actor=%d ep=%d transition push failed @ step=%d "+
					"— episode aborted, actor continues: %v\n", clientID, episodeID, step, err)
				return nil
			}
			pushedAny = true
		}
	}

	// Episode 终结 marker:loop 退出后(GameOver 或 MaxEpisodeSteps 截断)推一条
	// Done=true 的 terminal transition。 必须独立于 in-loop push —— transition 只在 me
	// 回合 push,对手打出致命一击 / 截断时最后一条 me-transition 不是终局,旧逻辑整个
	// episode 无 Done=true → Python assembler 永不 finalize → _buffers 泄漏 + episode
	// 数据丢失(I29 T-RR.1,~半数 episode 中招)。 marker NLegal=0:assembler 的
	// _capture_obs_np 对 n_legal==0 返 {} → 不产 DmcTransition,marker 仅作 done 信号 +
	// winner 载体(reward = terminalReward 从 engine g.Winner 算)。
	//
	// pushedAny==false(me 整局未行动 —— 对手在 me 首次行动前即结束游戏,极端情况)→
	// 不推 marker:assembler 端从无此 episode 的任何 transition,不会泄漏;该 episode
	// 无 me 决策、无训练价值,有意丢弃(语义保真 Python play_one_episode 的空 episode)。
	if pushedAny && transWri != nil {
		markerPayload := EncodeDmcTransitionPayload(
			0, step, terminalReward(g, me), 0, // chosen=0, nLegal=0
			nil, nil, nil, nil, staticHash,
		)
		marker := &gicg_actor.Transition{
			ClientID:  clientID,
			EpisodeID: episodeID,
			Step:      step,
			Done:      true,
			Payload:   markerPayload,
		}
		if err := transWri.Push(marker); err != nil {
			// 同 in-loop push:marker 写失败不致死 actor,本 episode 中止(orphan)。
			fmt.Fprintf(os.Stderr, "[gicg_actor] actor=%d ep=%d terminal marker push failed "+
				"— episode aborted, actor continues: %v\n", clientID, episodeID, err)
			return nil
		}
	}
	return nil
}

// terminalReward 返回 episode 终局 me 视角的 reward。 g.Winner 取值:0/1=对应玩家胜,
// 2=engine 判定平局,-1=进行中(Go 侧 MaxEpisodeSteps 截断、engine 未达 GameOver)。
// 截断与平局同归 0 —— 语义保真 Python terminal_z(training/paradigms/dmc/_episode.py,
// winner<0 → 0.0)。
func terminalReward(g *engine.Game, me int) float32 {
	switch g.Winner {
	case me:
		return 1.0
	case 1 - me:
		return -1.0
	default: // 2=draw,-1=truncated —— 均 0
		return 0.0
	}
}

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
