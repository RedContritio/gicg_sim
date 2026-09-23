# gicg_mono

一个轻量的七圣召唤规则、对局、训练与 Web 项目。Rust 负责规则执行，Python
负责环境、训练和评测，Web 提供可交互对局界面。

## 当前状态

更新时间：2026-09-23

| 模块 | 状态 |
| --- | --- |
| 对局引擎 | Rust 完整对局流程、元素反应、角色、卡牌、状态与选择结算 |
| 当前规则集 | 凯亚、八重神子、艾尔海森、千织、玛拉妮、玛薇卡及当前 15 张牌组所需卡牌 |
| Python 环境 | PettingZoo AEC 环境、状态编码、动作编码和 Rust 绑定 |
| 基线 | 可配置的 FxDy 贪心搜索与训练对手池，当前正式对手为 F1D2 |
| 主线算法 | 原生 DMC，学习执行动作的 `Q(s, a)`，支持 replay 与 checkpoint 恢复 |
| Web | 双方三角色、正常手牌和完整对局流程 |
| 远端运行 | Wake-on-LAN、同步、构建、训练、续训、评测、拉取和状态查询 |

FxDy 在所有深度使用启发式排序和 alpha-beta；D3 及以上只在内部节点展开评分最高的
8 个分支，根动作始终全部比较。常态评估使用 Random、F1D1 和 F1D2，F1D3 仅用于
搜索性能或强度专项检查。

修复击倒切人结算后的串行 DMC 已在 RTX 5070 Ti 上完成 10,000 局：

```text
D:/gicg_mono/artifacts/dmc/20260923_161230_000001/
```

该 run 包含完整配置、metadata、metrics、滚动 checkpoint 和最终
`checkpoint.pt`。最终 checkpoint 已拉回本地，并完成固定种子双座位评测：

| 对手 | 对局 | 胜 | 负 | 平 | 截断 | 胜率 | 95% 区间 | 先手胜率 | 后手胜率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Random | 1,000 | 1,000 | 0 | 0 | 0 | 100.0% | 99.62%–100.00% | 100.0% | 100.0% |
| F1D2 | 1,000 | 614 | 386 | 0 | 0 | 61.4% | 58.34%–64.37% | 67.8% | 55.0% |

Random 使用种子 20000–20499，F1D2 使用种子 30000–30499；每个种子各测试一个
先手和后手对局。原始逐局结果位于对应 run 的 `eval_vs_random.json` 和
`eval_vs_f1d2.json`。目前的规则内容是主线闭环，不是完整七圣召唤卡池。

并行吞吐实验 `20260923_165604_000001` 完成了 10,000 局且无截断，但将 batch
从 256 提高到 16,384、每局更新从 1 提高到 8 后，独立评估未通过质量门槛：

| 对手 | 对局 | 胜 | 负 | 截断 | 胜率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Random | 1,000 | 908 | 92 | 0 | 90.8% |
| F1D1 | 1,000 | 39 | 961 | 0 | 3.9% |
| F1D2 | 1,000 | 10 | 990 | 0 | 1.0% |
| F1D3 | 1,000 | 19 | 981 | 0 | 1.9% |

该 checkpoint 只保留为性能实验，不作为候选模型。并行采样和 GPU replay 保留，正式
训练恢复 batch 256、每局更新 1 次，并将策略快照批次收紧到 16 局。

## 结构

```text
data/          Lua 规则与牌表
gicg_engine/   Rust 规则执行器与 FxDy 搜索
gicg_env/      PyO3 绑定
python/gicg_ai Python 环境、DMC、评测与远端生命周期
web/           FastAPI 与静态 Web 界面
configs/       train / eval / web / hosts 配置
artifacts/     本地运行产物，不提交到 Git
```

规则只存在于 `data/`。Python 不复制规则逻辑；模型、replay、loss 和采集逻辑属于
DMC 算法内部。

## 本地启动

要求 Python 3.11+、Rust 1.90+ 和 Node.js 22+。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,train]'
.venv/bin/maturin develop
npm install
git config core.hooksPath .githooks
```

运行 Web：

```bash
.venv/bin/python -m web --config configs/web/local.toml
```

浏览器访问 `http://127.0.0.1:8000`。

运行本地训练闭环：

```bash
.venv/bin/python -m gicg_ai.train configs/train/smoke.toml
```

运行基线评测：

```bash
.venv/bin/python -m gicg_ai.evaluate configs/eval/smoke.toml
```

评测 DMC checkpoint：

```bash
.venv/bin/python -m gicg_ai.evaluate configs/eval/smoke.toml \
  --candidate-checkpoint artifacts/dmc/<run>/checkpoint.pt
```

正式评测配置为 `configs/eval/dmc_vs_random.toml` 和
`configs/eval/dmc_vs_f1d2.toml`。

运行时可用点路径覆盖已有配置项，不修改配置文件：

```bash
.venv/bin/python -m gicg_ai.evaluate configs/eval/dmc_vs_f1d2.toml \
  --set evaluation.device=mps
```

`--set` 可以重复使用；不存在的配置路径会直接失败。

## 训练语义

- DMC 直接回归本局执行动作的终局回报：胜 `+1`、平 `0`、负 `-1`。
- 学习方按 episode 轮换座位。
- `configs/train/dmc.toml` 通过 `[[training.opponents]]` 配置 Random 和任意 FxDy
  对手及其采样权重。
- 合法对局达到 `max_steps` 时单独记为截断，以中性回报 `0` 结算，不中止整次训练。
- checkpoint 保存模型、优化器、replay、随机数状态、规则哈希和训练签名。
- checkpoint 与规则、网络形状、设备类型或训练签名不一致时直接失败。

产物统一写入：

```text
artifacts/<experiment_tag>/<时间戳>_<六位序号>/
```

## 远端训练

机器信息只放在不会提交的 `configs/hosts.toml`：

```bash
cp configs/hosts.example.toml configs/hosts.toml
```

生命周期命令：

```bash
.venv/bin/python -m gicg_ai.remote wake gpu56
.venv/bin/python -m gicg_ai.remote sync gpu56
.venv/bin/python -m gicg_ai.remote prepare gpu56
.venv/bin/python -m gicg_ai.remote train gpu56 configs/train/dmc.toml
.venv/bin/python -m gicg_ai.remote status gpu56
.venv/bin/python -m gicg_ai.remote pull gpu56 --run artifacts/dmc/<run>
```

在远端执行 checkpoint 评测：

```bash
.venv/bin/python -m gicg_ai.remote evaluate gpu56 configs/eval/dmc_vs_f1d2.toml \
  --checkpoint artifacts/dmc/<run>/checkpoint.pt \
  --output artifacts/dmc/<run>/eval_vs_f1d2.json \
  --set evaluation.opponent=F1D1
```

从远端 checkpoint 续训：

```bash
.venv/bin/python -m gicg_ai.remote train gpu56 configs/train/dmc.toml \
  --resume artifacts/dmc/<run>/checkpoints/<episode>.pt
```

Windows OpenSSH 会清理脱离会话的子进程，因此 `train` 命令会保持 SSH 等待器直到
训练结束。训练发生在远端；关闭该命令会同时终止训练进程。

## 验证

```bash
.githooks/pre-commit
cargo test --workspace
.venv/bin/python -m pytest
```

完整检查由 GitHub Actions 执行。
