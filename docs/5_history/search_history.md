# Search 实测性能 + GPU 失败 + 耗时估算 (P1-T3 archived)

> 本文档抽取自:
> - `docs/1_specs/search/parallel.md` L332-383(实测性能 / MPS GPU
>   失败 / C1 验证 run 耗时估算)
>
> 当前 search 规约见:
> - [`openspec/specs/search-ismcts/`](../../openspec/specs/search-ismcts/spec.md) —
>   IS-MCTS 算法 + 确定化采样
> - [`openspec/specs/search-parallel/`](../../openspec/specs/search-parallel/spec.md) —
>   并行推理 + 异步训练流水
>
> 本文件保留作历史复盘 — 并行架构基准数据 + 失败决策依据
> (MPS GPU 在 d_model=64 规模 3-4× 慢于 CPU,作为"C1 规模不使用 GPU"
> 决策的证据)。
>
> 章节锚点:
> - `#virtual-loss-bench` — 虚损失并行 rollout 基准
> - `#batch-mean-from-overlap` — batch=4 来自重叠不是摊薄
> - `#mps-gpu-failure` — MPS GPU 失败数据
> - `#c1-run-time-estimation` — C1 验证 run 耗时估算

---

## 实测性能(2026-04 C1 规模) <a id="virtual-loss-bench"></a>

### 虚损失并行 rollout

基准条件:`d_model=64`,`n_cross_layers=2`,`n_rollouts=400`,MacBook
M 系列 CPU,`n_games=4`。

| 配置 | 同步 par=1 | 虚损失 par=4 | 加速 |
|---|---|---|---|
| nw=1 | 41.4s/game | 21.3s/game | 1.94× |
| nw=4 | 17.5s/game | **11.8s/game** | 1.49× |

`par=8` 实测和 `par=4` 持平,说明 server 已经饱和 — 进一步加
`parallel_rollouts` 不会继续给收益。

### batch_mean=4 的来源(重叠不是摊薄) <a id="batch-mean-from-overlap"></a>

虚损失流水线的加速(单 worker 1.94×)来自**重叠**,不是 batch 摊薄:
worker 内并行发出 4 条 rollout 的 eval 请求,在等待某条返回期间其他
rollout 可以继续 select/expand,从而把等待时间与树操作重叠。

但 server 端的实际 batch 大小受限于 `n_workers`,因为每个 worker 是
同步的(send-1-recv-1 稳态)。4 worker × par=4 并不会产生 batch=16
的请求堆积 —— 每个 worker 在任意时刻最多有 1 个 eval 请求在飞(发出
后立即阻塞等回复),所以 server 最多凑到 `batch=n_workers=4`。

**结论**:真正的加速来自流水线重叠,不是 batch 摊薄。Spec 侧的
`max_batch_size = 32` 是 capacity ceiling,实际稳态远低于此。

---

## MPS GPU 失败(d_model=64 规模) <a id="mps-gpu-failure"></a>

d_model=64 在 MPS 上 3-4× **慢于** CPU:

| 配置 | CPU | MPS | 倍率 |
|---|---|---|---|
| nw=1 | 38.0s | 148.6s | 3.91× 慢 |
| nw=4 | 17.2s | 64.0s | 3.72× 慢 |

**根因**:kernel launch overhead 在小矩阵乘法上主导耗时。`d_model=64`
的 matmul 计算量极小,MPS 每次 kernel dispatch 的固定开销远超实际
计算时间。需要 `d_model ≥ 256` 或 `batch ≥ 64` 才可能让 MPS 有正
收益。

**决策**:C1 规模暂不使用 GPU。该决策由
[`openspec/specs/search-parallel/inference-server.md`](../../openspec/specs/search-parallel/inference-server.md) §6.2
GPU 决策段引用本数据。

未来若 `d_model ≥ 256` 或 `batch ≥ 64`,通过 OpenSpec change 重新
评估并改 spec(详 [`search-parallel/spec.md`](../../openspec/specs/search-parallel/spec.md) §7)。

---

## C1 验证 run 耗时估算 <a id="c1-run-time-estimation"></a>

2000 局,4 worker,par=4 估算:

| 架构 | 耗时 |
|---|---|
| 老并行(worker-per-agent) | ~9.5 小时 |
| B+C sync(集中 server + 同步) | ~9.5 小时 |
| B+C + virtual loss(集中 server + 虚损失) | **~6.6 小时** |

**关键观察**:B+C sync 与老并行同等耗时 — 单纯集中化 inference
server 但同步等回复不带来加速。**真正的加速来自虚损失流水线重叠**
(rollout 内多个 eval 在飞 + tree 操作并行)。

打破这个天花板需要:
- 多 inference server 进程(突破单 server 吞吐)
- 或 GPU server(d_model ≥ 256 后重评估)
- 或减少每次 eval 的 Python/torch 开销(参见 issue #155 Go 化 rollout
  路径)

---

## 相关 OpenSpec change

- 暂无 — 本数据用于"C1 规模不使用 GPU"决策的证据,该决策已落入
  `openspec/specs/search-parallel/inference-server.md` §6.2,无单独
  change proposal。未来若任一升级触发(GPU / 多 server / Go rollout
  整体合并),将开新 change。
