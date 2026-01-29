# DSL 数据目录

本目录存放基于《技能 DSL 设计文档》的角色与技能配置。

- **role/**：角色元数据（YAML），与 `data/role/` 对应，供解析层引用。
- **skill/**：技能 **纯 DSL 脚本**（`.dsl`），用约定语法描述技能消耗、效果及 Token/Hook，供解析层/执行层处理；**不用 YAML/JSON 写技能逻辑**。

解析层：DSL 脚本文本 → 结构化数据  
执行层：结构化数据 + 游戏上下文 → 实际结算

---

## 技能 DSL 中 `cost` 的结构

**`cost [<元素> <数量> | any <数量>]* energy <数量>`**

- **`<元素> <数量>`**：指定元素骰个数；元素为 `pyro` `hydro` `cryo` `electro` `anemo` `geo` `dendro`。可多段，支持双属性等（如 1 冰 1 火）。
- **`any <数量>`**：任意骰个数。
- **`energy <数量>`**：能量；必须放在最后。

示例：
- `cost cryo 3 energy 0` = 3 冰、0 能量  
- `cost cryo 1 any 2 energy 0` = 1 冰 + 2 任意、0 能量  
- `cost cryo 1 pyro 1 any 2 energy 0` = 1 冰 + 1 火 + 2 任意、0 能量（双属性）  
- `cost anemo 3 energy 3` = 3 风 + 3 能量
