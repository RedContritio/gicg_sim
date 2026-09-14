---
plan: cleansing_schema
status: HISTORICAL
last_updated: 2026-09-14
---

# Card Cleansing Pipeline

> **历史方案**：本文记录 2026-04 的 raw/full/cleaned 流程。当前官方
> 内容抓取、差异和审核边界见
> [`native_content_curriculum.md`](native_content_curriculum.md)。

```
raw/<id>_<name>.json              (mihoyo wiki 抓取产物)
  │
  │  Sonnet subagent
  │    - 解二层 data JSON
  │    - 解 HTML escape + strip tags
  │    - 提取所有术语 tooltip 详情
  │    - 推断 sub_class / cost / duration / 触发时机(老数据无标签时)
  │    - 保留所有原始数据 + 可能引起歧义的详情
  ↓
full/<id>_<name>.yaml             (完整版,含 url/icon/术语展开/推断字段)
  │
  │  Python tool: tools/strip_card_yaml.py
  │    - 删除 URL/icon/header_img/version 等纯 visual
  │    - 保留所有机制字段
  ↓
cleaned/<id>_<name>.yaml          (化简版,只留分析需要的)
  │
  │  Opus(我)读 cleaned 做 DSL gap 分析
  ↓
docs/3_plans/cards/dsl_gaps.md
```

**关键决策**:阶段 1 用 sonnet **不是** Python — 因为 raw 里有些东西机器难做:
- 嵌入 HTML 的术语 tooltip(双重 escape)
- 老数据没显式 sub_class 标签,需要从 effect 文本推断
- skill cost 在 desc 文本里描述("消耗 3 风元素骰")
- 多义触发时机("受到伤害时" vs "进行普通攻击时")

阶段 2 用 Python — 因为只是字段过滤,确定性 100%。

---

## 阶段 1:full YAML schema(sonnet 输出)

**指导原则**:**保留所有原始数据**,不丢字段。Sonnet 解嵌套 + unescape +
推断,但**不删任何信息**。冗余优于丢失。

### 字段约定(sample + sqrt(N) 反馈后 finalize)

**cost 结构化**:
- `{same: N}` — 任意同色 N 个骰子(行动牌 attr「花费」常用)
- `{<元素>: N, 无色: M}` — 指定元素 + 任意无色(角色技能常用)
- `{any: N}` — 任意元素 N 个(无色骰)
- `{void: N}` — 显式无色 N 个(等价 `{无色: N}`,任选其一)

**energy 字段**:统一用 `energy_delta: ±N`(整数,签名):
- 普通攻击 / 元素战技 = `+1`(产生)
- 元素爆发 = 负值(消耗,如 `-3`)
- 不再用 `energy_gain` / `energy_consume`(分散)

**多版本字段** `variants`(替代 ad-hoc `alternate_mode`):
当一张卡有多套技能定义(如标准版 vs 自行巧局),用 `variants[]` 数组:

```yaml
variants:
  - mode: 标准              # 模式名,从 raw 取或描述
    skills: [...]
    talent: ...
  - mode: 自行巧局
    skills: [...]
```

只有真正多版本时用;单一版本卡正常用顶层 `skills` 即可,**不要**强加
`variants` 包装。

**数据噪声处理**(unsure / raw_value):
- attr key/value 异常(浊水幻灵 + 6 张丘丘 / 萨满 / 史莱姆 / 愚人众等老 monster 模板):同时保留 `raw_value`(原始)和 `value`(sonnet 清洗后),用 `unsure_reason` 字段说明
- effect_text 末尾冗余文本(机关·芒重复)→ 忽略 + 加 `unsure: 'wiki 编辑残留'` 注释
- **`unsure` 值含中文 `:` 时必须 quote**(YAML parser 见两个冒号会误判 mapping):写成 `unsure: "..."` 或 block scalar `unsure: |`

**特技(specials)**(角色级别新机制,4.x 版本起):
某些卡(目前见角色卡如希诺宁、装备牌如驰轮车·疾驰)附带"特技"子技能,
作为额外可用技能。**约束:每角色装备槽 1 张特技**(见领域笔记节)。

Character schema 加 `specials[]`:
```yaml
specials:
  - name: 高速腾跃
    cost: { void: 1 }
    effect_text: |
      切换到下一个我方角色,本回合中下次造成的伤害+1。
    duration: 可用次数 1
    icon: ...                # full YAML 留;cleaned 删
    term_refs: [...]
```

Action schema(特技装备牌,如驰轮车·疾驰)在 talent / equip 顶层之外
增加 `attached_special`:
```yaml
attached_special:
  name: 疾驰
  type: 特技
  cost: { void: 1 }
  effect_text: |
    ...
  icon: ...
```

(命名:`specials` 在角色侧表 owner 拥有的特技 list;`attached_special`
在装备牌侧表"装备此牌后给角色加这个特技"的 1:1 关系。)

**始基力 / 元素改造**(草神 / 水神后版本):
某些角色 attr 含「始基力」字段(如克洛琳德 = 荒性),记到顶层 `attr` 内
保留;DSL 元素枚举如何扩在 task #11 决定。

**HP 上限非 10**(如希诺宁 HP=12):卡数据驱动,DSL 不能 hardcode `hp_max=10`。

**角色多召唤物**(爱可菲 = 2 个):`summons[]` 是 list,自然支持。

### Character schema

```yaml
id: 500192
name: 流浪者
title: 久世浮倾·流浪者
parent_class: character
desc: 久世浮倾·流浪者卡牌
icon_url: https://act-upload.mihoyo.com/...
header_img_url: ""
version: "1771593033"
acquire: 角色邀请·友好对局

attr:
  元素: [风元素]
  武器: [法器]
  充能: []
  获取方式: [角色邀请·友好对局]

# 推断字段(机器难做,sonnet 必须填)
element: 风
weapon: 法器
hp: 10
energy: 3                    # 元素爆发能量上限,从爆发 skill cost 推断

skills:
  - name: 行幡鸣弦
    type: 普通攻击
    raw_life: 1              # raw life 字段(语义未确认,留作 audit)
    raw_energy: 2            # raw energy 字段
    cost:                    # 从 desc / icon 推断
      风: 1
      无色: 2
    energy_delta: +1
    icon: https://...
    effect_html: "<p>造成1点...</p>"     # 原始 HTML(完整保留)
    effect_text: 造成1点风元素伤害。      # strip 后纯文本
    term_refs: [风元素伤害]

  - name: 羽画·风姿华歌
    type: 元素战技
    raw_life: 3
    raw_energy: 0
    cost: { 风: 3 }
    energy_delta: +1
    icon: ...
    effect_html: ...
    effect_text: |
      造成2点风元素伤害,本角色附属优风倾姿。
    term_refs: [风元素伤害, 优风倾姿]

  - name: 狂言·式乐五番
    type: 元素爆发
    raw_life: 3
    raw_energy: 3
    cost: { 风: 3 }
    energy_delta: -3
    icon: ...
    effect_html: ...
    effect_text: |
      造成7点风元素伤害;
      如果角色附属有优风倾姿,则将其移除并使此伤害+1。
    term_refs: [风元素伤害, 优风倾姿]

talent:
  name: 梦迹一风
  type: 装备牌(战斗行动)
  cost: { 风: 3 }
  raw_life: 4
  raw_energy: 0
  icon: ...
  effect_html: ...
  effect_text: |
    我方出战角色为流浪者时,装备此牌。
    流浪者装备此牌后,立刻使用一次羽画·风姿华歌。
    装备有此牌的流浪者在优风倾姿状态下进行重击后:
      下次从该角色执行「切换角色」行动时少花费 1 个元素骰,
      并且造成 1 点风元素伤害。
  deck_constraint: 牌组中包含流浪者,才能加入牌组
  term_refs: [战斗行动, 优风倾姿, 风元素伤害, 羽画·风姿华歌]

summons: []

flavor_html: ...
flavor_text: 久世浮倾·流浪者千般劫渡,不可得知。

# 全卡引用的术语 → 完整解释(sonnet 从 data-name 提取)
terms:
  风元素伤害: |
    和已附着的元素发生元素反应:
    扩散(冰):对目标以外的所有敌方角色造成 1 点冰元素伤害
    扩散(水)/扩散(火)/扩散(雷):同上
  优风倾姿: |
    状态。所附属角色进行普通攻击时:造成的伤害+2;
    如果敌方存在后台角色,则此技能改为对下一个敌方后台角色造成伤害。
    可用次数: 2
  战斗行动: |
    我方执行了一次战斗行动后,会轮到对方行动。
    打出具有此规则的手牌是一个战斗行动,而非快速行动。
  可用次数: |
    此牌效果触发后,会消耗 1 次可用次数;
    可用次数耗尽后,立刻弃置此牌。

_raw_path: raw/character/500192_流浪者.json
```

### Action schema

```yaml
id: 500023
name: 老章
parent_class: action
sub_class: 支援牌                # 从 attr「类型」直取或从 effect 推断
tags: [伙伴]                     # attr「标签」
cost_text: 2同色                 # 从 attr「花费」+ 推断
cost: { same: 2 }                # 结构化 cost
icon_url: ...
attr:
  类型: [支援牌]
  标签: [伙伴]
  花费: ["2"]
  获取: [...]
effect_html: ...
effect_text: |
  ...
duration: 持续 / 可用次数 N / 一次性
term_refs: [...]
terms: {...}
flavor_text: ...
_raw_path: ...
```

### Monster schema

```yaml
id: 500546
name: 压制特化型机关·芒
parent_class: monster
hp: ...
element: ...
skills: [...]
flavor_text: ...
terms: {...}
_raw_path: ...
```

---

## 阶段 2:cleaned YAML schema(Python 工具输出)

`tools/strip_card_yaml.py` 从 full YAML 删以下字段(纯 visual / audit):

```yaml
# 删除字段:
- icon_url
- header_img_url
- version
- icon                      # skill[].icon, talent.icon, ...
- effect_html               # skill[].effect_html(保留 effect_text)
- talent.effect_html
- flavor_html               # 保留 flavor_text
- _raw_path
```

保留:**所有机制字段** + **术语字典** + **flavor 纯文本**。

工具是 deterministic YAML key 过滤器,~30 行 Python。

---

## 工具行为约束(strip_card_yaml.py)

- 输入:`full/<type>/<id>_<name>.yaml` 或目录
- 输出:`cleaned/<type>/<id>_<name>.yaml`
- 字段删除规则:`_DROP_KEYS = {'icon_url', 'header_img_url', 'version', 'icon', 'effect_html', 'flavor_html', '_raw_path'}`
- 递归遍历 dict / list 删 key
- 不动 effect_text / cost / 术语字典
- `--merge-glossary` 选项产 `cleaned/_glossary.yaml`(全卡 terms 合并,同名取最长解释)

---

## Sonnet subagent 任务规格

每次 invoke 处理 1 张卡或一个 batch:
- 输入:raw JSON 路径列表
- 输出:对应 full YAML 文件 in `data/full/<type>/<id>_<name>.yaml`
- 严格遵守上述 schema(否则 strip_card_yaml.py 找不到字段会 fail)
- **冲突处理**:同一字段有多源时(如 attr.元素 vs 顶层 element),保留两者,sonnet 自己判断哪个准
- **不发明字段**:schema 没列的不加;不确定就留 `unsure: <description>` 子字段
- **HTML 完整保留**:effect_html 不删 tag(给将来 web UI 渲染用)

---

## Sample 阶段(task #10)

3 类各 3 张:
- character:500192_流浪者 / 500194_迪希雅 / 500195_瑶瑶
- action:500023_老章(支援) / 500020_风物之诗咏(装备) / 500019_最终解释权(装备)
- monster:500546_压制特化型机关·芒 / 502488_浊水幻灵 / 500548_攻坚特化型机关·芒

跑完看 schema 是否需要补字段或简化。

---

## 领域笔记(DSL gap analysis 时参考)

raw / cleaned schema 不直接表达的游戏规则约束,记在这里供 task #11 分析时引用。

### 特技(specialty)槽

特技是 4.x 版本引入的新机制:某些装备牌(如「驰轮车·疾驰」家族)装备时
附带一个"特技"子技能,可作为额外技能使用。

**约束**(2026-04-28 待最终确认):**每个角色 / 玩家只能装备 1 张特技牌**。
具体粒度(per-char vs per-player)需要在 cleansing 完成后从更多样本验证。

**对 DSL 的影响**:
- 若 per-char:Counter `Scope.Self`,1 槽限制
- 若 per-player:Counter `Scope.PerPlayer`,1 槽
- 装备时需检查槽位空,违反则不可打出
- 当前 DSL 的 `requires_char` / `requires_weapon` 约束机制可能需扩展支持"slot_type=specialty"

### (其他领域笔记预留位置)

后续清洗中遇到的特殊机制(共鸣 / 秘传 / 大世界状态等)记在此节。

---

## 弃用说明

`tools/parse_raw_card.py`(2026-04-28 PM 早期产物)做的是"机器化 parse",
跟本 plan 的 sonnet-first 思路冲突,弃用。代码仍在仓库以备将来若 sonnet
不能稳定输出时回退用。
