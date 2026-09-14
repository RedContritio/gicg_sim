# 2026-09-12 分支审计与清理

用户要求提交全部当前改动、合入 dev，并只保留 main / dev。
开始时没有 dev，也未配置任何 Git remote；所有操作均为本地操作。

| 分支 | 原始提交 | 用途和结论 |
|---|---|---|
| main | c87c73c | 当前主线，保留原位置 |
| i33-roundend-actor-ctx | cdc3f8b | 回合末 actor 语义、DSL 加载与牌组修复；本轮环境、NN、评估和重构在此积累，提交后合入 dev |
| i31-cfr-az-mp-pool-unification | 94c4541 | CFR/AZ 多进程池及权重同步；tree 与主线 b3d0922 完全一致，已 squash 合入 |
| dev/maintenance-governance | a37e111 | 治理与 pull/eval/sync 修复；tools/training 与 main 相同，文档后续清理已由 c87c73c 接续；旧历史完整归档 |
| i32-dmc-per | 35befd3 | PER、折扣 MC 回报及 gamma/lr 实验配置；6 个独有提交，尚未合入。不在清理时引入新算法，保存完整 Git 历史与 patch |
| worktree-wf_76b120e8-90f-31 | c87c73c | after-damage / after-heal 延迟回调审计，未提交探针已保存 |
| worktree-wf_76b120e8-90f-32 | c87c73c | 双方出战角色连续死亡导致 pending 覆盖的旧复现探针，已保存 |
| worktree-wf_76b120e8-90f-4 | c87c73c | clone/restore/reset 的准备技能、支援、装备、延迟回调审计，已保存 |

## 恢复资料

全部原分支历史位于 `artifacts/branch_cleanup_20260912/branches-before.bundle`，
已通过 `git bundle verify`，包含完整历史，无 prerequisite。
例如需要取回 PER 实验时：

```bash
git fetch artifacts/branch_cleanup_20260912/branches-before.bundle \
  refs/heads/i32-dmc-per:refs/heads/recovered-per
```

同目录 `i32.patch` 是相对 main 共同祖先的完整差异；`branches-before.txt` 记录原提交。
三个 worktree 的未跟踪及忽略文件已分别保存为同名 tar.gz，清单见 worktrees.json。
未提交探针另以 `.go.txt` 原件纳入本目录 probes/；它们是历史诊断材料，不作为当前测试执行。
其中有些断言以复现旧错误为成功标准，不能直接混入正式回归。

## 清理步骤

提交当前工作后，删除占用 dev 命名空间的旧维护分支，从 main 创建 dev 并合入本轮分支。
移除已归档的三个旧 worktree，删除其分支及其余已审计分支。
不删除 main，不触及现有 tag，不运行训练，不覆盖远端训练设备代码。

## 完成结果

- 当前实现提交：`1506454`；包含当时全部592个改动文件及探针审计材料。
- 合入 dev：`a4b59b8`，从 main 创建 dev 后使用 no-ff 合并，未发生冲突。
- 合并后的文件树与实现分支完全相同，原有验收结果继续适用。
- 已删除7个旧分支和3个旧worktree，仅保留 main / dev，当前停在 dev。
- main 仍位于 `c87c73c`；未配置remote，因此无远端分支或推送操作。
- 原hook路径指向不存在的位置，现已设置 `core.hooksPath=.githooks`，实际提交钩子通过。
- 归档内容已逐文件与worktree原件比较一致后才删除；未合入的PER实验没有丢失。
