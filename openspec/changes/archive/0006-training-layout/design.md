# Design (retrospective)

## Consequences

### 落地结构

```
training/
  framework/          # 算法无关
    obs_constants.py
    step_encoding.py
    matchup/
      players.py       # MCTSPlayer 等
      gauntlet.py      # DEFAULT_SOCKET_PATH 内联
    inference_server.py
    buffer_base.py     # StaticDedupBufferBase
    agent_base.py      # AgentBase
    config_base.py     # TrainingConfig
  az/                 # AlphaZero
    selfplay.py
    mcts.py
    determinize.py
    replay.py
    network/actor_critic.py
    train_step.py
    async_loop.py
    arena.py
    config_loader.py
    parallel_inference.py  # AZ-specific worker pool
  cfr/                # Deep CFR
    traversal/
      __init__.py
      encoding.py
      config.py
      traverser.py        # CFRTraverser(TraverserBase, OSMixin, ESMixin)
      os_sampling.py
      es_sampling.py
    reservoir.py
    agent.py             # CFRAgent
    advantage_fit.py
    strategy_fit.py
    value_fit.py
```

### Subagent 审查 4 轮迭代

- v6 → v6.1: 6 项(pool-spec 公开化、MCTSPlayer 上提、DEFAULT_SOCKET_PATH 内联、traversal 5 分、
  buffer 基类正名、TrainConfig 改名)
- v6.1 → v6.2: 2 项(parallel_inference 归 az/、buffer 共享面收窄)
- v6.2 → v6.3: 2 项(AgentBase 跨包继承、step_encoding + structural 提取)
- end-review: 3 项(config_loader / arena / async_loop 归 az/,移除 7 处 agent 自作主张的向后兼容
  别名,移除 1 处 F401 re-export shim)

### 验证

- `tools._meta.check_line_limits training/` = 0 violations
- `pytest training/tests gicg_env/tests -n 2` 全绿 (394 passed)
- `ruff format --check` 通过

## Tradeoffs revisited

- **Atomic worktree refactor**:对 reviewer 不友好(diff 巨大),但避免中间状态有 broken import
- **`CollectorBuffer` duck-type 不抽**:接受小重复换 reservoir / collector 语义清晰
- **`AgentBase` 跨包继承**:framework 暴露 ABC,子包继承;权衡是 framework 保留少量 OO 抽象 vs 完全
  纯函数化

## References

- `docs/2_decisions/adr-0006-training_layout.md` (mirror)
- `training/framework/`、`training/az/`、`training/cfr/` — shipped tree
- Memory `project_training_layout` — 2026-04-23 ship summary
