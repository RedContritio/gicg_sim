# 验收与续跑边界

## 修复

异步统计读取 `EpisodeRecord.scenario_seed`，不再访问 serial 的局部变量 `seeds`。
回归用不同、逆序到达的种子检查统计原样保留；不声称异步已支持 serial 的四路随机流。
异步和多进程测试 17 项通过，强化后的逆序种子用例单独通过。

## 拆分

| 原模块 | 抽出的职责 |
|---|---|
| capi_state.go | capi_observation.go：观测尺寸、常量和静态数据导出 |
| damage.go | heal_energy.go：治疗和能量变更 |
| observation_dynamic.go | observation_history.go：伤害/准备技能/修正日志编码 |
| card_yiyidailao_test.go | card_yiyidailao_counter_test.go：治疗与护盾反击 |
| game_snap_pool_test.go | game_snap_pool_bench_test.go：快照性能基准 |
| helpers_setup_test.go | helpers_dsl_paths_test.go：DSL 文件选择与解析 |
| _engine_lifecycle.py | _engine_state.py：重置、克隆、快照、隐藏状态设置 |
| env.py | env_state.py：公开状态与底层查询转发 |
| agent_base.py | agent_observation.py：观测缓存与张量解析 |
| dmc/_agent.py | _agent_batch.py：批量前向 |
| dmc/_decoder.py | _capture_obs.py：actor 的 numpy 观测捕获 |

公开入口保持不变；搬移的 42 个 Python 函数节点（包含嵌套函数）AST 一致。
全部改动文件通过行数限制、Ruff 格式、Go 格式和空白检查，不跳过提交钩子。
Go 全套通过，本机 C 共享库重建成功。Python 本轮回归 1348 passed、6 skipped、22 warnings，42.26 秒；
按仓库默认标记排除 smoke_full、integration、smoke_remote。详细命令与日志见 verification.json。

回归另外暴露出一个耗时用例：深度 4 的无限预算搜索默认完整手牌，分支过大。
为预算等价测试设置双方空手牌、空牌库和三个万能骰，保留深度 4、多个合法动作、
无限预算与 1e9 预算同动作的断言；单例 0.46 秒通过。生产搜索算法没有改动。

## 旧训练

重构前来源 `8bc1dce77cd90f8eaf7f71be117bdf532df1da036bd8f62123b79521bf1a8dc5`。
完整源码归档 `artifacts/refactor_20260912/pre_refactor_source.tar.gz`，
归档 SHA 和文件数见同目录 baseline.json。远端 `D:/gicg_dev` 保留旧运行代码。

旧检查点仍只在匹配的旧源码下恢复；新源码不自动接受旧来源。
本轮没有改写旧 checkpoint、manifest、经验池，也没有放宽来源校验或重新开训。
如要续跑本轮 30k 实验，应使用远端原代码并验证完整的 `ckpt_<step>.pt`；
如要在新代码中开始实验，需按新的来源清单独立登记，不能静默混合。
