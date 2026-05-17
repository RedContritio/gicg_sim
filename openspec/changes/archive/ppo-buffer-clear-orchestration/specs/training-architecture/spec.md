---
change_id: ppo-buffer-clear-orchestration
capability: training-architecture
delta_type: ADD
target_subtopic: protocols
---

# Spec Delta — training-architecture / protocols

> 本 delta 加 1 SHALL 到 `openspec/specs/training-architecture/protocols.md`
> § 4 Buffer protocol 末尾(merge target anchor:§ 4 末 "ckpt-able" SHALL 之后)。

## [ADD] § 4 Buffer protocol — On-policy buffer epilogue 契约

4. On-policy paradigm(e.g. PPO)SHALL 在 `step_schedule` 返回 `StepPlan` 时
   显式 set `clear_buffer_after_train=True` 声明 per-iter clear intent。Driver
   SHALL honor 此 flag,在 train block 结束后(eval / ckpt 之前)调用
   `buffer.clear()`。Off-policy / dataset-driven paradigm SHALL 保留 default
   `False`(无 clear 副作用)。

   **Rationale**:Buffer 是 paradigm-agnostic storage 抽象,clear 时机决策权
   归 paradigm — driver 不假定 buffer 类型。`StepPlan.clear_buffer_after_train:
   bool = False` 是显式 per-step 声明,与 `advance_step: int = 1` 同为带
   default 的 dispatcher field。

   **Failure mode if violated**:PPO 第 2 outer iter `collect` push 时 buffer
   仍持有第 1 iter transitions → `RolloutBuffer.push: over capacity` raise
   (per `paradigm-ppo/spec.md` § P4.1 on-policy invariant)。
