"""eval-service shared constants — single source of truth。

W2-3 (post-2026-05-28):pre-W2 `DEFAULT_HOST` / `DEFAULT_PORT` lived in
``tools/eval/eval_service.py`` 作为 production constant + 又复制一份
inline 到 ``training/core/gauntlet.py`` 因为 "framework → tools cross-
layer import 不可接受"(audit finding 高优 #3 — `gauntlet.py:4-17` 注释
自承避让 hack)。 集中到本 module 让两边都 import,delete inline 重复。

post W3+ eval_service production-tier files 全 mv 到 ``training/core/eval/``
(audit 全部 recommendation),本 module 是该路径的 staging。
"""

from __future__ import annotations


# Default bind host for the eval_service TCP server。 Localhost only —
# external exposure is intentionally not supported(container 部署用
# `-p 9100:9100` 显式映射)。
DEFAULT_HOST = 'localhost'

# Default bind port for the eval_service TCP server。
DEFAULT_PORT = 9100
