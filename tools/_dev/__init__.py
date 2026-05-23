"""tools/_dev — 一次性 / 临时 diagnostic 工具,非 production path。

模块下脚本走 ad-hoc dispatch(env-var gate / 显式 import),production 入口
不应无条件依赖。 入选标准:跨多次 session 复用 的 perf / mem / IO 调试器。

不属于此处的:
- 一次跑完弃 → 直接 inline。
- 长期 production infra → tools/runs/ 或 training/core/perf/。
"""
