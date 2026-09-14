# 2026-09-14 dev 工作区提交与 main 合并判断

用户要求先提交当前工作，再判断是否合main。本次保存原生五角色/23行动牌、引擎规则修复、语义网络、随机变体与辅助RL工具、网页适配、评估测试及交接文档。版本文件v0.2.0；这是开发快照，不是稳定模型或正式PvE发布。

## 验证

- 暂存文件格式、行数/字节限制及OpenSpec索引hook通过。
- `go test ./gicg_engine/... ./gicg_actor/... ./gicg_mcts/...` 全通过（需要访问系统Go缓存）。
- `web/frontend` 的 `npm run build` 通过；已有大bundle提示，非构建错误。
- Python范围：gicg_env/tests、training/tests、tools/experiments、tools/rule_validation、tools/cards/tests、tools/runs/tests、web/backend/tests；默认排除full smoke。
- 首次沙箱内2257 passed/36 failed/12 errors/7 skipped。对48个失败/错误项在授权环境重跑，43 passed/5 failed。合计2300项通过，5项仍失败，7项跳过；不是全绿回归。
- 已知残余：actor_critic_mirror完整前向交换视角logit相同；tune_actions四个调和动作仅两种logit；semantic_live三个测试因网页绑定历史模型来源指纹不兼容而失败。不能绕过指纹守卫或更改旧权重来源。
- 按CLAUDE重复失败规则已请求独立只读review。剩余失败需要修复或以证据证明测试假设失效，不能仅删除断言。

## 分支判断

提交前main是dev祖先，main无独立新增提交，可以fast-forward，无须制造merge冲突。**本次只提交dev，不合main**：先解决5项残余回归，再按拟合入版本重验。随机变体尚未稳定胜过D2属于研究目标未完成，本身不应作为代码永远不能合main的理由。

未push远端Git，未打release标签。56训练继续，未同步提交导致任何训练代码变动。模型与实验产物仍在本地/56 artifacts，不包含在源码Git提交中。新session先读docs/0_status/README.md与docs/HANDOFF.md。

## 独立复核结论

- 调和失败是真实兼容缺口：旧DmcAgent通路未消费card_hook_links/skill_links；canonical hook去ID后，不同弃牌同骰色的动作表示合并。需补旧DMC采样、训练、推理的定义关联编码，不能改断言为2。当前semantic网络已有独立关联编码，不据此推断56实验失效。
- 镜像并非精确相同：小CPU前向typed差4.45e-4、policy差2.03e-6、value差4.41e-5；原测试atol1e-5误判。需要受控干预与梯度检查，不能仅随意放宽阈值。
- 网页需兼容模型或兼容测试fixture，保留指纹守卫。独立review未改代码或影响56。
- 主实现快照提交为`a40c729`；本记录增补单独提交。main仍停留原提交，不推送。
