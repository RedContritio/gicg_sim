// paradigm.go — DMC Paradigm impl(adapter.go Paradigm interface 实现)。
//
// Phase 1.2a 是 stub:Run loop 不真跑 episode,只 idle 等 ctx.Done(),便于 hello-world
// e2e 验证 paradigm registry + pool spawn + Go runtime + libgicg_actor c-shared 全栈
// 端到端跑通。
//
// Phase 1.2b/c ship 真 episode loop:
//   - 创建 engine instance(`engine.NewGame(spec)`,native Go,~ms 级 init)
//   - 缓存 static hash(每 episode 算一次,跨 turn 不变)
//   - 主循环:
//     · acting player == me: BuildInferRequest → InferenceClient.Request → 解码 chosen
//       action idx → engine.Step → push transition(opt)
//     · acting player == opp: greedy_player.SelectAction(F1-D2/D4)→ engine.Step
//     · engine.Done(): push final transition + break
//   - episode 完结 → new engine instance + 继续

package dmc

import (
	"context"
	"sync"

	"gicg_mono/gicg_actor"
)

// DMCParadigm implements gicg_actor.Paradigm。
type DMCParadigm struct {
	// Phase 1.2b/c 扩 config:scenario spec / opp pool ratios / max actions / max episode steps。
	// 当前 stub:零 state。
}

func (p *DMCParadigm) Name() string {
	return "dmc"
}

// Run — Phase 1.2a stub:idle 等 ctx.Done。 Phase 1.2c 替换为完整 episode loop。
//
// 设计目标(Phase 1.2c):
//   - 单 goroutine own 一个 engine instance(跨 episode reuse,reduce alloc churn)
//   - infCli / transWri 可为 nil(本地测试场景 / paradigm registry test);production 必填
//   - ctx.Done() 检查频率 ≥ 每 episode start(保证 stop_pool 信号 ≤ episode_wall 内响应)
func (p *DMCParadigm) Run(ctx context.Context, actorID int, infCli *gicg_actor.InferenceClient, transWri *gicg_actor.TransitionWriter) error {
	<-ctx.Done()
	return nil
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
