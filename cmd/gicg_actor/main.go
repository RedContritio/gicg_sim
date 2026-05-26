// Package main — standalone Go-actor executable (I29 redesign 2026-05-25)。
//
// 与 master Python 走 SHMRing transition (master 0 cgo lib loaded,deal-breaker
// invariant #1 of docs/superpowers/specs/2026-05-25-i29-redesign-design.md)。
//
// Lifecycle:读 stdin Config JSON 一次 → attach SHM ring → 构 TransitionWriterShm sink →
// 调 gicg_actor.Run(ctx, cfg, infReqs, sinks) → 输出 "READY" 通知 master init 完毕 → 阻塞至
// Run 返回 (paradigm.Run finish 或 ctx cancel) → exit 0。
//
// main 负责 wire 配置 → sink → Run。 ParadigmName 必传(placeholder PoC path 已退役 — I29 A4
// cleanup 2026-05-25):per-actor 创 TCP InferenceClient → infReqs slice → DMC paradigm.Run。
//
// Master Python 用 subprocess.Popen spawn 本 binary,见
// training/core/actor/go_subprocess.py:GoSubprocessHandle。
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/signal"
	"runtime"
	"syscall"
	"time"

	"gicg_mono/gicg_actor"
	// DMC paradigm side-effect import — registers "dmc" with gicg_actor.RegisterParadigm
	// via init()。 P1.3 cmd-path 只需 DMC (subagent brief 边界);P2 起 AZ/PPO 同模式加 import。
	_ "gicg_mono/gicg_actor/dmc"
	"gicg_mono/gicg_actor/shm"
)

// Config — stdin JSON schema。 字段命名 snake_case 与 Python 侧 go_subprocess.py 对应。
//
// 字段集:
//   - NActors / TransShmName / TransShmCapacity / TransShmSlotSize — SHMRing wire
//   - ParadigmName / ParadigmConfig / InfServerAddr — production paradigm 路径
//   - BaseActorID — I29 R7.2 N independent subprocess 拓扑,各 subprocess NActors=1 +
//     BaseActorID=i ∈ [0, N) 让 clientID 跨 subprocess 唯一(否则 SHM ring 上 (cid, ep_id) 撞)
type Config struct {
	NActors          int    `json:"n_actors"`
	TransShmName     string `json:"trans_shm_name"`
	TransShmCapacity int    `json:"trans_shm_capacity"`
	TransShmSlotSize int    `json:"trans_shm_slot_size"`
	// BaseActorID — I29 R7.2 N-subprocess 拓扑用:master spawn 第 i 个 subprocess 时传
	// BaseActorID=i,actor goroutine 内 clientID = BaseActorID + local_idx,跨 subprocess
	// 不撞 key。 默认 0(legacy / single subprocess 路径)。
	BaseActorID int `json:"base_actor_id,omitempty"`

	// GoMaxProcs — Go runtime GOMAXPROCS cfg-driven (I29 R6.1)。 cfg-driven only per
	// [[feedback_cfg_driven_only]] — 不走 env var GOMAXPROCS。
	// Default 0 (unset / 0 = Go runtime default = NumCPU):R6.1 verify mixed-opp
	// workload (minimax f1d2/f1d4 opp) 下 GOMAXPROCS=1 跌 ~76% (13.44 → 3.11 fps/actor),
	// random-only workload 几无差 (52.81 vs 53.01),综合 default NumCPU 双 workload 都不 hurt。
	// 详 tools/_bench/p2_results/PHASE2_VERIFY_REPORT.md R6.1 Bench 2 mixed workload safety check。
	// 显式设 >= 1 时按值传 runtime.GOMAXPROCS;<= 0 跳过 runtime.GOMAXPROCS 调用 (Go runtime 自管 NumCPU)。
	GoMaxProcs int `json:"go_gomaxprocs,omitempty"`

	// production paradigm 字段 — main 起 N inference client (per-actor),paradigm.Run
	// 走真 inference + 真 episode loop。
	// Inference transport: TCP only (I29 R7.1 删 SHM inference path — InfServer
	// socket_listener thread 已 ship + bridge layer 消除,与 Python mp wire 等价)。
	// InfServerAddr 非空时起 N TCP InferenceClient (per-actor)。
	InfServerAddr  string `json:"inf_server_addr,omitempty"`
	ParadigmName   string `json:"paradigm_name"`
	ParadigmConfig string `json:"paradigm_config,omitempty"`
	// IOTimeoutMs — inference I/O deadline (default 30s)。 TCP socket Read/Write deadline。
	IOTimeoutMs int `json:"io_timeout_ms,omitempty"`
}

// parseConfig — 读 stdin 单条 JSON object 反序列化为 Config。 fail-loud on n_actors <= 0
// 或 trans_shm_name 空 或 paradigm_name 空 或 paradigm_name 非空时 inf_server_addr 空。
func parseConfig(r io.Reader) (*Config, error) {
	var cfg Config
	if err := json.NewDecoder(r).Decode(&cfg); err != nil {
		return nil, fmt.Errorf("parseConfig decode: %w", err)
	}
	if cfg.NActors <= 0 {
		return nil, fmt.Errorf("parseConfig: n_actors must be > 0, got %d", cfg.NActors)
	}
	if cfg.BaseActorID < 0 {
		return nil, fmt.Errorf("parseConfig: base_actor_id must be >= 0, got %d", cfg.BaseActorID)
	}
	if cfg.TransShmName == "" {
		return nil, fmt.Errorf("parseConfig: trans_shm_name required")
	}
	if cfg.ParadigmName == "" {
		return nil, fmt.Errorf("parseConfig: paradigm_name required (placeholder PoC path 已退役)")
	}
	// production paradigm path 必须有 TCP inference transport (I29 R7.1 删 SHM,
	// TCP 与 Python mp wire 等价 — InfServer socket_listener thread accept N TCP
	// client 进 request_q 与 mp.Queue 走同一 batch forward path)。
	if cfg.InfServerAddr == "" {
		return nil, fmt.Errorf("parseConfig: paradigm_name=%q 要求 inf_server_addr (TCP)", cfg.ParadigmName)
	}
	return &cfg, nil
}

// toPkgConfig — main.Config → gicg_actor.Config (透传字段)。
// SHM transition ring 在本 main attach 后传给 sink,不进 pkg Config。
func toPkgConfig(c *Config) gicg_actor.Config {
	return gicg_actor.Config{
		NActors:            c.NActors,
		ParadigmName:       c.ParadigmName,
		ParadigmConfigJSON: c.ParadigmConfig,
		InfServerAddr:      c.InfServerAddr,
		IOTimeoutMs:        c.IOTimeoutMs,
		BaseActorID:        c.BaseActorID,
	}
}

// buildInferenceClients — TCP path: 起 N 条 TCP InferenceClient (per-actor),Connect
// 失败时关已 connected 的 + 返 err (caller 退出 4 后 master 见 stderr fail-loud)。
// 镜像 gicg_actor/pool.go:StartPoolWithConfig 的 per-actor TCP path,production-proven。
func buildInferenceClients(addr string, n int, timeout time.Duration) ([]gicg_actor.InferenceRequester, error) {
	out := make([]gicg_actor.InferenceRequester, 0, n)
	for i := 0; i < n; i++ {
		c := gicg_actor.NewInferenceClient(addr, timeout)
		if err := c.Connect(); err != nil {
			// 关已 connected — 防 partial-init 文件描述符泄漏。
			for _, prev := range out {
				_ = prev.Close()
			}
			return nil, fmt.Errorf("InferenceClient actor=%d connect %s: %w", i, addr, err)
		}
		out = append(out, c)
	}
	return out, nil
}

func main() {
	cfg, err := parseConfig(os.Stdin)
	if err != nil {
		fmt.Fprintf(os.Stderr, "gicg_actor: %v\n", err)
		os.Exit(2)
	}

	// I29 R6.1 — GOMAXPROCS cfg-driven (default Go runtime NumCPU when <= 0)。
	// 必须在 game/interp/SHM attach 之前起 effect (runtime.GOMAXPROCS 改变 GC + scheduler
	// thread pool 全局 state)。 cfg.GoMaxProcs <= 0 时跳过 runtime.GOMAXPROCS 调用让
	// Go 自管 NumCPU (random-only workload OK,mixed-opp workload R6.1 Bench 2 verify
	// GOMAXPROCS=1 跌 76% regression 不能 default 1)。
	// 详 Config.GoMaxProcs doc + PHASE2_VERIFY_REPORT.md R6.1。
	if cfg.GoMaxProcs > 0 {
		runtime.GOMAXPROCS(cfg.GoMaxProcs)
	}

	// Attach 共享 SHM ring (Python master 已 create_owner)。
	// shm.Attach 自动 NormaliseName ("/" prefix for POSIX);Python 端 ring_shm.py 也已用同
	// prefix create,跨进程 wire 对齐。
	total := shm.RingTotalSize(cfg.TransShmCapacity, cfg.TransShmSlotSize)
	ring, err := shm.Attach(cfg.TransShmName, total)
	if err != nil {
		fmt.Fprintf(os.Stderr, "gicg_actor: shm.Attach %q failed: %v\n", cfg.TransShmName, err)
		os.Exit(3)
	}
	defer ring.Close()

	// Sink shared by all N actor goroutines (MPSC ring,shm_ring_push CAS-safe)。
	// owned=false → Close 不关 ring,由 main defer ring.Close 统一管。
	sink := gicg_actor.NewTransitionWriterShm(ring)
	sinks := []gicg_actor.TransitionSink{sink}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// SIGTERM / SIGINT → graceful cancel。 master 用 SIGTERM (subprocess.terminate);
	// Ctrl+C 用 SIGINT (人手调试)。 Go runtime 默认不接 SIGTERM,需显式 signal.Notify
	// (历史教训 [[feedback_go_cgo_signal_handler]] 在 c-shared lib 路径下更严重,本 standalone
	// executable 路径下 Go runtime 自管 signal,但显式 handler 更可控)。
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGTERM, syscall.SIGINT)
	go func() {
		<-sig
		cancel()
	}()

	// production path:per-actor inference client upfront — fail-loud (exit 4) on
	// any connect failure (master 见 stderr 立即诊断;actor goroutine 起跑后才发现
	// 不通已是 N 个 partial-init 死局)。
	// I29 R7.1: TCP only (SHM inference path 删 — InfServer socket_listener thread
	// 与 Python mp mp.Queue 等价 wire,无 bridge layer)。
	timeoutMs := cfg.IOTimeoutMs
	if timeoutMs <= 0 {
		timeoutMs = 30_000
	}
	timeout := time.Duration(timeoutMs) * time.Millisecond
	infReqs, err := buildInferenceClients(cfg.InfServerAddr, cfg.NActors, timeout)
	if err != nil {
		fmt.Fprintf(os.Stderr, "gicg_actor: %v\n", err)
		os.Exit(4)
	}
	defer func() {
		for _, c := range infReqs {
			_ = c.Close()
		}
	}()

	// 通知 master init 完毕 (master.GoSubprocessHandle.spawn 读 stdout 等 "READY")。
	// 必须 explicit Sync 才确保 line-buffered subprocess.PIPE 立即 flush 到 master。
	// Print 在 Run 之前 (Run 阻塞),保 master 不会因等 READY 超时。
	// READY 在 InferenceClient connect 之后 — master 看到 READY 即知 inf TCP 已 established,
	// 后续 paradigm.Run 第一次 Request 不会因 dial 失败 stall。
	fmt.Println("READY")
	_ = os.Stdout.Sync()

	pkgCfg := toPkgConfig(cfg)
	if err := gicg_actor.Run(ctx, pkgCfg, infReqs, sinks); err != nil {
		fmt.Fprintf(os.Stderr, "gicg_actor: Run: %v\n", err)
		os.Exit(5)
	}
}

// _ = io.EOF — 保留 io import 给 parseConfig 用 (Decoder reads from io.Reader)。
var _ = io.EOF
