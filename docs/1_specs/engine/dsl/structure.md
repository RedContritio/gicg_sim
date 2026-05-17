> **MOVED to `openspec/specs/engine-dsl/`**(2026-05-15,P1-T5)
>
> 本文档 §6 文件结构内容已迁到 OpenSpec(SHALL 语言):
> - [File structure](../../../../openspec/specs/engine-dsl/file-structure.md)
> - [Spec](../../../../openspec/specs/engine-dsl/spec.md)
>
> 卡牌难度分级(原 §7)→
> `docs/3_plans/cards/card_difficulty_grades.md`(curriculum 资料,无 SHALL)。
>
> 本文件保留至 P1++;**只读**。

---

# DSL 文件结构与卡牌分级

> 接续 [DSL 规范](README.md) 第 1-4 节和 [api.md](api.md) 第 5 节。

## 6. 文件结构

```
data/
  characters/
    赤蝶/
      赤蝶.lua              -- 角色声明：HP 上限、能量上限等元数据
      赤蝶_枪.lua           -- 纯基础效果（declare_skill + damage）
      赤蝶_蝶火.lua         -- buff 拥有其所有效果（附魔/加伤/回火条件治疗/衰减）
      赤蝶_回火.lua
    墨客/ 猫咪/ 刻师傅/ 天星/  -- 同上结构
  cards/
    L1/ 碌碌无为.lua
    L2/ 美味烧鸡.lua, 佛跳墙.lua, 占星.lua, 诅咒.lua
    L3/ 速速茶点.lua, 铁剑.lua, 铁枪.lua, 荷花酥.lua, 以牙还牙.lua, 反制.lua
    L4/ 铁弓.lua, 西风长枪.lua, 西风剑.lua, 瞬身之术.lua, 伏兵之术.lua,
        清洁时间.lua, 玄冰.lua
    L5/ 蝶鳞.lua, 守正.lua, 刺刺猫爪.lua, 发现静电.lua, 星愿.lua
    L6/ 以逸待劳.lua, 乘胜追击.lua, 以攻代守.lua
  system/
    reactions/
      蒸发.lua, 超载.lua, 融化.lua, 感电.lua, 冻结.lua, 超导.lua, 结晶.lua, 解冻.lua
    round.lua     -- AP counter 创建、回合开始 AP 重置、先手判定
    alive.lua     -- 死亡检测：on_after_write(alive, SUB) → set_alive → defer 强制切换
    element.lua   -- 元素附着 counter 系统
    frozen.lua    -- on_action_check 检查冻结 → 阻止技能和切换
    reaction.lua  -- 反应调度入口（遍历 reactions/ 子目录并派发）
    draw.lua      -- 开局抽 5 张、on_round_end_final 抽 2 张
    timeout.lua   -- 记录第一回合先手方、on_round_end_final 判负
    food.lua      -- 饱腹 counter、on_action_check 阻止再次使用食物
    equip.lua     -- 装备 counter 基础设施（武器/圣遗物）
```

引擎的 capi 加载器按固定顺序枚举 system 文件（见 `gicg_engine/capi/capi.go` 中的
`systemFiles`）；角色专属文件按绑定逐槽加载，卡牌文件全局拓扑排序一次，
详见 `../capi_mirror.md` §10。

## 7. 卡牌分级

> 已抽离到 `docs/3_plans/cards/card_difficulty_grades.md`(curriculum
> 资料,2026-05-15 P1-T5)。原 L1-L6 表见该文件。
