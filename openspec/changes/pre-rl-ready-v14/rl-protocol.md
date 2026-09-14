# 下一阶段小范围 RL（准备完毕后另行启动）

## 固定首次预算

- 配置 configs/dmc/pre_rl_small.toml：当前1v1基础池，CPU serial，一演员，随机初始化。
- 三种子41/42/43，每个3000 agent frames，episode预算512，max_rounds8。
- 训练对手：配置继承的随机0.4 / F1D2 0.3 / 本轮历史策略0.3；不加载外部旧策略。
- checkpoint每50更新步，保留最后2份；最终策略按训练预算末尾选，不根据测试挑选。
- CPU dropout0。固定模型初始化、环境/对手/探索随机流；collector保存实际探索RNG。
  恢复功能通过smoke，不承诺异步、多硬件或不同线程配置逐位重现。
- terminal胜/负/平=1/-1/0，截断报错不作为输或平；不修改已确认规则。

## 评估

- 新独立评估master seed98000，每个对手32个scenario×双方换边=64局。
- 对手为均匀随机和F1D2；记录逐局结果、胜负平、win+0.5draw、配对bootstrap区间。
- 同预算前的随机初始化策略、均匀随机基线与最终策略均评估，禁止只报告最好种子。
- 预先判据：三种子均应胜过均匀随机（score>0.5），对F1D2相对初始化平均score
  改善至少0.05，且不超过一个种子退步；报告区间，不将小样本判据当统计显著性。
- 未达标时进入短程RL诊断，不直接扩至2v2/5070Ti或反复用同测试集调参。
- 通过后另登记2v2课程与新评估种子；以逸待劳/速速茶点继续封存。

## 运行入口（本次不执行）

```sh
.venv/bin/python -m tools.experiments.pre_rl
.venv/bin/python -m tools.runs.train configs/dmc/pre_rl_small.toml --override meta.seed=41 --override meta.run_label=small_rl_v14_s41
.venv/bin/python -m tools.runs.train configs/dmc/pre_rl_small.toml --override meta.seed=42 --override meta.run_label=small_rl_v14_s42
.venv/bin/python -m tools.runs.train configs/dmc/pre_rl_small.toml --override meta.seed=43 --override meta.run_label=small_rl_v14_s43
.venv/bin/python -m tools.experiments.evaluate_clean configs/dmc/pre_rl_small.toml RUN/ckpts/latest.pt RUN/evaluation.json --scenarios 32 --seed 98000
```

训练前先评估相同初始化模型（evaluate_clean 的 fresh:41/fresh:42/fresh:43）及 random。
RUN由tools.runs.train分配；必须替换为对应实际目录，不复用辅助训练权重。
